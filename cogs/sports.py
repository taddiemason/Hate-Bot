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
    eco.setdefault("sports_parlays", {})
    eco.setdefault("next_sports_event_id", 1)
    eco.setdefault("next_sports_bet_id", 1)
    eco.setdefault("next_sports_parlay_id", 1)


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


def _to_decimal(american):
    return (american / 100 + 1) if american > 0 else (100 / abs(american) + 1)


def _to_american(decimal):
    if decimal >= 2.0:
        return round((decimal - 1) * 100)
    return round(-100 / (decimal - 1))


def _parlay_combined_odds(legs):
    """Return (decimal_product, american_odds) for the active (non-push) legs."""
    active = [l for l in legs if l.get("result") != "push"]
    decimal = 1.0
    for leg in active:
        decimal *= _to_decimal(leg["odds"])
    return decimal, _to_american(decimal)


def _settle_parlays(eco, settled_sid):
    """Resolve any parlay legs tied to settled_sid. Returns notification tuples."""
    event = eco["sports_events"].get(settled_sid)
    if not event or not event.get("settled"):
        return []

    results = []
    for uid, parlays in eco.get("sports_parlays", {}).items():
        for parlay in parlays:
            if parlay["settled"]:
                continue
            changed = False
            for leg in parlay["legs"]:
                if leg["game_id"] != settled_sid or leg.get("result"):
                    continue
                outcome = _determine_outcome(leg, event, event["home_score"], event["away_score"])
                leg["result"] = "push" if outcome is None else ("win" if outcome else "loss")
                changed = True

            if not changed:
                continue

            lost = [l for l in parlay["legs"] if l.get("result") == "loss"]
            pending_legs = [l for l in parlay["legs"] if not l.get("result")]

            if lost:
                parlay["settled"] = True
                parlay["won"] = False
                parlay["payout"] = 0
                results.append((uid, parlay))
            elif not pending_legs:
                wins = [l for l in parlay["legs"] if l.get("result") == "win"]
                if not wins:
                    # All pushed — full refund
                    payout = parlay["amount"]
                    parlay["settled"] = True
                    parlay["won"] = None
                    parlay["payout"] = payout
                else:
                    decimal, _ = _parlay_combined_odds(parlay["legs"])
                    payout = round(parlay["amount"] * decimal)
                    parlay["settled"] = True
                    parlay["won"] = True
                    parlay["payout"] = payout
                eco["balances"][uid] = round(eco["balances"].get(uid, 0) + parlay["payout"], 2)
                results.append((uid, parlay))

    return results


def _sports_leaderboard_stats(eco):
    """Return list of (uid, stats_dict) sorted by net profit descending."""
    stats = {}

    for uid, bets in eco.get("sports_bets", {}).items():
        settled = [b for b in bets if b.get("settled") and b.get("won") is not None]
        if not settled:
            continue
        wagered = sum(b["amount"] for b in settled)
        payouts = sum(b.get("payout", 0) for b in settled)
        wins = sum(1 for b in settled if b["won"] is True)
        stats.setdefault(uid, {"wagered": 0, "payout": 0, "wins": 0, "total": 0})
        stats[uid]["wagered"] += wagered
        stats[uid]["payout"] += payouts
        stats[uid]["wins"] += wins
        stats[uid]["total"] += len(settled)

    for uid, parlays in eco.get("sports_parlays", {}).items():
        settled = [p for p in parlays if p.get("settled") and p.get("won") is not None]
        if not settled:
            continue
        stats.setdefault(uid, {"wagered": 0, "payout": 0, "wins": 0, "total": 0})
        for p in settled:
            stats[uid]["wagered"] += p["amount"]
            stats[uid]["payout"] += p.get("payout", 0)
            stats[uid]["total"] += 1
            if p["won"] is True:
                stats[uid]["wins"] += 1

    for uid, s in stats.items():
        s["net"] = s["payout"] - s["wagered"]
        s["win_pct"] = round(s["wins"] / s["total"] * 100, 1) if s["total"] else 0

    return sorted(stats.items(), key=lambda x: x[1]["net"], reverse=True)


