import datetime
import os
from zoneinfo import ZoneInfo
import aiohttp
import discord
from discord.ext import commands, tasks
from shared import load_economy, save_economy, _get_guild_channels

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# ESPN unofficial scoreboard — no key, no rate limits
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_PATHS = {
    "NFL": "football/nfl",
    "NBA": "basketball/nba",
    "MLB": "baseball/mlb",
    "NHL": "hockey/nhl",
    "KBO": "baseball/kbo",
    "NPB": "baseball/npb",
    "UFC": "mma/ufc",
}

SPORT_KEYS = {
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
    "KBO": "baseball_kbo",
    "NPB": "baseball_npb",
    "UFC": "mma_mixed_martial_arts",
}
SPORT_EMOJI = {"NFL": "🏈", "NBA": "🏀", "MLB": "⚾", "NHL": "🏒", "KBO": "⚾", "NPB": "⚾", "UFC": "🥊"}

# Sports where only moneyline makes sense (no spread/total)
MONEYLINE_ONLY = {"UFC"}
MARKET_ALIASES = {
    "ml": "h2h", "h2h": "h2h", "moneyline": "h2h",
    "spread": "spreads", "spreads": "spreads",
    "total": "totals", "totals": "totals", "ou": "totals",
}
MARKET_LABEL = {"h2h": "ML", "spreads": "Spread", "totals": "Total"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _init_sports(eco):
    eco.setdefault("sports_events", {})
    eco.setdefault("sports_bets", {})
    eco.setdefault("next_sports_event_id", 1)
    eco.setdefault("next_sports_bet_id", 1)


def _parse_dt(iso_str):
    return datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def _fmt_odds(american):
    """Format American odds: +130 or -150."""
    return f"+{american}" if american > 0 else str(american)


def _fmt_line(line):
    """Format a spread/total line: +3.5 or -3.5."""
    return f"+{line}" if line > 0 else str(line)


def _calc_payout(amount, american_odds):
    """Return total coins returned (stake + profit) for a winning bet."""
    if american_odds > 0:
        return round(amount + amount * (american_odds / 100))
    else:
        return round(amount + amount * (100 / abs(american_odds)))


def _parse_event(game, sport_label, eco):
    """Upsert a game from The Odds API into eco['sports_events']. Returns (short_id, event)."""
    api_id = game["id"]

    # Find existing entry by api_id
    for sid, ev in eco["sports_events"].items():
        if ev.get("api_id") == api_id:
            _update_odds(ev, game)
            return sid, ev

    short_id = str(eco["next_sports_event_id"])
    eco["next_sports_event_id"] += 1
    event = {
        "id": short_id,
        "api_id": api_id,
        "sport": sport_label,
        "home": game["home_team"],
        "away": game["away_team"],
        "commence_time": game["commence_time"],
        "status": "upcoming",
        "home_score": None,
        "away_score": None,
        "odds": {},
        "settled": False,
    }
    _update_odds(event, game)
    eco["sports_events"][short_id] = event
    return short_id, event


def _update_odds(event, game):
    """Parse bookmaker odds from API response into the event dict."""
    bookmakers = game.get("bookmakers", [])
    if not bookmakers:
        return
    bk = bookmakers[0]
    home, away = game["home_team"], game["away_team"]
    for market in bk.get("markets", []):
        mk = market["key"]
        outcomes = market["outcomes"]
        if mk == "h2h":
            ho = next((o["price"] for o in outcomes if o["name"] == home), None)
            ao = next((o["price"] for o in outcomes if o["name"] == away), None)
            if ho is not None and ao is not None:
                event["odds"]["h2h"] = {"home": ho, "away": ao}
        elif mk == "spreads":
            hs = next((o for o in outcomes if o["name"] == home), None)
            as_ = next((o for o in outcomes if o["name"] == away), None)
            if hs and as_:
                event["odds"]["spreads"] = {
                    "home": {"line": hs["point"], "price": hs["price"]},
                    "away": {"line": as_["point"], "price": as_["price"]},
                }
        elif mk == "totals":
            ov = next((o for o in outcomes if o["name"] == "Over"), None)
            un = next((o for o in outcomes if o["name"] == "Under"), None)
            if ov and un:
                event["odds"]["totals"] = {
                    "line": ov["point"],
                    "over_price": ov["price"],
                    "under_price": un["price"],
                }


def _settle_event(eco, short_id, home_score, away_score):
    """Settle all open bets for a completed game. Returns notification tuples."""
    event = eco["sports_events"].get(short_id)
    if not event or event["settled"]:
        return []

    event["home_score"] = home_score
    event["away_score"] = away_score
    event["status"] = "completed"
    event["settled"] = True
    event["settled_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    results = []
    for uid, bets in eco["sports_bets"].items():
        for bet in bets:
            if bet["game_id"] != short_id or bet.get("settled"):
                continue

            won = _determine_outcome(bet, event, home_score, away_score)
            bet["settled"] = True
            bet["won"] = won

            if won is None:
                payout = bet["amount"]  # push: refund stake
            elif won:
                payout = _calc_payout(bet["amount"], bet["odds"])
            else:
                payout = 0

            bet["payout"] = payout
            if payout > 0:
                eco["balances"][uid] = round(eco["balances"].get(uid, 0) + payout, 2)
            results.append((uid, bet, event, won, payout))

    return results


def _determine_outcome(bet, event, home_score, away_score):
    """Return True (win), False (loss), or None (push)."""
    market, pick = bet["market"], bet["selection"]

    if market == "h2h":
        if home_score == away_score:
            return None
        return (pick == "home") == (home_score > away_score)

    elif market == "spreads":
        sp = event["odds"]["spreads"][pick]["line"]
        if pick == "home":
            diff = home_score + sp - away_score
        else:
            diff = away_score + sp - home_score
        if diff == 0:
            return None
        return diff > 0

    elif market == "totals":
        total = home_score + away_score
        line = event["odds"]["totals"]["line"]
        if total == line:
            return None
        return (pick == "over") == (total > line)

    return None


# ── Cog ───────────────────────────────────────────────────────────────────────

class SportsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        if ODDS_API_KEY:
            self.fetch_odds_task.start()
        self.settle_bets_task.start()  # ESPN needs no key

    async def cog_unload(self):
        self.fetch_odds_task.cancel()
        self.settle_bets_task.cancel()

    # ── Background: refresh odds every 6 hours ────────────────────────────────

    @tasks.loop(hours=6)
    async def fetch_odds_task(self):
        eco = load_economy()
        _init_sports(eco)
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(hours=6)

        async with aiohttp.ClientSession() as session:
            for sport_label, sport_key in SPORT_KEYS.items():
                try:
                    async with session.get(
                        f"{ODDS_API_BASE}/sports/{sport_key}/odds",
                        params={
                            "apiKey": ODDS_API_KEY,
                            "regions": "us",
                            "markets": "h2h,spreads,totals",
                            "oddsFormat": "american",
                            "dateFormat": "iso",
                        },
                    ) as resp:
                        if resp.status != 200:
                            continue
                        games = await resp.json()
                except Exception:
                    continue

                for game in games:
                    commence = _parse_dt(game["commence_time"])
                    if commence < cutoff:
                        continue
                    _parse_event(game, sport_label, eco)

        save_economy(eco)

    @fetch_odds_task.before_loop
    async def before_fetch_odds(self):
        await self.bot.wait_until_ready()

    # ── Background: settle completed games via ESPN (free, no key) ───────────────

    @tasks.loop(minutes=3)
    async def settle_bets_task(self):
        eco = load_economy()
        _init_sports(eco)
        now = datetime.datetime.now(datetime.timezone.utc)

        sports_needing_scores = {
            ev["sport"]
            for ev in eco["sports_events"].values()
            if not ev["settled"] and _parse_dt(ev["commence_time"]) <= now
        }
        if not sports_needing_scores:
            return

        # Build lookup: (home_name, away_name) -> (sid, event) for fast matching
        pending = {
            (ev["home"], ev["away"]): (sid, ev)
            for sid, ev in eco["sports_events"].items()
            if not ev["settled"] and _parse_dt(ev["commence_time"]) <= now
        }

        settlement_results = []
        today = now.strftime("%Y%m%d")
        yesterday = (now - datetime.timedelta(days=1)).strftime("%Y%m%d")

        async with aiohttp.ClientSession() as session:
            for sport_label in sports_needing_scores:
                path = ESPN_PATHS[sport_label]
                for date_str in (today, yesterday):
                    try:
                        async with session.get(
                            f"{ESPN_BASE}/{path}/scoreboard",
                            params={"dates": date_str},
                        ) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.json()
                    except Exception:
                        continue

                    for event in data.get("events", []):
                        if not event.get("status", {}).get("type", {}).get("completed"):
                            continue
                        competition = (event.get("competitions") or [{}])[0]
                        competitors = competition.get("competitors", [])
                        if not competitors:
                            continue

                        if sport_label == "UFC":
                            # MMA: no scores — settle by winner flag
                            # ESPN lists both fighters; check athlete name against stored names
                            for c in competitors:
                                athlete = (c.get("athlete") or c.get("team") or {})
                                name = athlete.get("displayName") or athlete.get("name", "")
                                if not c.get("winner"):
                                    continue
                                # Find which pending event this winner belongs to
                                for key, (sid, ev) in list(pending.items()):
                                    home_name, away_name = key
                                    if name in (home_name, away_name):
                                        home_score = 1.0 if name == home_name else 0.0
                                        away_score = 0.0 if name == home_name else 1.0
                                        results = _settle_event(eco, sid, home_score, away_score)
                                        settlement_results.extend(results)
                                        pending.pop(key, None)
                                        break
                        else:
                            # Team sports: settle by score
                            home_c = next((c for c in competitors if c.get("homeAway") == "home"), None)
                            away_c = next((c for c in competitors if c.get("homeAway") == "away"), None)
                            if not home_c or not away_c:
                                continue
                            home_name = home_c["team"]["displayName"]
                            away_name = away_c["team"]["displayName"]
                            match = pending.get((home_name, away_name))
                            if not match:
                                continue
                            sid, _ = match
                            try:
                                home_score = float(home_c.get("score", 0))
                                away_score = float(away_c.get("score", 0))
                            except (TypeError, ValueError):
                                continue
                            results = _settle_event(eco, sid, home_score, away_score)
                            settlement_results.extend(results)
                            pending.pop((home_name, away_name), None)

        save_economy(eco)

        guild_channels = _get_guild_channels()
        for uid, bet, event, won, payout in settlement_results:
            emoji = SPORT_EMOJI.get(event["sport"], "🏆")
            for gid, ch in guild_channels:
                member = ch.guild.get_member(int(uid))
                if not member:
                    continue
                if won is None:
                    outcome = f"**PUSH** — **{payout:,} coins** refunded"
                elif won:
                    outcome = f"**WON** — +**{payout:,} coins** 🎉"
                else:
                    outcome = f"**LOST** — **{bet['amount']:,} coins** gone 😢"
                await ch.send(
                    f"{emoji} {member.mention} Bet **#{bet['id']}** settled: "
                    f"**{event['away']} @ {event['home']}** — {outcome}"
                )
                break

    @settle_bets_task.before_loop
    async def before_settle(self):
        await self.bot.wait_until_ready()

    # ── !odds ─────────────────────────────────────────────────────────────────

    @commands.command(name="odds")
    async def odds_cmd(self, ctx, sport: str = None):
        """Show upcoming game lines. Usage: !odds [NFL|NBA|MLB|NHL]"""
        if not ODDS_API_KEY:
            await ctx.send(
                "⚠️ Sports betting is not configured. Set `ODDS_API_KEY` in your `.env` file. "
                "Get a free key at https://the-odds-api.com/"
            )
            return

        eco = load_economy()
        _init_sports(eco)
        now = datetime.datetime.now(datetime.timezone.utc)

        sport_filter = sport.upper() if sport else None
        if sport_filter and sport_filter not in SPORT_KEYS:
            await ctx.send(f"Unknown sport. Options: {', '.join(SPORT_KEYS)}")
            return
            return

        events = [
            ev for ev in eco["sports_events"].values()
            if not ev["settled"]
            and (not sport_filter or ev["sport"] == sport_filter)
        ]
        events.sort(key=lambda e: e["commence_time"])

        if not events:
            await ctx.send(
                "No upcoming games in the books right now. "
                "Lines refresh every 6 hours automatically."
            )
            return

        lines = ["🎰 **Sportsbook — Upcoming Lines**\n"]
        for ev in events[:8]:
            commence_et = _parse_dt(ev["commence_time"]).astimezone(ZoneInfo("America/New_York"))
            emoji = SPORT_EMOJI.get(ev["sport"], "🏆")
            lines.append(
                f"{emoji} **#{ev['id']}** — **{ev['away']}** @ **{ev['home']}** "
                f"| {commence_et.strftime('%a %b %-d %-I:%M %p ET')}"
            )
            is_mma = ev.get("sport") in MONEYLINE_ONLY
            if "h2h" in ev["odds"]:
                h = ev["odds"]["h2h"]
                if is_mma:
                    lines.append(
                        f"  **ML (pick fighter):** {ev['away']} {_fmt_odds(h['away'])}  ·  {ev['home']} {_fmt_odds(h['home'])}"
                    )
                else:
                    lines.append(
                        f"  **ML:** {ev['away']} {_fmt_odds(h['away'])}  ·  {ev['home']} {_fmt_odds(h['home'])}"
                    )
            if not is_mma:
                if "spreads" in ev["odds"]:
                    sp = ev["odds"]["spreads"]
                    lines.append(
                        f"  **Spread:** {ev['away']} {_fmt_line(sp['away']['line'])} ({_fmt_odds(sp['away']['price'])})  ·  "
                        f"{ev['home']} {_fmt_line(sp['home']['line'])} ({_fmt_odds(sp['home']['price'])})"
                    )
                if "totals" in ev["odds"]:
                    t = ev["odds"]["totals"]
                    lines.append(
                        f"  **O/U {t['line']}:** Over {_fmt_odds(t['over_price'])}  ·  Under {_fmt_odds(t['under_price'])}"
                    )
            lines.append("")

        lines.append("`!bet <#> <ml|spread|total> <home|away|over|under> <coins>` to wager")
        await ctx.send("\n".join(lines)[:1990])

    # ── !bet ──────────────────────────────────────────────────────────────────

    @commands.command(name="bet")
    async def place_bet(self, ctx, game_id: str = None, market: str = None, pick: str = None, amount: int = None):
        """Place a sports bet. Usage: !bet <#> <ml|spread|total> <home|away|over|under> <coins>"""
        if not all([game_id, market, pick, amount]) or amount <= 0:
            await ctx.send(
                "Usage: `!bet <#> <ml|spread|total> <home|away|over|under> <coins>`\n"
                "Examples: `!bet 3 ml away 500`  ·  `!bet 3 spread home 200`  ·  `!bet 3 total over 100`\n"
                "See `!odds` for open games."
            )
            return

        market_key = MARKET_ALIASES.get(market.lower())
        if not market_key:
            await ctx.send("Market must be `ml`, `spread`, or `total`.")
            return

        pick = pick.lower()
        if market_key in ("h2h", "spreads") and pick not in ("home", "away"):
            await ctx.send(f"For `{market}`, pick must be `home` or `away`.")
            return
        if market_key == "totals" and pick not in ("over", "under"):
            await ctx.send("For `total`, pick must be `over` or `under`.")
            return

        eco = load_economy()
        _init_sports(eco)
        uid = str(ctx.author.id)
        now = datetime.datetime.now(datetime.timezone.utc)

        event = eco["sports_events"].get(game_id)
        if event and event.get("sport") in MONEYLINE_ONLY and market_key != "h2h":
            await ctx.send(f"UFC/MMA only supports moneyline (`ml`) bets — pick `home` or `away` fighter.")
            return
        if not event or event["settled"]:
            await ctx.send(f"Game **#{game_id}** not found. Check `!odds`.")
            return

        if _parse_dt(event["commence_time"]) <= now:
            await ctx.send("❌ This game has already started — betting is closed.")
            return

        if market_key not in event["odds"]:
            await ctx.send(f"No **{MARKET_LABEL[market_key]}** line available for this game.")
            return

        if market_key == "h2h":
            odds = event["odds"]["h2h"][pick]
            pick_label = f"{event['home'] if pick == 'home' else event['away']}"
        elif market_key == "spreads":
            sp = event["odds"]["spreads"][pick]
            odds = sp["price"]
            pick_label = f"{event['home'] if pick == 'home' else event['away']} {_fmt_line(sp['line'])}"
        else:
            t = event["odds"]["totals"]
            odds = t["over_price"] if pick == "over" else t["under_price"]
            pick_label = f"{pick.capitalize()} {t['line']}"

        bal = eco["balances"].get(uid, 0)
        if bal < amount:
            await ctx.send(f"Not enough coins. You have **{bal:,}**, bet costs **{amount:,}**.")
            return

        eco["balances"][uid] = round(bal - amount, 2)
        bet_id = eco["next_sports_bet_id"]
        eco["next_sports_bet_id"] += 1
        eco["sports_bets"].setdefault(uid, []).append({
            "id": bet_id,
            "game_id": game_id,
            "market": market_key,
            "selection": pick,
            "amount": amount,
            "odds": odds,
            "placed_at": now.isoformat(),
            "settled": False,
            "won": None,
            "payout": None,
        })
        save_economy(eco)

        potential = _calc_payout(amount, odds)
        commence_et = _parse_dt(event["commence_time"]).astimezone(ZoneInfo("America/New_York"))
        emoji = SPORT_EMOJI.get(event["sport"], "🏆")
        await ctx.send(
            f"✅ **Bet #{bet_id}** placed! {emoji} **{event['away']} @ {event['home']}**\n"
            f"**{pick_label}** {_fmt_odds(odds)} — **{amount:,} coins** wagered · "
            f"potential return **{potential:,} coins**\n"
            f"Game: {commence_et.strftime('%a %b %-d %-I:%M %p ET')}"
        )

    # ── !mybets ───────────────────────────────────────────────────────────────

    @commands.command(name="mybets")
    async def my_bets(self, ctx, status: str = "open"):
        eco = load_economy()
        _init_sports(eco)
        uid = str(ctx.author.id)
        all_bets = eco["sports_bets"].get(uid, [])

        show = all_bets if status.lower() == "all" else [b for b in all_bets if not b["settled"]]
        if not show:
            await ctx.send(
                "No sports bets found. Use `!bet` to place one, or `!mybets all` to see history."
            )
            return

        lines = [f"🎰 **{ctx.author.display_name}'s Bets** ({status})\n"]
        for bet in show[-15:]:
            ev = eco["sports_events"].get(bet["game_id"], {})
            matchup = f"{ev.get('away', '?')} @ {ev.get('home', '?')}" if ev else f"Game #{bet['game_id']}"
            mk_label = MARKET_LABEL.get(bet["market"], bet["market"])
            pick_display = bet["selection"].capitalize()

            if bet["settled"]:
                if bet["won"] is None:
                    result = f"PUSH (+{bet['payout']:,})"
                elif bet["won"]:
                    result = f"WON +{bet['payout']:,} 🎉"
                else:
                    result = f"LOST -{bet['amount']:,} ❌"
            else:
                result = f"open — {_calc_payout(bet['amount'], bet['odds']):,} to win"

            lines.append(
                f"**#{bet['id']}** {matchup} | {mk_label} {pick_display} {_fmt_odds(bet['odds'])} | "
                f"{bet['amount']:,} wagered | {result}"
            )

        lines.append("\n`!cancelsportsbet <id>` to cancel an open bet before game start")
        await ctx.send("\n".join(lines)[:1990])

    # ── !cancelsportsbet ──────────────────────────────────────────────────────

    @commands.command(name="cancelsportsbet")
    async def cancel_sports_bet(self, ctx, bet_id: int = None):
        if not bet_id:
            await ctx.send("Usage: `!cancelsportsbet <id>`")
            return
        eco = load_economy()
        _init_sports(eco)
        uid = str(ctx.author.id)
        bets = eco["sports_bets"].get(uid, [])
        bet = next((b for b in bets if b["id"] == bet_id and not b["settled"]), None)
        if not bet:
            await ctx.send(f"Bet **#{bet_id}** not found or already settled.")
            return

        event = eco["sports_events"].get(bet["game_id"])
        if event and _parse_dt(event["commence_time"]) <= datetime.datetime.now(datetime.timezone.utc):
            await ctx.send("Game has already started — this bet can't be cancelled.")
            return

        eco["sports_bets"][uid].remove(bet)
        eco["balances"][uid] = round(eco["balances"].get(uid, 0) + bet["amount"], 2)
        save_economy(eco)
        await ctx.send(f"✅ Bet **#{bet_id}** cancelled — **{bet['amount']:,} coins** refunded.")

    # ── !sportsbook ───────────────────────────────────────────────────────────

    @commands.command(name="sportsbook")
    async def sportsbook_cmd(self, ctx):
        eco = load_economy()
        _init_sports(eco)

        events = [ev for ev in eco["sports_events"].values() if not ev["settled"]]
        events.sort(key=lambda e: e["commence_time"])

        total_wagered = sum(
            b["amount"]
            for bets in eco["sports_bets"].values()
            for b in bets if not b["settled"]
        )
        open_bet_count = sum(
            1 for bets in eco["sports_bets"].values() for b in bets if not b["settled"]
        )

        lines = [
            f"🏆 **Sportsbook** — {len(events)} open events · "
            f"{open_bet_count} open bets · {total_wagered:,} coins at risk\n"
        ]
        for ev in events[:10]:
            commence_et = _parse_dt(ev["commence_time"]).astimezone(ZoneInfo("America/New_York"))
            emoji = SPORT_EMOJI.get(ev["sport"], "🏆")
            bets_on_game = sum(
                1 for bets in eco["sports_bets"].values()
                for b in bets if b["game_id"] == ev["id"] and not b["settled"]
            )
            bet_str = f" · {bets_on_game} bet{'s' if bets_on_game != 1 else ''}" if bets_on_game else ""
            lines.append(
                f"{emoji} **#{ev['id']}** {ev['away']} @ **{ev['home']}** — "
                f"{commence_et.strftime('%a %b %-d %-I:%M %p ET')}{bet_str}"
            )

        lines.append(
            "\n`!odds [NFL|NBA|MLB|NHL]` · `!bet <#> <ml|spread|total> <pick> <coins>` · "
            "`!mybets` · `!mybets all`"
        )
        await ctx.send("\n".join(lines)[:1990])


async def setup(bot):
    await bot.add_cog(SportsCog(bot))
