import asyncio
import random
import datetime
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks
import shared
from shared import (
    load_economy, save_economy, get_guild_target, _t,
    _sparkline, _market_sentiment, _get_target_stock_info, _get_delisted_stocks,
    init_market, get_portfolio_value, init_derivatives, _get_random_member_name,
    execute_market_buy, execute_market_sell, execute_open_short, execute_close_short,
    calc_option_premium,
)

class StocksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.dividend_payout.start()
        self.earnings_report.start()
        self.limit_order_checker.start()
        self.meme_stock_drift.start()
        self.derivatives_settlement.start()
        self.margin_call_checker.start()

    async def cog_unload(self):
        self.dividend_payout.cancel()
        self.earnings_report.cancel()
        self.limit_order_checker.cancel()
        self.meme_stock_drift.cancel()
        self.derivatives_settlement.cancel()
        self.margin_call_checker.cancel()

    @tasks.loop(time=datetime.time(hour=18, minute=0, tzinfo=ZoneInfo("America/New_York")))
    async def dividend_payout(self):
        """Every Sunday at 6 PM ET: pay dividends to holders of dividend-bearing stocks."""
        if datetime.datetime.now(ZoneInfo("America/New_York")).weekday() != 6:
            return

        eco = load_economy()
        shared.init_market(eco)
        payouts = {}  # uid -> total coins earned

        for ticker, info in shared.MARKET_STOCKS.items():
            rate = info.get("dividend_rate")
            if not rate:
                continue
            price = eco["market"].get(ticker, {}).get("price", info["base_price"])
            per_share = round(price * rate, 2)
            if per_share <= 0:
                continue
            for uid, port in eco.get("portfolios", {}).items():
                shares = port.get(ticker, {}).get("shares", 0)
                if shares <= 0:
                    continue
                earned = round(per_share * shares)
                eco["balances"][uid] = eco.get("balances", {}).get(uid, 0) + earned
                payouts.setdefault(uid, {})[ticker] = earned

        save_economy(eco)

        if not payouts:
            return

        lines = ["💰 **WEEKLY DIVIDENDS PAID**\n"]
        for ticker, info in shared.MARKET_STOCKS.items():
            if not info.get("dividend_rate"):
                continue
            price = eco["market"].get(ticker, {}).get("price", info["base_price"])
            per_share = round(price * info["dividend_rate"], 2)
            total_paid = sum(v[ticker] for v in payouts.values() if ticker in v)
            if total_paid:
                lines.append(f"**${ticker}** — {per_share:.2f} coins/share  ({total_paid:,} coins paid out)")

        for _, ch in shared._get_guild_channels():
            try:
                await ch.send("\n".join(lines))
            except Exception:
                pass



    @tasks.loop(time=datetime.time(hour=19, minute=0, tzinfo=ZoneInfo("America/New_York")))
    async def earnings_report(self):
        """Every Sunday at 7 PM ET: shift each stock's dynamic base toward its weekly average."""
        if datetime.datetime.now(ZoneInfo("America/New_York")).weekday() != 6:
            return

        eco = load_economy()
        shared.init_market(eco)
        all_stocks = {**shared.MARKET_STOCKS, **shared._get_target_stock_info(eco)}
        lines = ["📰 **WEEKLY EARNINGS REPORT** 📰\n"]

        for ticker, info in all_stocks.items():
            mdata = eco["market"].get(ticker)
            if not mdata:
                continue

            old_base = mdata.get("dynamic_base", info["base_price"])
            history = mdata.get("price_history", [mdata["price"]])
            recent_avg = sum(history) / len(history)

            # Shift base 30% toward the weekly average, capped at ±10% per week
            raw_new_base = old_base * 0.70 + recent_avg * 0.30
            max_shift = old_base * 0.10
            new_base = max(old_base - max_shift, min(old_base + max_shift, raw_new_base))
            new_base = round(new_base, 2)
            mdata["dynamic_base"] = new_base

            change_pct = round((new_base - old_base) / old_base * 100, 1)
            if abs(change_pct) < 0.1:
                rating = "➡️ HOLD"
            elif change_pct >= 5:
                rating = "🚀 STRONG BUY"
            elif change_pct >= 2:
                rating = "📈 BUY"
            elif change_pct <= -5:
                rating = "💀 STRONG SELL"
            elif change_pct <= -2:
                rating = "📉 SELL"
            else:
                rating = "🟡 NEUTRAL"

            lines.append(
                f"**${ticker}** — Base: **${old_base:.2f} → ${new_base:.2f}** ({change_pct:+.1f}%)  {rating}"
            )

        save_economy(eco)
        msg = "\n".join(lines)
        for _, ch in shared._get_guild_channels():
            try:
                await ch.send(msg)
            except Exception:
                pass



    @tasks.loop(minutes=1)
    async def limit_order_checker(self):
        eco = load_economy()
        shared.init_market(eco)
        orders = list(eco.get("limit_orders", []))
        if not orders:
            return
        remaining = []
        notifications = []
        for order in orders:
            ticker = order["ticker"]
            if ticker not in eco.get("market", {}):
                remaining.append(order)
                continue
            price = eco["market"][ticker]["price"]
            should_fill = (
                (order["order_type"] == "buy"   and price <= order["limit_price"]) or
                (order["order_type"] == "sell"  and price >= order["limit_price"]) or
                (order["order_type"] == "short" and price >= order["limit_price"]) or
                (order["order_type"] == "cover" and price <= order["limit_price"])
            )
            if not should_fill:
                remaining.append(order)
                continue
            uid = order["user_id"]
            if order["order_type"] == "buy":
                ok, msg = shared.execute_market_buy(eco, uid, ticker, order["shares"])
            elif order["order_type"] == "sell":
                ok, msg = shared.execute_market_sell(eco, uid, ticker, order["shares"])
            elif order["order_type"] == "short":
                ok, msg = shared.execute_open_short(eco, uid, ticker, order["shares"])
            else:
                ok, msg = shared.execute_close_short(eco, uid, ticker, order["shares"])
            status = "filled ✅" if ok else "failed ❌"
            notifications.append((uid, order["id"], status, msg))
        eco["limit_orders"] = remaining
        save_economy(eco)
        guild_channels = shared._get_guild_channels()
        for uid, order_id, status, msg in notifications:
            for gid, channel in guild_channels:
                member = channel.guild.get_member(int(uid))
                mention = member.mention if member else f"<@{uid}>"
                await channel.send(f"📋 {mention} Limit order **#{order_id}** {status}: {msg}")
                break



    @tasks.loop(minutes=10)
    async def meme_stock_drift(self):
        eco = load_economy()
        shared.init_market(eco)
        now = datetime.datetime.now(datetime.timezone.utc)
        broadcast_channels = shared._get_guild_channels()
        mstate = eco["market_state"]

        # ── Delist cleanup: auto-liquidate and remove expired target stocks ───────
        delist_grace = datetime.timedelta(hours=48)
        for gid_str, history in eco.get("target_history", {}).items():
            still_active = []
            for entry in history:
                delisted_at_str = entry.get("delisted_at")
                if not delisted_at_str:
                    still_active.append(entry)
                    continue
                deadline = datetime.datetime.fromisoformat(delisted_at_str) + delist_grace
                if now <= deadline:
                    still_active.append(entry)
                    continue
                # Grace period over — liquidate all holders at last known price
                ticker = entry.get("ticker", "").upper()
                last_price = eco.get("market", {}).get(ticker, {}).get("price")
                if ticker and last_price:
                    for uid, port in eco.get("portfolios", {}).items():
                        shares_held = port.get(ticker, {}).get("shares", 0)
                        if shares_held > 0:
                            payout = round(shares_held * last_price)
                            eco["balances"][uid] = eco.get("balances", {}).get(uid, 0) + payout
                            port.pop(ticker, None)
                    eco["market"].pop(ticker, None)
                # Drop from target_history (don't keep in still_active)
            eco["target_history"][gid_str] = still_active

        # ── Resolve pending rumors ────────────────────────────────────────────────
        still_pending = []
        for rumor in eco.get("pending_rumors", []):
            if now < datetime.datetime.fromisoformat(rumor["confirm_at"]):
                still_pending.append(rumor)
                continue
            confirmed = random.random() < 0.70
            if confirmed:
                for t, pct in rumor["remaining_impact"].items():
                    if t in eco["market"]:
                        old = eco["market"][t]["price"]
                        shared._apply_price_event(eco["market"][t], old * (1 + pct / 100))
                new_p = eco["market"][rumor["ticker"]]["price"]
                analyst = random.choice(shared._ANALYST_QUOTES)
                for _, ch in broadcast_channels:
                    await ch.send(
                        f"✅ **CONFIRMED — ${rumor['ticker']}:** {rumor['headline']}\n"
                        f"**${rumor['old_price']:.2f} → ${new_p:.2f}** | {analyst}"
                    )
            else:
                for t, pct in rumor["pre_impact"].items():
                    if t in eco["market"]:
                        old = eco["market"][t]["price"]
                        shared._apply_price_event(eco["market"][t], old * (1 - pct / 100))
                for _, ch in broadcast_channels:
                    await ch.send(
                        f"❌ **DENIED — ${rumor['ticker']}:** *\"{rumor['headline']}\"* was **FAKE NEWS**. "
                        f"Price reverting. 📉"
                    )
        eco["pending_rumors"] = still_pending

        # ── Daily volume reset ────────────────────────────────────────────────────
        today = now.strftime("%Y-%m-%d")
        if mstate.get("volume_date") != today:
            for ticker in shared.MARKET_STOCKS:
                eco["market"][ticker]["volume_today"] = 0
            mstate["volume_date"] = today

        now_est = datetime.datetime.now(ZoneInfo("America/New_York"))

        # ── Market sentiment: slow random walk, mean-reverts to 0 (9am–midnight EST)
        sentiment = mstate.get("sentiment", 0.0)
        if now_est.hour >= 9:
            sentiment = max(-1.0, min(1.0, sentiment * 0.92 + random.gauss(0, 0.1)))
            mstate["sentiment"] = round(sentiment, 4)

        # ── Volume-based price discovery ──────────────────────────────────────────
        now_iso = now.isoformat()
        all_drift_stocks = {**shared.MARKET_STOCKS, **shared._get_target_stock_info(eco)}
        for ticker, info in all_drift_stocks.items():
            mdata = eco["market"][ticker]
            price = mdata["price"]
            base = mdata.get("dynamic_base", info["base_price"])
            vol = info["volatility"]
            daily_vol = info["daily_volume"]

            # TBELL 4th meal hours: triple volume and volatility 10pm–4am EST
            tick_multiplier = 3.0 if ticker == "TBELL" and (now_est.hour >= 22 or now_est.hour < 4) else 1.0

            # Simulated tick volume — slice of daily volume with noise
            tick_vol = max(10, round(daily_vol / 144 * random.uniform(0.5, 2.0) * tick_multiplier))

            # Buy pressure probability — baked-in sentiment, mean reversion, momentum
            history = mdata.get("price_history", [price])
            mr_tilt      = (base - price) / base * info["mean_reversion"] * 10
            momentum_tilt = ((history[-1] / history[0] - 1) if len(history) >= 2 else 0.0) * 0.15
            p_buy = max(0.15, min(0.85, 0.5 + sentiment * 0.15 + mr_tilt + momentum_tilt))

            buy_vol  = round(tick_vol * p_buy)
            sell_vol = tick_vol - buy_vol

            # Order flow imbalance drives direction; volatility scales magnitude
            ofi        = (buy_vol - sell_vol) / tick_vol
            volume_pct = ofi * vol * 0.7 * tick_multiplier
            noise_pct  = random.gauss(0, vol * 0.25)
            total_pct  = max(-15.0, min(15.0, volume_pct + noise_pct))

            new_price = max(round(price * (1 + total_pct / 100), 2), 0.01)
            mdata["price_history"]  = (history + [new_price])[-49:]
            mdata["prev_price"]     = price
            mdata["price"]          = new_price
            mdata["last_updated"]   = now_iso
            mdata["volume_today"]   = mdata.get("volume_today", 0) + tick_vol
            mdata["all_time_high"]  = max(mdata.get("all_time_high", new_price), new_price)
            mdata["all_time_low"]   = min(mdata.get("all_time_low",  new_price), new_price)

        # ── News events (9am–midnight EST only) ──────────────────────────────────
        immediate_news = []
        for ticker in (shared.MARKET_STOCKS if now_est.hour >= 9 else []):
            if random.random() > 0.025:
                continue
            event = random.choice(shared._STOCK_NEWS[ticker])
            headline = event["headline"]
            if "{member}" in headline:
                headline = headline.replace("{member}", _get_random_member_name())

            impact_pct = random.uniform(*event["impact"])
            impacts = {ticker: impact_pct}
            for linked_ticker, linked_range in event.get("linked", []):
                impacts[linked_ticker] = random.uniform(*linked_range)

            is_rumor = random.random() < 0.30
            if is_rumor:
                pre_impact, remaining_impact = {}, {}
                for t, pct in impacts.items():
                    pre_impact[t] = round(pct * 0.25, 4)
                    remaining_impact[t] = round(pct * 0.75, 4)
                    if t in eco["market"]:
                        old = eco["market"][t]["price"]
                        shared._apply_price_event(eco["market"][t], old * (1 + pre_impact[t] / 100))
                eco["pending_rumors"].append({
                    "ticker": ticker,
                    "headline": headline,
                    "old_price": eco["market"][ticker]["price"],
                    "pre_impact": pre_impact,
                    "remaining_impact": remaining_impact,
                    "confirm_at": (now + datetime.timedelta(minutes=20)).isoformat(),
                })
                pre_pct = pre_impact[ticker]
                cur_p = eco["market"][ticker]["price"]
                for _, ch in broadcast_channels:
                    await ch.send(
                        f"🔍 **UNCONFIRMED — ${ticker}:** *\"{headline}\"*\n"
                        f"Markets reacting cautiously: **${cur_p:.2f}** ({pre_pct:+.1f}% pre-move) "
                        f"— confirmation expected in ~20 min..."
                    )
            else:
                old_price = eco["market"][ticker]["price"]
                for t, pct in impacts.items():
                    if t in eco["market"]:
                        old = eco["market"][t]["price"]
                        shared._apply_price_event(eco["market"][t], old * (1 + pct / 100))
                immediate_news.append((ticker, headline, impact_pct, old_price, impacts))

        save_economy(eco)

        for ticker, headline, impact_pct, old_p, impacts in immediate_news:
            arrow = "📈" if impact_pct > 0 else "📉"
            new_p = eco["market"][ticker]["price"]
            analyst = random.choice(shared._ANALYST_QUOTES)
            linked_str = "".join(
                f" | **${t}** → **${eco['market'][t]['price']:.2f}** ({pct:+.1f}%)"
                for t, pct in impacts.items() if t != ticker
            )
            msg_text = (
                f"{arrow} **BREAKING — ${ticker}:** {headline}\n"
                f"**${old_p:.2f} → ${new_p:.2f}** ({impact_pct:+.1f}%){linked_str}\n"
                f"*{analyst}*"
            )
            for _, ch in broadcast_channels:
                await ch.send(msg_text)



    @tasks.loop(minutes=5)
    async def derivatives_settlement(self):
        eco = load_economy()
        shared.init_market(eco)
        shared.init_derivatives(eco)
        gc = shared._get_guild_channels()
        channel = gc[0][1] if gc else None
        await shared.settle_expired_futures(eco, channel)
        await shared.expire_options(eco, channel)
        save_economy(eco)



    @tasks.loop(minutes=5)
    async def margin_call_checker(self):
        eco = load_economy()
        shared.init_market(eco)
        gc = shared._get_guild_channels()
        channel = gc[0][1] if gc else None
        now = datetime.datetime.now(datetime.timezone.utc)
        squeeze_msgs = []

        # Check for short squeezes before running margin calls
        for ticker, info in shared.MARKET_STOCKS.items():
            if ticker not in eco["market"]:
                continue
            outstanding = info["shares_outstanding"]
            shorted = sum(
                pos[ticker]["shares"]
                for pos in eco.get("short_positions", {}).values()
                if ticker in pos
            )
            if shorted / outstanding <= 0.20:
                continue
            last_str = eco["market"][ticker].get("last_squeeze")
            if last_str and now - datetime.datetime.fromisoformat(last_str) < datetime.timedelta(hours=1):
                continue
            spike_pct = random.uniform(15, 30)
            old = eco["market"][ticker]["price"]
            shared._apply_price_event(eco["market"][ticker], old * (1 + spike_pct / 100))
            eco["market"][ticker]["last_squeeze"] = now.isoformat()
            squeeze_msgs.append((ticker, old, new, round(shorted / outstanding * 100, 1), spike_pct))

        # Run margin calls (catches positions squeezed above threshold)
        liquidations = []
        for uid, positions in list(eco.get("short_positions", {}).items()):
            for ticker in list(positions.keys()):
                pos = positions[ticker]
                price = eco["market"][ticker]["price"]
                loss = (price - pos["avg_price"]) * pos["shares"]
                if loss >= pos["collateral"] * 0.80:
                    pnl = round((pos["avg_price"] - price) * pos["shares"], 2)
                    returned = max(round(pos["collateral"] + pnl, 2), 0)
                    shared.apply_price_impact(eco, ticker, pos["shares"], +1)
                    eco["balances"][uid] = eco["balances"].get(uid, 0) + returned
                    del eco["short_positions"][uid][ticker]
                    if not eco["short_positions"][uid]:
                        del eco["short_positions"][uid]
                    liquidations.append((uid, ticker, pos["shares"], price, pnl, returned))

        if squeeze_msgs or liquidations:
            save_economy(eco)
        if channel:
            for ticker, old, new, si_pct, spike_pct in squeeze_msgs:
                await channel.send(
                    f"🔥 **SHORT SQUEEZE — ${ticker}!** Short interest hit **{si_pct:.1f}%** of float. "
                    f"Price spiked **+{spike_pct:.1f}%**: **${old:.2f}** → **${new:.2f}**. "
                    f"Short sellers getting squeezed! 💀"
                )
            for uid, ticker, shares, price, pnl, returned in liquidations:
                member = channel.guild.get_member(int(uid))
                mention = member.mention if member else f"<@{uid}>"
                pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
                await channel.send(
                    f"🚨 **MARGIN CALL** — {mention}'s short on **${ticker}** ({shares} shares) was "
                    f"force-liquidated at **${price:.2f}**. "
                    f"P&L: **{pnl_str} coins** | Returned: **{returned:.0f} coins**"
                )





    @commands.command(name="stocktrend")
    async def stock_trend(self, ctx, ticker: str = None):
        """Show sparkline chart and trend indicators for a stock. Usage: !stocktrend <TICKER>"""
        eco = load_economy()
        init_market(eco)
        gid = ctx.guild.id if ctx.guild else None

        all_stocks = {**shared.MARKET_STOCKS, **_get_target_stock_info(eco)}

        if not ticker:
            await ctx.send("Usage: `!stocktrend <TICKER>` — e.g. `!stocktrend DONOVAN`")
            return

        ticker = ticker.lstrip("$").upper()
        if ticker not in eco["market"]:
            await ctx.send(f"Unknown ticker **${ticker}**. Check `!stockmarket` for valid tickers.")
            return

        mdata = eco["market"][ticker]
        info = all_stocks.get(ticker, shared._TARGET_STOCK_DEFAULTS)
        history = mdata.get("price_history", [mdata["price"]])
        current = mdata["price"]
        base = mdata.get("dynamic_base", info.get("base_price", shared._TARGET_STOCK_DEFAULTS["base_price"]))
        static_base = info.get("base_price", shared._TARGET_STOCK_DEFAULTS["base_price"])

        # Sparkline: show full available history (up to 48 ticks = 8 hours)
        spark_prices = history[-48:]
        spark = _sparkline(spark_prices)

        # Multi-window % changes
        def pct_change(window):
            if len(history) < window + 1:
                return None
            old = history[-(window + 1)]
            return round((current - old) / old * 100, 2) if old else None

        c30m  = pct_change(3)    # 30 min  (3 ticks)
        c2h   = pct_change(12)   # 2 hours (12 ticks)
        c8h   = pct_change(48)   # 8 hours (48 ticks)

        def fmt_pct(val):
            if val is None:
                return "n/a"
            arrow = "📈" if val > 0 else ("📉" if val < 0 else "➡️")
            return f"{arrow} {val:+.2f}%"

        # Momentum: fraction of recent ticks that were up-moves
        diffs = [history[i] - history[i - 1] for i in range(1, len(history))]
        recent_diffs = diffs[-12:] if len(diffs) >= 12 else diffs
        if recent_diffs:
            up_frac = sum(1 for d in recent_diffs if d > 0) / len(recent_diffs)
            if up_frac >= 0.65:
                momentum = "🟢 Bullish"
            elif up_frac <= 0.35:
                momentum = "🔴 Bearish"
            else:
                momentum = "🟡 Neutral"
        else:
            momentum = "🟡 Neutral"

        # High / low over available history
        hi = max(history)
        lo = min(history)

        # Distance from dynamic base (and drift from original)
        from_base = round((current - base) / base * 100, 1)
        base_drift = round((base - static_base) / static_base * 100, 1)
        drift_str = f"  *(drifted {base_drift:+.1f}% from original ${static_base:.2f})*" if abs(base_drift) >= 0.1 else ""
        base_str = f"{from_base:+.1f}% from base (${base:.2f}){drift_str}"

        # Short interest
        shorted = sum(
            pos[ticker]["shares"]
            for pos in eco.get("short_positions", {}).values()
            if ticker in pos
        )
        outstanding = info.get("shares_outstanding", shared._TARGET_STOCK_DEFAULTS["shares_outstanding"])
        si_pct = round(shorted / outstanding * 100, 1) if outstanding else 0
        si_str = f"  🔥 Short Interest: {si_pct}%" if si_pct > 0 else ""

        ticks_shown = len(spark_prices)
        lines = [
            f"📈 **${ticker} Trend** — ${current:.2f}  |  {base_str}",
            f"```{spark}```",
            f"*last {ticks_shown} ticks (~{ticks_shown * 10} min)*",
            f"",
            f"**Performance**",
            f"  30 min:  {fmt_pct(c30m)}",
            f"  2 hr:    {fmt_pct(c2h)}",
            f"  8 hr:    {fmt_pct(c8h)}",
            f"",
            f"**Range (session history)**",
            f"  High: ${hi:.2f}   Low: ${lo:.2f}",
            f"",
            f"**All-Time High:** ${mdata.get('all_time_high', hi):.2f}  |  **All-Time Low:** ${mdata.get('all_time_low', lo):.2f}",
            f"",
            f"**Momentum:** {momentum}{si_str}",
        ]
        # Dividend yield note
        all_stocks = {**shared.MARKET_STOCKS, **_get_target_stock_info(eco)}
        div_rate = all_stocks.get(ticker, {}).get("dividend_rate")
        if div_rate:
            weekly_per_share = round(current * div_rate, 2)
            lines.append(f"💰 **Dividend:** {weekly_per_share:.2f} coins/share/week ({div_rate*100:.1f}% weekly yield)")
        await ctx.send("\n".join(lines))



    @commands.command(name="stockmarket")
    async def stock_market(self, ctx):
        eco = load_economy()
        init_market(eco)
        save_economy(eco)
        gid = ctx.guild.id if ctx.guild else None
        tgt_ticker = get_guild_target(gid)["ticker"]

        lines = [f"📊 **{tgt_ticker} STOCK EXCHANGE**\n"]

        target_stocks = _get_target_stock_info(eco)
        delisted = _get_delisted_stocks(eco)
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        all_display_stocks = {**shared.MARKET_STOCKS, **target_stocks}

        for ticker, info in all_display_stocks.items():
            if ticker not in eco["market"]:
                continue
            mdata = eco["market"][ticker]
            price = mdata["price"]
            prev = mdata.get("prev_price", info.get("base_price", price))
            change = round(price - prev, 2)
            pct = round((change / prev * 100) if prev else 0, 1)
            trend = "📉" if change < 0 else "📈"
            vol = mdata.get("volume_today", 0)
            history = mdata.get("price_history", [price])
            spark = _sparkline(history[-12:])  # last 2 hours inline
            shorted = sum(
                pos[ticker]["shares"]
                for pos in eco.get("short_positions", {}).values()
                if ticker in pos
            )
            outstanding = info.get("shares_outstanding", shared._TARGET_STOCK_DEFAULTS["shares_outstanding"])
            si_pct = round(shorted / outstanding * 100, 1) if outstanding else 0
            si_str = f"  🔥 SI: {si_pct}%" if si_pct > 0 else ""

            # 2-hour % change (12 ticks back)
            if len(history) >= 13:
                old_2h = history[-13]
                pct_2h = round((price - old_2h) / old_2h * 100, 1) if old_2h else None
            else:
                pct_2h = None
            pct_2h_str = f"  2hr: {pct_2h:+.1f}%" if pct_2h is not None else ""

            if ticker in delisted:
                hrs_left = max(0, round((delisted[ticker] - now_dt).total_seconds() / 3600, 1))
                label = "🪦 "
                delist_str = f"  *(delisted — {hrs_left}h to sell)*"
            else:
                label = ""
                delist_str = ""

            lines.append(
                f"{label}**${ticker}** — ${price:.2f}  {trend} {change:+.2f} ({pct:+.1f}%){pct_2h_str}  "
                f"Vol: {vol}{si_str}{delist_str}"
            )

        # Top portfolio holders
        all_uids = set(eco.get("portfolios", {}).keys()) | set(eco.get("short_positions", {}).keys())
        if all_uids:
            ranked = sorted(all_uids, key=lambda u: get_portfolio_value(eco, u), reverse=True)[:5]
            lines.append("\n**Top Portfolio Values:**")
            for uid in ranked:
                member = ctx.guild.get_member(int(uid))
                name = member.display_name if member else "Unknown"
                val = get_portfolio_value(eco, uid)
                lines.append(f"  **{name}** — {val:.0f} coins")

        # Sentiment indicator
        s_score, s_label, s_emoji = _market_sentiment(eco)
        bar_filled = round(s_score / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append(f"\n**Market Sentiment:** {s_emoji} **{s_label}** `{bar}` {s_score}/100")

        # Dividend-paying stocks note
        div_stocks = [t for t, i in shared.MARKET_STOCKS.items() if i.get("dividend_rate")]
        if div_stocks:
            lines.append(f"💰 Dividend stocks (paid every Sunday): {', '.join(f'${t}' for t in div_stocks)}")

        lines.append("\n`!buystock` `!sellstock` `!short` `!cover` `!limitorder` `!portfolio` `!orders` `!stocktrend <TICKER>`")
        await ctx.send("\n".join(lines))



    @commands.command(name="buystock")
    async def buy_stock(self, ctx, ticker: str = None, shares: int = None):
        if not ticker or not shares or shares <= 0:
            await ctx.send("Usage: `!buystock <TICKER> <shares>` — e.g. `!buystock DONOVAN 10`")
            return
        ticker = ticker.lstrip("$").upper()
        if ticker not in shared.MARKET_STOCKS:
            await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in shared.MARKET_STOCKS)}")
            return
        eco = load_economy()
        init_market(eco)
        ok, msg = execute_market_buy(eco, ctx.author.id, ticker, shares)
        save_economy(eco)
        await ctx.send(("✅ " if ok else "❌ ") + msg)



    @commands.command(name="sellstock")
    async def sell_stock(self, ctx, ticker: str = None, shares: int = None):
        if not ticker or not shares or shares <= 0:
            await ctx.send("Usage: `!sellstock <TICKER> <shares>` — e.g. `!sellstock DONOVAN 10`")
            return
        ticker = ticker.lstrip("$").upper()
        if ticker not in shared.MARKET_STOCKS:
            await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in shared.MARKET_STOCKS)}")
            return
        eco = load_economy()
        init_market(eco)
        ok, msg = execute_market_sell(eco, ctx.author.id, ticker, shares)
        save_economy(eco)
        await ctx.send(("✅ " if ok else "❌ ") + msg)



    @commands.command(name="short")
    async def short_stock(self, ctx, ticker: str = None, shares: int = None):
        if not ticker or not shares or shares <= 0:
            gid = ctx.guild.id if ctx.guild else None
            tgt_ticker = get_guild_target(gid)["ticker"]
            await ctx.send(f"Usage: `!short <TICKER> <shares>` — Only `${tgt_ticker}` is shortable.")
            return
        ticker = ticker.lstrip("$").upper()
        if ticker not in shared.MARKET_STOCKS:
            await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in shared.MARKET_STOCKS)}")
            return
        eco = load_economy()
        init_market(eco)
        ok, msg = execute_open_short(eco, ctx.author.id, ticker, shares)
        save_economy(eco)
        await ctx.send(("✅ " if ok else "❌ ") + msg)



    @commands.command(name="cover")
    async def cover_short(self, ctx, ticker: str = None, shares: int = None):
        if not ticker or not shares or shares <= 0:
            await ctx.send("Usage: `!cover <TICKER> <shares>` — e.g. `!cover DONOVAN 10`")
            return
        ticker = ticker.lstrip("$").upper()
        if ticker not in shared.MARKET_STOCKS:
            await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in shared.MARKET_STOCKS)}")
            return
        eco = load_economy()
        init_market(eco)
        ok, msg = execute_close_short(eco, ctx.author.id, ticker, shares)
        save_economy(eco)
        await ctx.send(("✅ " if ok else "❌ ") + msg)



    @commands.command(name="limitorder")
    async def limit_order(self, ctx, order_type: str = None, ticker: str = None, shares: int = None, price: float = None):
        if not all([order_type, ticker, shares, price]) or shares <= 0 or price <= 0:
            await ctx.send(
                "Usage: `!limitorder <buy|sell|short|cover> <TICKER> <shares> <price>`\n"
                "Example: `!limitorder buy DONOVAN 10 85.00`"
            )
            return
        order_type = order_type.lower()
        ticker = ticker.lstrip("$").upper()
        if order_type not in ("buy", "sell", "short", "cover"):
            await ctx.send("Order type must be `buy`, `sell`, `short`, or `cover`.")
            return
        if ticker not in shared.MARKET_STOCKS:
            await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in shared.MARKET_STOCKS)}")
            return
        eco = load_economy()
        init_market(eco)
        order_id = eco.get("next_order_id", 1)
        eco["next_order_id"] = order_id + 1
        eco.setdefault("limit_orders", []).append({
            "id": order_id,
            "user_id": str(ctx.author.id),
            "ticker": ticker,
            "order_type": order_type,
            "shares": shares,
            "limit_price": price,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        save_economy(eco)
        current = eco["market"][ticker]["price"]
        await ctx.send(
            f"📋 Limit order **#{order_id}** placed: **{order_type.upper()} {shares} ${ticker}** "
            f"@ **${price:.2f}** (current: **${current:.2f}**). You'll be notified when it fills."
        )



    @commands.command(name="cancellimit")
    async def cancel_limit(self, ctx, order_id: int = None):
        if not order_id:
            await ctx.send("Usage: `!cancellimit <order_id>`")
            return
        eco = load_economy()
        orders = eco.get("limit_orders", [])
        target = next((o for o in orders if o["id"] == order_id and o["user_id"] == str(ctx.author.id)), None)
        if not target:
            await ctx.send(f"Order **#{order_id}** not found or doesn't belong to you.")
            return
        eco["limit_orders"] = [o for o in orders if o["id"] != order_id]
        save_economy(eco)
        await ctx.send(f"✅ Limit order **#{order_id}** cancelled.")



    @commands.command(name="portfolio")
    async def portfolio_cmd(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        eco = load_economy()
        init_market(eco)
        uid = str(target.id)
        holdings = eco.get("portfolios", {}).get(uid, {})
        shorts = eco.get("short_positions", {}).get(uid, {})
        if not holdings and not shorts:
            await ctx.send(f"**{target.display_name}** has no open positions. Use `!buystock` or `!short` to get in.")
            return
        lines = [f"📈 **{target.display_name}'s Portfolio**\n"]
        total_value = 0.0
        if holdings:
            lines.append("**Long Positions:**")
            for ticker, pos in holdings.items():
                price = eco["market"][ticker]["price"]
                value = round(pos["shares"] * price, 2)
                pnl = round((price - pos["avg_cost"]) * pos["shares"], 2)
                pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
                total_value += value
                lines.append(
                    f"  **${ticker}** — {pos['shares']} shares @ avg ${pos['avg_cost']:.2f} | "
                    f"Now: ${price:.2f} | Value: {value:.0f} | P&L: **{pnl_str}**"
                )
        if shorts:
            lines.append("\n**Short Positions:**")
            for ticker, pos in shorts.items():
                price = eco["market"][ticker]["price"]
                pnl = round((pos["avg_price"] - price) * pos["shares"], 2)
                pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
                total_value += pos["collateral"] + pnl
                lines.append(
                    f"  **${ticker}** — {pos['shares']} shares short @ ${pos['avg_price']:.2f} | "
                    f"Now: ${price:.2f} | Collateral: {pos['collateral']:.0f} | P&L: **{pnl_str}**"
                )
        lines.append(f"\n**Total Portfolio Value: {total_value:.0f} coins**")
        await ctx.send("\n".join(lines))



    @commands.command(name="orders")
    async def my_orders(self, ctx):
        eco = load_economy()
        uid = str(ctx.author.id)
        orders = [o for o in eco.get("limit_orders", []) if o["user_id"] == uid]
        if not orders:
            await ctx.send("You have no pending limit orders. Use `!limitorder` to place one.")
            return
        lines = ["📋 **Your Pending Limit Orders:**\n"]
        for o in orders:
            lines.append(
                f"**#{o['id']}** — {o['order_type'].upper()} {o['shares']} **${o['ticker']}** @ **${o['limit_price']:.2f}**"
            )
        lines.append("\nUse `!cancellimit <id>` to cancel.")
        await ctx.send("\n".join(lines))



    @commands.command(name="futures")
    async def futures_cmd(self, ctx, direction: str = None, ticker: str = None, contracts: int = None):
        if not all([direction, ticker, contracts]) or contracts <= 0:
            await ctx.send(
                "Usage: `!futures <long|short> <TICKER> <contracts>` — 7-day contract, 20% margin.\n"
                "Example: `!futures long DONOVAN 10`"
            )
            return
        direction = direction.lower()
        ticker = ticker.lstrip("$").upper()
        if direction not in ("long", "short"):
            await ctx.send("Direction must be `long` or `short`.")
            return
        if ticker not in shared.MARKET_STOCKS:
            await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in shared.MARKET_STOCKS)}")
            return
        eco = load_economy()
        init_market(eco)
        init_derivatives(eco)
        price = eco["market"][ticker]["price"]
        margin = round(price * contracts * 0.20, 2)
        uid = str(ctx.author.id)
        bal = eco["balances"].get(uid, 0)
        if bal < margin:
            await ctx.send(f"Need **{margin:.0f} coins** margin (20% of position). You have **{bal}**.")
            return
        eco["balances"][uid] = bal - margin
        deriv_id = eco["next_derivative_id"]
        eco["next_derivative_id"] += 1
        expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)).isoformat()
        eco["futures"].setdefault(uid, []).append({
            "id": deriv_id,
            "ticker": ticker,
            "contracts": contracts,
            "direction": direction,
            "entry_price": price,
            "margin": margin,
            "expiry": expiry,
        })
        save_economy(eco)
        emoji = "📈" if direction == "long" else "📉"
        await ctx.send(
            f"{emoji} Opened **{direction.upper()}** futures: **{contracts}x ${ticker}** @ **${price:.2f}**. "
            f"Margin held: **{margin:.0f} coins**. Settles in 7 days. ID: **#{deriv_id}**"
        )



    @commands.command(name="closefutures")
    async def close_futures_cmd(self, ctx, deriv_id: int = None):
        if not deriv_id:
            await ctx.send("Usage: `!closefutures <id>`")
            return
        uid = str(ctx.author.id)
        eco = load_economy()
        init_market(eco)
        init_derivatives(eco)
        positions = eco["futures"].get(uid, [])
        pos = next((p for p in positions if p["id"] == deriv_id), None)
        if not pos:
            await ctx.send(f"Futures contract **#{deriv_id}** not found.")
            return
        price = eco["market"][pos["ticker"]]["price"]
        pnl = (price - pos["entry_price"]) * pos["contracts"] if pos["direction"] == "long" \
            else (pos["entry_price"] - price) * pos["contracts"]
        pnl = round(pnl, 2)
        returned = max(round(pos["margin"] + pnl, 2), 0)
        eco["balances"][uid] = eco["balances"].get(uid, 0) + returned
        eco["futures"][uid] = [p for p in positions if p["id"] != deriv_id]
        save_economy(eco)
        pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
        await ctx.send(
            f"✅ Closed futures **#{deriv_id}**: **{pos['direction'].upper()} {pos['contracts']}x ${pos['ticker']}**. "
            f"P&L: **{pnl_str} coins**. Returned: **{returned:.0f} coins**."
        )



    @commands.command(name="myfutures")
    async def my_futures_cmd(self, ctx):
        uid = str(ctx.author.id)
        eco = load_economy()
        init_market(eco)
        init_derivatives(eco)
        positions = eco["futures"].get(uid, [])
        if not positions:
            await ctx.send("No open futures. Use `!futures long/short <TICKER> <contracts>` to open one.")
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        lines = ["📅 **Your Open Futures:**\n"]
        for pos in positions:
            price = eco["market"][pos["ticker"]]["price"]
            pnl = (price - pos["entry_price"]) * pos["contracts"] if pos["direction"] == "long" \
                else (pos["entry_price"] - price) * pos["contracts"]
            pnl = round(pnl, 2)
            pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
            days_left = max(0, (datetime.datetime.fromisoformat(pos["expiry"]) - now).days)
            lines.append(
                f"**#{pos['id']}** {pos['direction'].upper()} **{pos['contracts']}x ${pos['ticker']}** "
                f"@ ${pos['entry_price']:.2f} | Now: ${price:.2f} | P&L: **{pnl_str}** | {days_left}d left"
            )
        lines.append("\nUse `!closefutures <id>` to close early.")
        await ctx.send("\n".join(lines))



    @commands.command(name="buyoption")
    async def buy_option_cmd(self, ctx, option_type: str = None, ticker: str = None, contracts: int = None, strike: float = None, days: int = 7):
        if not all([option_type, ticker, contracts, strike]) or contracts <= 0 or strike <= 0:
            await ctx.send(
                "Usage: `!buyoption <call|put> <TICKER> <contracts> <strike> [days=7]`\n"
                "Example: `!buyoption call DONOVAN 10 85 7`"
            )
            return
        option_type = option_type.lower()
        ticker = ticker.lstrip("$").upper()
        if option_type not in ("call", "put"):
            await ctx.send("Option type must be `call` or `put`.")
            return
        if ticker not in shared.MARKET_STOCKS:
            await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in shared.MARKET_STOCKS)}")
            return
        if not 1 <= days <= 30:
            await ctx.send("Expiry must be between 1 and 30 days.")
            return
        eco = load_economy()
        init_market(eco)
        init_derivatives(eco)
        spot = eco["market"][ticker]["price"]
        premium_per = calc_option_premium(spot, strike, option_type, days)
        total_premium = round(premium_per * contracts, 2)
        uid = str(ctx.author.id)
        bal = eco["balances"].get(uid, 0)
        if bal < total_premium:
            await ctx.send(
                f"Premium costs **{total_premium:.0f} coins** (${premium_per:.2f}/contract). You have **{bal}**."
            )
            return
        eco["balances"][uid] = bal - total_premium
        deriv_id = eco["next_derivative_id"]
        eco["next_derivative_id"] += 1
        expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).isoformat()
        eco["options"].setdefault(uid, []).append({
            "id": deriv_id,
            "ticker": ticker,
            "option_type": option_type,
            "contracts": contracts,
            "strike": strike,
            "premium_paid": total_premium,
            "expiry": expiry,
            "exercised": False,
        })
        save_economy(eco)
        itm = "ITM" if (option_type == "call" and spot > strike) or (option_type == "put" and spot < strike) else "OTM"
        await ctx.send(
            f"✅ Bought **{contracts}x {option_type.upper()} ${ticker}** strike **${strike:.2f}** ({itm}, spot: ${spot:.2f}). "
            f"Premium: **{total_premium:.0f} coins**. Expires in {days}d. ID: **#{deriv_id}**"
        )



    @commands.command(name="exercise")
    async def exercise_option_cmd(self, ctx, deriv_id: int = None):
        if not deriv_id:
            await ctx.send("Usage: `!exercise <id>`")
            return
        uid = str(ctx.author.id)
        eco = load_economy()
        init_market(eco)
        init_derivatives(eco)
        opt = next((o for o in eco["options"].get(uid, []) if o["id"] == deriv_id and not o.get("exercised")), None)
        if not opt:
            await ctx.send(f"Option **#{deriv_id}** not found or already exercised.")
            return
        if datetime.datetime.now(datetime.timezone.utc) > datetime.datetime.fromisoformat(opt["expiry"]):
            await ctx.send(f"Option **#{deriv_id}** has already expired.")
            return
        price = eco["market"][opt["ticker"]]["price"]
        intrinsic = (price - opt["strike"]) * opt["contracts"] if opt["option_type"] == "call" \
            else (opt["strike"] - price) * opt["contracts"]
        if intrinsic <= 0:
            await ctx.send(
                f"Option **#{deriv_id}** is out of the money. "
                f"Spot: ${price:.2f}, Strike: ${opt['strike']:.2f} — nothing to exercise."
            )
            return
        payout = round(intrinsic, 2)
        eco["balances"][uid] = eco["balances"].get(uid, 0) + payout
        opt["exercised"] = True
        save_economy(eco)
        net_pnl = round(payout - opt["premium_paid"], 2)
        net_str = f"+{net_pnl:.0f}" if net_pnl >= 0 else str(round(net_pnl))
        await ctx.send(
            f"✅ Exercised **#{deriv_id}** ({opt['option_type'].upper()} ${opt['ticker']} @ ${opt['strike']:.2f}). "
            f"Payout: **{payout:.0f} coins**. Net P&L: **{net_str} coins**."
        )



    @commands.command(name="myoptions")
    async def my_options_cmd(self, ctx):
        uid = str(ctx.author.id)
        eco = load_economy()
        init_market(eco)
        init_derivatives(eco)
        opts = [o for o in eco["options"].get(uid, []) if not o.get("exercised")]
        if not opts:
            await ctx.send("No open options. Use `!buyoption call/put <TICKER> <contracts> <strike>` to buy one.")
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        lines = ["🎯 **Your Open Options:**\n"]
        for opt in opts:
            spot = eco["market"][opt["ticker"]]["price"]
            intrinsic = max(0, (spot - opt["strike"]) * opt["contracts"]) if opt["option_type"] == "call" \
                else max(0, (opt["strike"] - spot) * opt["contracts"])
            itm = (opt["option_type"] == "call" and spot > opt["strike"]) or \
                  (opt["option_type"] == "put" and spot < opt["strike"])
            days_left = max(0, (datetime.datetime.fromisoformat(opt["expiry"]) - now).days)
            status = "✅ ITM" if itm else "❌ OTM"
            lines.append(
                f"**#{opt['id']}** {opt['option_type'].upper()} **{opt['contracts']}x ${opt['ticker']}** "
                f"strike ${opt['strike']:.2f} | Spot: ${spot:.2f} {status} | "
                f"Value: {intrinsic:.0f} | Paid: {opt['premium_paid']:.0f} | {days_left}d left"
            )
        lines.append("\nUse `!exercise <id>` to exercise early.")
        await ctx.send("\n".join(lines))




async def setup(bot):
    await bot.add_cog(StocksCog(bot))