async def _fetch_live_scores(sport_labels):
    """Fetch in-progress game scores from ESPN for the given sports.

    Returns a dict keyed by (home_name, away_name) ->
      {"home_score", "away_score", "detail", "clock", "sport"}
    """
    results = {}
    async with aiohttp.ClientSession() as session:
        for sport_label in sport_labels:
            path = ESPN_PATHS.get(sport_label)
            if not path:
                continue
            try:
                async with session.get(f"{ESPN_BASE}/{path}/scoreboard") as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
            except Exception:
                continue

            for event in data.get("events", []):
                status = event.get("status", {})
                state = status.get("type", {}).get("state", "")
                if state != "in":
                    continue
                detail = status.get("type", {}).get("detail", "Live")
                clock = status.get("displayClock", "")
                competition = (event.get("competitions") or [{}])[0]
                competitors = competition.get("competitors", [])

                if sport_label == "UFC":
                    names = [
                        (c.get("athlete") or c.get("team") or {}).get("displayName", "?")
                        for c in competitors
                    ]
                    if len(names) >= 2:
                        results[(names[0], names[1])] = {
                            "home_score": None, "away_score": None,
                            "detail": detail, "clock": "", "sport": sport_label,
                        }
                else:
                    home_c = next((c for c in competitors if c.get("homeAway") == "home"), None)
                    away_c = next((c for c in competitors if c.get("homeAway") == "away"), None)
                    if not home_c or not away_c:
                        continue
                    try:
                        hs = int(float(home_c.get("score", 0)))
                        as_ = int(float(away_c.get("score", 0)))
                    except (TypeError, ValueError):
                        hs = as_ = 0
                    key = (home_c["team"]["displayName"], away_c["team"]["displayName"])
                    results[key] = {
                        "home_score": hs, "away_score": as_,
                        "detail": detail, "clock": clock, "sport": sport_label,
                    }
    return results


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
        "start_notified": False,
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
        self.settle_bets_task.start()
        self.game_start_notifier.start()

    async def cog_unload(self):
        self.fetch_odds_task.cancel()
        self.settle_bets_task.cancel()
        self.game_start_notifier.cancel()

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
        parlay_results = []
        settled_sids = set()
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
                                        settled_sids.add(sid)
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
                            settled_sids.add(sid)
                            pending.pop((home_name, away_name), None)

        for sid in settled_sids:
            parlay_results.extend(_settle_parlays(eco, sid))

        save_economy(eco)

        guild_channels = _get_guild_channels()
        for uid, bet, event, won, payout in settlement_results:
            emoji = SPORT_EMOJI.get(event["sport"], "🏆")
            score_str = ""
            if event.get("home_score") is not None and event.get("sport") not in MONEYLINE_ONLY:
                score_str = f" (**{int(event['away_score'])}–{int(event['home_score'])}** final)"
            elif event.get("sport") in MONEYLINE_ONLY and event.get("home_score") is not None:
                winner = event["home"] if event["home_score"] > event["away_score"] else event["away"]
                score_str = f" ({winner} wins)"
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
                    f"**{event['away']} @ {event['home']}**{score_str} — {outcome}"
                )
                break

        for uid, parlay in parlay_results:
            for gid, ch in guild_channels:
                member = ch.guild.get_member(int(uid))
                if not member:
                    continue
                payout = parlay["payout"]
                won = parlay["won"]
                if won is None:
                    outcome = f"**PUSH** — **{payout:,} coins** refunded"
                elif won:
                    _, combined_american = _parlay_combined_odds(parlay["legs"])
                    outcome = f"**WON** — +**{payout:,} coins** 🎉 ({_fmt_odds(combined_american)} parlay)"
                else:
                    lost_leg = next((l for l in parlay["legs"] if l.get("result") == "loss"), None)
                    busted_on = f" (busted on: {lost_leg['matchup']})" if lost_leg else ""
                    outcome = f"**LOST** — **{parlay['amount']:,} coins** gone 😢{busted_on}"
                leg_count = len(parlay["legs"])
                await ch.send(
                    f"🎰 {member.mention} **{leg_count}-leg parlay #{parlay['id']}** settled — {outcome}"
                )
                break

    @settle_bets_task.before_loop
    async def before_settle(self):
        await self.bot.wait_until_ready()

    # ── Background: notify channel when a bet-active game kicks off ───────────

    @tasks.loop(minutes=3)
    async def game_start_notifier(self):
        eco = load_economy()
        _init_sports(eco)
        now = datetime.datetime.now(datetime.timezone.utc)
        guild_channels = _get_guild_channels()
        if not guild_channels:
            return

        changed = False
        for sid, ev in eco["sports_events"].items():
            if ev.get("settled") or ev.get("start_notified"):
                continue
            if _parse_dt(ev["commence_time"]) > now:
                continue

            # Gather all straight bets on this game
            straight = [
                (uid, bet)
                for uid, bets in eco.get("sports_bets", {}).items()
                for bet in bets
                if bet["game_id"] == sid and not bet["settled"]
            ]
            # Gather parlay legs on this game
            parlay_legs = [
                (uid, parlay, leg)
                for uid, parlays in eco.get("sports_parlays", {}).items()
                for parlay in parlays if not parlay["settled"]
                for leg in parlay["legs"]
                if leg["game_id"] == sid and not leg.get("result")
            ]

            ev["start_notified"] = True
            changed = True

            if not straight and not parlay_legs:
                continue  # no bets on this game — mark notified but stay quiet

            total_coins = sum(b["amount"] for _, b in straight) + sum(
                p["amount"] for _, p, _ in parlay_legs
            )
            emoji = SPORT_EMOJI.get(ev["sport"], "🏆")
            commence_et = _parse_dt(ev["commence_time"]).astimezone(ZoneInfo("America/New_York"))

            for gid, ch in guild_channels:
                # Per-bettor summary (deduplicated by uid)
                seen = {}
                for uid, bet in straight:
                    if uid not in seen:
                        seen[uid] = []
                    mk = MARKET_LABEL.get(bet["market"], bet["market"])
                    team = ev["home"] if bet["selection"] == "home" else ev["away"]
                    pick = f"{mk} {team}" if bet["market"] == "h2h" else f"{mk} {bet['selection'].capitalize()}"
                    seen[uid].append(f"{pick} {_fmt_odds(bet['odds'])} ({bet['amount']:,})")
                for uid, parlay, leg in parlay_legs:
                    if uid not in seen:
                        seen[uid] = []
                    seen[uid].append(f"{leg['pick_label']} [parlay #{parlay['id']}]")

                lines = [
                    f"{emoji} **KICKOFF** — **{ev['away']} @ {ev['home']}** (#{sid})",
                    f"⏰ {commence_et.strftime('%a %b %-d %-I:%M %p ET')} · 💰 {total_coins:,} coins at risk",
                ]
                if "h2h" in ev["odds"]:
                    h = ev["odds"]["h2h"]
                    lines.append(
                        f"  ML: {ev['away']} {_fmt_odds(h['away'])}  ·  {ev['home']} {_fmt_odds(h['home'])}"
                    )
                for uid, picks in list(seen.items())[:8]:
                    member = ch.guild.get_member(int(uid))
                    name = member.mention if member else f"<@{uid}>"
                    lines.append(f"  {name}: {' · '.join(picks)}")
                if len(seen) > 8:
                    lines.append(f"  _...and {len(seen) - 8} more_")

                await ch.send("\n".join(lines))

        if changed:
            save_economy(eco)

    @game_start_notifier.before_loop
    async def before_start_notifier(self):
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
        now = datetime.datetime.now(datetime.timezone.utc)

        show = all_bets if status.lower() == "all" else [b for b in all_bets if not b["settled"]]
        if not show:
            await ctx.send(
                "No sports bets found. Use `!bet` to place one, or `!mybets all` to see history."
            )
            return

        # Fetch live scores for sports with in-progress open bets
        open_sports = {
            eco["sports_events"][b["game_id"]]["sport"]
            for b in show if not b["settled"]
            and b["game_id"] in eco["sports_events"]
            and not eco["sports_events"][b["game_id"]]["settled"]
            and _parse_dt(eco["sports_events"][b["game_id"]]["commence_time"]) <= now
        }
        live = await _fetch_live_scores(open_sports) if open_sports else {}

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
                live_data = live.get((ev.get("home", ""), ev.get("away", "")))
                if live_data:
                    hs, as_ = live_data["home_score"], live_data["away_score"]
                    period = live_data["detail"]
                    clock = live_data["clock"]
                    if hs is not None:
                        score_str = f"{ev.get('away','?')} **{as_}** – **{hs}** {ev.get('home','?')}"
                        time_str = f"{period} {clock}".strip()
                        result = f"🔴 LIVE {score_str} _{time_str}_ | {_calc_payout(bet['amount'], bet['odds']):,} to win"
                    else:
                        result = f"🔴 LIVE {period} | {_calc_payout(bet['amount'], bet['odds']):,} to win"
                else:
                    result = f"open — {_calc_payout(bet['amount'], bet['odds']):,} to win"

            lines.append(
                f"**#{bet['id']}** {matchup} | {mk_label} {pick_display} {_fmt_odds(bet['odds'])} | "
                f"{bet['amount']:,} wagered | {result}"
            )

        lines.append("\n`!livescores` for all live games · `!cancelsportsbet <id>` to cancel before start")
        await ctx.send("\n".join(lines)[:1990])

    # ── !parlay ───────────────────────────────────────────────────────────────

    @commands.command(name="parlay")
    async def parlay_cmd(self, ctx, amount: int = None, *legs_raw: str):
        """Combine 2–6 legs into one bet. Usage: !parlay <coins> <game:market:pick> ..."""
        if not amount or amount <= 0 or len(legs_raw) < 2:
            await ctx.send(
                "Usage: `!parlay <coins> <game:market:pick> [game:market:pick] ...` (2–6 legs)\n"
                "Example: `!parlay 500 3:ml:home 5:total:over 7:ml:away`\n"
                "See `!odds` for game numbers."
            )
            return
        if len(legs_raw) > 6:
            await ctx.send("Maximum 6 legs per parlay.")
            return

        eco = load_economy()
        _init_sports(eco)
        uid = str(ctx.author.id)
        now = datetime.datetime.now(datetime.timezone.utc)

        parsed_legs = []
        for raw in legs_raw:
            parts = raw.split(":")
            if len(parts) != 3:
                await ctx.send(f"Bad leg format `{raw}` — use `game:market:pick` e.g. `3:ml:home`.")
                return
            game_id, market_raw, pick_raw = parts
            market_key = MARKET_ALIASES.get(market_raw.lower())
            if not market_key:
                await ctx.send(f"Unknown market `{market_raw}` in leg `{raw}`. Use `ml`, `spread`, or `total`.")
                return
            pick = pick_raw.lower()
            event = eco["sports_events"].get(game_id)
            if not event or event["settled"]:
                await ctx.send(f"Game **#{game_id}** not found or already settled.")
                return
            if _parse_dt(event["commence_time"]) <= now:
                await ctx.send(f"Game **#{game_id}** has already started — can't include it in a parlay.")
                return
            if event.get("sport") in MONEYLINE_ONLY and market_key != "h2h":
                await ctx.send(f"Game **#{game_id}** (UFC) only supports `ml` bets.")
                return
            if market_key in ("h2h", "spreads") and pick not in ("home", "away"):
                await ctx.send(f"Leg `{raw}`: pick must be `home` or `away` for `{market_raw}`.")
                return
            if market_key == "totals" and pick not in ("over", "under"):
                await ctx.send(f"Leg `{raw}`: pick must be `over` or `under` for `total`.")
                return
            if market_key not in event["odds"]:
                await ctx.send(f"No **{MARKET_LABEL[market_key]}** line for game **#{game_id}**.")
                return

            if market_key == "h2h":
                odds = event["odds"]["h2h"][pick]
                pick_label = event["home"] if pick == "home" else event["away"]
            elif market_key == "spreads":
                sp = event["odds"]["spreads"][pick]
                odds = sp["price"]
                pick_label = f"{event['home'] if pick == 'home' else event['away']} {_fmt_line(sp['line'])}"
            else:
                t = event["odds"]["totals"]
                odds = t["over_price"] if pick == "over" else t["under_price"]
                pick_label = f"{pick.capitalize()} {t['line']}"

            parsed_legs.append({
                "game_id": game_id,
                "market": market_key,
                "selection": pick,
                "odds": odds,
                "pick_label": pick_label,
                "matchup": f"{event['away']} @ {event['home']}",
                "result": None,
            })

        # Deduplicate: can't have two legs on the same game
        game_ids_used = [l["game_id"] for l in parsed_legs]
        if len(game_ids_used) != len(set(game_ids_used)):
            await ctx.send("Each game can only appear once in a parlay.")
            return

        bal = eco["balances"].get(uid, 0)
        if bal < amount:
            await ctx.send(f"Not enough coins. You have **{bal:,}**, parlay costs **{amount:,}**.")
            return

        eco["balances"][uid] = round(bal - amount, 2)
        parlay_id = eco["next_sports_parlay_id"]
        eco["next_sports_parlay_id"] += 1
        decimal, combined_american = _parlay_combined_odds(parsed_legs)
        potential = round(amount * decimal)

        eco["sports_parlays"].setdefault(uid, []).append({
            "id": parlay_id,
            "legs": parsed_legs,
            "amount": amount,
            "placed_at": now.isoformat(),
            "settled": False,
            "won": None,
            "payout": None,
        })
        save_economy(eco)

        leg_lines = "\n".join(
            f"  Leg {i+1}: **{l['pick_label']}** {_fmt_odds(l['odds'])} — {l['matchup']}"
            for i, l in enumerate(parsed_legs)
        )
        await ctx.send(
            f"🎰 **Parlay #{parlay_id}** placed — **{amount:,} coins**\n"
            f"{leg_lines}\n"
            f"Combined odds: **{_fmt_odds(combined_american)}** | "
            f"Potential payout: **{potential:,} coins**"
        )

    # ── !myparlays ────────────────────────────────────────────────────────────

    @commands.command(name="myparlays")
    async def my_parlays_cmd(self, ctx, status: str = "open"):
        eco = load_economy()
        _init_sports(eco)
        uid = str(ctx.author.id)
        all_parlays = eco["sports_parlays"].get(uid, [])

        show = all_parlays if status.lower() == "all" else [p for p in all_parlays if not p["settled"]]
        if not show:
            await ctx.send("No parlays found. Use `!parlay` to place one, or `!myparlays all` for history.")
            return

        lines = [f"🎰 **{ctx.author.display_name}'s Parlays** ({status})\n"]
        for parlay in show[-10:]:
            decimal, combined_american = _parlay_combined_odds(parlay["legs"])
            potential = round(parlay["amount"] * decimal)
            if parlay["settled"]:
                if parlay["won"] is None:
                    summary = f"PUSH (+{parlay['payout']:,})"
                elif parlay["won"]:
                    summary = f"WON +{parlay['payout']:,} 🎉"
                else:
                    summary = f"LOST -{parlay['amount']:,} ❌"
            else:
                summary = f"open — {potential:,} to win"

            lines.append(
                f"**#{parlay['id']}** {len(parlay['legs'])}-leg · "
                f"{_fmt_odds(combined_american)} · {parlay['amount']:,} wagered · {summary}"
            )
            for i, leg in enumerate(parlay["legs"]):
                icon = {"win": "✅", "loss": "❌", "push": "➡️"}.get(leg.get("result"), "⏳")
                lines.append(
                    f"  {icon} Leg {i+1}: **{leg['pick_label']}** {_fmt_odds(leg['odds'])} — {leg['matchup']}"
                )
            lines.append("")

        await ctx.send("\n".join(lines)[:1990])

    # ── !betleaderboard ───────────────────────────────────────────────────────

    @commands.command(name="betleaderboard", aliases=["betlb"])
    async def bet_leaderboard_cmd(self, ctx):
        eco = load_economy()
        _init_sports(eco)
        ranked = _sports_leaderboard_stats(eco)

        if not ranked:
            await ctx.send("No settled bets yet — leaderboard is empty.")
            return

        lines = ["🏆 **Sports Betting Leaderboard**\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, s) in enumerate(ranked[:10]):
            name = ctx.guild.get_member(int(uid))
            display = name.display_name if name else f"<@{uid}>"
            medal = medals[i] if i < 3 else f"**{i+1}.**"
            net_str = f"+{s['net']:,}" if s['net'] >= 0 else f"{s['net']:,}"
            lines.append(
                f"{medal} **{display}** — {net_str} coins net | "
                f"{s['wins']}W–{s['total']-s['wins']}L ({s['win_pct']}%) | "
                f"{s['wagered']:,} wagered"
            )

        await ctx.send("\n".join(lines))

    # ── !livescores ───────────────────────────────────────────────────────────

    @commands.command(name="livescores")
    async def live_scores_cmd(self, ctx):
        """Show live scores for all games with active bets."""
        eco = load_economy()
        _init_sports(eco)
        now = datetime.datetime.now(datetime.timezone.utc)

        # All sports that have started but unsettled events
        active_sports = {
            ev["sport"]
            for ev in eco["sports_events"].values()
            if not ev["settled"] and _parse_dt(ev["commence_time"]) <= now
        }
        if not active_sports:
            await ctx.send("No games have started yet. Check `!odds` for upcoming matchups.")
            return

        live = await _fetch_live_scores(active_sports)
        if not live:
            await ctx.send("No games are currently in progress. Results will post automatically when games finish.")
            return

        # Count open bets and coins wagered per event
        bet_counts, bet_coins = {}, {}
        for bets in eco["sports_bets"].values():
            for b in bets:
                if not b["settled"]:
                    gid = b["game_id"]
                    bet_counts[gid] = bet_counts.get(gid, 0) + 1
                    bet_coins[gid] = bet_coins.get(gid, 0) + b["amount"]

        # Map stored events by (home, away) for bet count lookup
        events_by_teams = {
            (ev["home"], ev["away"]): (sid, ev)
            for sid, ev in eco["sports_events"].items()
        }

        lines = ["📺 **Live Scores**\n"]
        for (home_name, away_name), data in live.items():
            emoji = SPORT_EMOJI.get(data["sport"], "🏆")
            period = data["detail"]
            clock = data["clock"]
            time_str = f"{period} {clock}".strip()

            if data["home_score"] is not None:
                hs, as_ = data["home_score"], data["away_score"]
                score_str = f"**{as_} – {hs}**"
                line = f"{emoji} {away_name} {score_str} {home_name} _{time_str}_"
            else:
                line = f"{emoji} {away_name} vs {home_name} — _{time_str}_"

            matched = events_by_teams.get((home_name, away_name))
            if matched:
                sid, _ = matched
                count = bet_counts.get(sid, 0)
                coins = bet_coins.get(sid, 0)
                if count:
                    line += f"  |  #{sid} · {count} bet{'s' if count != 1 else ''} · {coins:,} coins at risk"

            lines.append(line)

        lines.append("\n`!mybets` to see your bets with live scores")
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
