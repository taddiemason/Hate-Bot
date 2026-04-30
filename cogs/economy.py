import asyncio
import datetime
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands
import shared
from shared import (
    load_economy, save_economy, add_coins, spend_coins, get_guild_target,
    get_guild_config, is_donovan, is_double_coin_day, get_daily_reward,
    get_shop_rotation, consume_upgrade, has_upgrade, claim_bounties,
    is_insurance_active, record_trivia_win, init_market, init_derivatives,
    get_portfolio_value, _t,
)

class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _resolve_name(self, uid: int, ctx_guild) -> str:
        """Look up a display name, searching all bot guilds if not in the current one."""
        member = ctx_guild.get_member(uid)
        if member:
            return member.display_name
        for guild in self.bot.guilds:
            member = guild.get_member(uid)
            if member:
                return member.display_name
        return f"User {uid}"

    @commands.command(name="daily")
    async def daily_checkin(self, ctx):
        eco = load_economy()
        uid = str(ctx.author.id)
        now_est = datetime.datetime.now(ZoneInfo("America/New_York"))
        today = now_est.date().isoformat()
        yesterday = (now_est.date() - datetime.timedelta(days=1)).isoformat()
        data = eco.setdefault("daily_checkins", {}).get(uid, {"last_checkin": None, "streak": 0})

        if data["last_checkin"] == today:
            await ctx.send("You've already checked in today. Come back tomorrow.")
            return

        streak = data["streak"] + 1 if data["last_checkin"] == yesterday else 1
        reward = get_daily_reward(streak)
        if is_double_coin_day():
            reward *= 2

        eco["daily_checkins"][uid] = {"last_checkin": today, "streak": streak}
        save_economy(eco)
        add_coins(ctx.author.id, reward)

        streak_msg = f" 🔥 **{streak} day streak!**" if streak > 1 else ""
        milestone_msg = " 🎉 **7-DAY BONUS — DOUBLED!**" if streak % 7 == 0 else ""
        double_msg = " 💰 **Weekend 2x active!**" if is_double_coin_day() else ""
        await ctx.send(f"✅ Daily check-in! **+{reward} coins**{streak_msg}{milestone_msg}{double_msg}")



    @commands.command(name="flip")
    async def coinflip(self, ctx, arg1: str = None, arg2: str = None):
        # Accept either order: !flip 500 heads  OR  !flip heads 500
        amount, side = None, None
        for arg in (arg1, arg2):
            if arg is None:
                continue
            if arg.lower() in ("heads", "tails"):
                side = arg.lower()
            else:
                try:
                    amount = int(arg)
                except ValueError:
                    pass
        if not amount or not side:
            await ctx.send("Usage: `!flip <amount> heads` or `!flip <amount> tails`")
            return
        if amount <= 0:
            await ctx.send("Bet must be positive.")
            return
        if not spend_coins(ctx.author.id, amount):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins. You have **{bal}**.")
            return
        result = random.choice(["heads", "tails"])
        if result == side:
            add_coins(ctx.author.id, amount * 2)
            await ctx.send(f"🪙 **{result.upper()}!** You won **{amount} coins!**")
        else:
            await ctx.send(f"🪙 **{result.upper()}!** You lost **{amount} coins**. Better luck next time.")



    @commands.command(name="slots")
    async def slots(self, ctx, amount: int = None):
        if not amount or amount <= 0:
            await ctx.send("Usage: `!slots <amount>`")
            return
        if not spend_coins(ctx.author.id, amount):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins. You have **{bal}**.")
            return
        reels = [random.choice(shared.SLOT_SYMBOLS) for _ in range(3)]
        display = " | ".join(reels)
        key = tuple(reels)
        mult = shared.SLOT_PAYOUTS.get(key, 0)
        if mult == 0:
            if reels[0] == reels[1] == reels[2]:
                mult = 10
            elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
                mult = 2
        if mult > 0:
            winnings = amount * mult
            add_coins(ctx.author.id, winnings)
            try:
                await ctx.send(f"🎰 [ {display} ]\n**{mult}x PAYOUT!** You won **{winnings} coins!**")
            except Exception:
                add_coins(ctx.author.id, -winnings)
                add_coins(ctx.author.id, amount)
                raise
        else:
            try:
                await ctx.send(f"🎰 [ {display} ]\nNo match. You lost **{amount} coins**.")
            except Exception:
                add_coins(ctx.author.id, amount)
                raise



    @commands.command(name="balance")
    async def balance(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        eco = load_economy()
        init_market(eco)
        init_derivatives(eco)
        uid = str(target.id)
        bal = eco["balances"].get(uid, 0)
        portfolio = get_portfolio_value(eco, uid)

        # Unrealized futures P&L
        futures_pnl = 0.0
        for pos in eco["futures"].get(uid, []):
            price = eco["market"][pos["ticker"]]["price"]
            if pos["direction"] == "long":
                futures_pnl += (price - pos["entry_price"]) * pos["contracts"]
            else:
                futures_pnl += (pos["entry_price"] - price) * pos["contracts"]

        # Unrealized options value
        options_value = 0.0
        for opt in eco["options"].get(uid, []):
            if opt.get("exercised"):
                continue
            price = eco["market"][opt["ticker"]]["price"]
            if opt["option_type"] == "call":
                options_value += max(0, (price - opt["strike"]) * opt["contracts"])
            else:
                options_value += max(0, (opt["strike"] - price) * opt["contracts"])

        total = round(bal + portfolio + futures_pnl + options_value, 2)
        lines = [f"💰 **{target.display_name}**",
                 f"Cash: **{bal} coins**"]
        if portfolio:
            lines.append(f"Stocks/Shorts: **{portfolio:.0f} coins**")
        if futures_pnl:
            pnl_str = f"+{futures_pnl:.0f}" if futures_pnl >= 0 else f"{futures_pnl:.0f}"
            lines.append(f"Futures P&L: **{pnl_str} coins**")
        if options_value:
            lines.append(f"Options Value: **{options_value:.0f} coins**")
        lines.append(f"**Net Worth: {total:.0f} coins**")
        await ctx.send("\n".join(lines))



    @commands.command(name="leaderboard")
    async def leaderboard(self, ctx):
        eco = load_economy()
        init_market(eco)
        init_derivatives(eco)
        if not eco["balances"]:
            await ctx.send("Nobody has earned any Roast Coins yet.")
            return

        def net_worth(uid):
            uid = str(uid)
            cash = eco["balances"].get(uid, 0)
            portfolio = get_portfolio_value(eco, uid)
            futures_pnl = sum(
                (p["entry_price"] - eco["market"][p["ticker"]]["price"]) * p["contracts"]
                if p["direction"] == "short"
                else (eco["market"][p["ticker"]]["price"] - p["entry_price"]) * p["contracts"]
                for p in eco["futures"].get(uid, [])
                if p["ticker"] in eco["market"]
            )
            options_val = sum(
                max(0, (eco["market"][o["ticker"]]["price"] - o["strike"]) * o["contracts"])
                if o["option_type"] == "call"
                else max(0, (o["strike"] - eco["market"][o["ticker"]]["price"]) * o["contracts"])
                for o in eco["options"].get(uid, [])
                if not o.get("exercised") and o["ticker"] in eco["market"]
            )
            return round(cash + portfolio + futures_pnl + options_val, 2)

        top = sorted(eco["balances"].keys(), key=net_worth, reverse=True)[:5]
        lines = []
        for i, uid in enumerate(top, 1):
            name = self._resolve_name(int(uid), ctx.guild)
            cash = round(eco["balances"].get(str(uid), 0))
            total = net_worth(uid)
            portfolio = round(total - cash)
            if portfolio:
                lines.append(f"{i}. **{name}** — {total:.0f} coins net worth _(cash: {cash} + investments: {portfolio})_")
            else:
                lines.append(f"{i}. **{name}** — {total:.0f} coins")
        await ctx.send("💰 **Roast Coin Leaderboard** _(ranked by net worth)_\n" + "\n".join(lines))



    @commands.command(name="shop")
    async def shop(self, ctx):
        gid = ctx.guild.id if ctx.guild else None
        rotation, expires = get_shop_rotation()
        now = datetime.datetime.now(datetime.timezone.utc)
        seconds_left = int((expires - now).total_seconds())
        hours_left = seconds_left // 3600
        minutes_left = (seconds_left % 3600) // 60
        lines = []
        for k in rotation:
            if k not in shared.SHOP_ITEMS:
                continue
            desc_tmpl = _shared.SHOP_ITEMS_TMPL.get(k, {}).get("description", shared.SHOP_ITEMS[k]["description"])
            desc = _t(desc_tmpl, gid)
            lines.append(f"**{shared.SHOP_ITEMS[k]['name']}** (`{k}`) — {shared.SHOP_ITEMS[k]['cost']} coins\n_{desc}_")
        await ctx.send(
            f"🛒 **Roast Shop** — Today's Rotation _(refreshes in {hours_left}h {minutes_left}m)_\n\n"
            + "\n\n".join(lines)
            + "\n\nUse `!buy <item>` to purchase."
        )



    @commands.command(name="resetshop")
    @commands.has_permissions(administrator=True)
    async def resetshop(self, ctx):
        eco = load_economy()
        eco["shop_rotation"] = None
        eco["shop_rotation_expires"] = None
        save_economy(eco)
        rotation, expires = get_shop_rotation()
        now = datetime.datetime.now(datetime.timezone.utc)
        seconds_left = int((expires - now).total_seconds())
        hours_left = seconds_left // 3600
        minutes_left = (seconds_left % 3600) // 60
        lines = [f"**{shared.SHOP_ITEMS[k]['name']}** (`{k}`) — {shared.SHOP_ITEMS[k]['cost']} coins"
                 for k in rotation if k in shared.SHOP_ITEMS]
        await ctx.send(
            f"🔄 Shop rotation reset! New rotation (expires in {hours_left}h {minutes_left}m):\n"
            + "\n".join(lines)
        )



    @commands.command(name="buy")
    async def buy_item(self, ctx, item_name: str = None):
        if not item_name or item_name.lower() not in shared.SHOP_ITEMS:
            await ctx.send(f"Unknown item. Use `!shop` to see today's available items.")
            return
        rotation, _ = get_shop_rotation()
        if item_name.lower() not in rotation:
            await ctx.send(f"**{shared.SHOP_ITEMS[item_name.lower()]['name']}** isn't in today's rotation. Check `!shop` for what's available.")
            return
        item = shared.SHOP_ITEMS[item_name.lower()]
        if not spend_coins(ctx.author.id, item["cost"]):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins. You have **{bal}**, this costs **{item['cost']}**.")
            return
        eco = load_economy()
        eco.setdefault("inventory", {}).setdefault(str(ctx.author.id), []).append(item_name.lower())
        save_economy(eco)
        await ctx.send(f"✅ Purchased **{item['name']}**! It's in your inventory. Use `!use {item_name.lower()}` when you're ready to arm it.")



    @commands.command(name="inventory")
    async def inventory(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        eco = load_economy()
        owned = eco.get("inventory", {}).get(str(target.id), [])
        armed = eco.get("pending_upgrades", {}).get(str(target.id), [])
        if not owned and not armed:
            await ctx.send(f"**{target.display_name}** has no items. Buy some with `!shop`.")
            return
        lines = []
        if owned:
            lines.append("**Inventory (unequipped):**")
            for item in owned:
                lines.append(f"  • {shared.SHOP_ITEMS[item]['name']} (`{item}`)")
        if armed:
            lines.append("**Armed (fires on next @mention):**")
            for item in armed:
                lines.append(f"  ⚡ {shared.SHOP_ITEMS.get(item, {}).get('name', item)}")
        await ctx.send(f"🎒 **{target.display_name}'s Items**\n" + "\n".join(lines))



    @commands.command(name="use")
    async def use_item(self, ctx, item_name: str = None):
        if not item_name:
            await ctx.send("Usage: `!use <item_name>`")
            return
        item_name = item_name.lower()
        eco = load_economy()
        uid = str(ctx.author.id)
        owned = eco.get("inventory", {}).get(uid, [])
        if item_name not in owned:
            await ctx.send(f"You don't have a **{shared.SHOP_ITEMS.get(item_name, {}).get('name', item_name)}** in your inventory.")
            return
        owned.remove(item_name)
        eco["inventory"][uid] = owned

        if item_name == "slow_clap":
            eco["slow_clap_pending"] = eco.get("slow_clap_pending", 0) + 1
            save_economy(eco)
            gid = ctx.guild.id if ctx.guild else None
            tn = get_guild_target(gid)["name"]
            await ctx.send(f"👏 **Slow Clap** armed! It will fire on {tn}'s next message.")
            return

        eco.setdefault("pending_upgrades", {}).setdefault(uid, []).append(item_name)
        save_economy(eco)
        item = shared.SHOP_ITEMS[item_name]
        await ctx.send(f"⚡ **{item['name']}** armed! It will fire on your next @mention of the bot.")



    @commands.command(name="bounty")
    async def post_bounty(self, ctx, amount: int = None, *, description: str = None):
        gid = ctx.guild.id if ctx.guild else None
        tn = get_guild_target(gid)["name"]
        if is_donovan(ctx.author, gid):
            await ctx.send(f"{tn} cannot post bounties. They ARE the bounty.")
            return
        if not amount or not description or amount <= 0:
            await ctx.send("Usage: `!bounty <amount> <description>`")
            return
        if not spend_coins(ctx.author.id, amount):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins. You have **{bal}**.")
            return
        eco = load_economy()
        bid = eco.get("next_bounty_id", 1)
        eco["bounties"].append({"id": bid, "poster_id": str(ctx.author.id),
                                "amount": amount, "description": description, "active": True})
        eco["next_bounty_id"] = bid + 1
        save_economy(eco)
        await ctx.send(f"🎯 **Bounty #{bid} posted!**\n_{description}_\n💰 Reward: **{amount} coins** to whoever triggers the next roast!")



    @commands.command(name="bounties")
    async def view_bounties(self, ctx):
        active = [b for b in load_economy()["bounties"] if b["active"]]
        if not active:
            await ctx.send("🎯 No active bounties. Post one with `!bounty <amount> <description>`.")
            return
        lines = [f"**#{b['id']}** — {b['amount']} coins\n_{b['description']}_" for b in active]
        await ctx.send("🎯 **Active Bounties**\n\n" + "\n\n".join(lines))



    @commands.command(name="insurance")
    async def insurance(self, ctx, minutes: int = None):
        gid = ctx.guild.id if ctx.guild else None
        tn = get_guild_target(gid)["name"]
        if not is_donovan(ctx.author, gid):
            await ctx.send(f"Only {tn} needs insurance. Everyone else is fine.")
            return
        if not minutes or minutes <= 0:
            await ctx.send(f"Usage: `!insurance <minutes>` — costs {shared.INSURANCE_COST_PER_MINUTE} coins/min (max {shared.MAX_INSURANCE_MINUTES} min).")
            return
        minutes = min(minutes, shared.MAX_INSURANCE_MINUTES)
        cost = minutes * shared.INSURANCE_COST_PER_MINUTE
        if not spend_coins(ctx.author.id, cost):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins {tn}. You have **{bal}**, you need **{cost}**. Keep chatting to earn more.")
            return
        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
        eco = load_economy()
        eco["insurance_expires"] = expires.isoformat()
        save_economy(eco)
        await ctx.send(f"🛡️ {tn} bought **{minutes} minutes** of insurance for **{cost} coins**. Cute. Won't save him though.")



    @commands.command(name="give")
    async def give_coins(self, ctx, member: discord.Member = None, amount: int = None):
        if not member or not amount or amount <= 0:
            await ctx.send("Usage: `!give @user <amount>`")
            return
        if member.id == ctx.author.id:
            await ctx.send("You can't give coins to yourself.")
            return
        if not spend_coins(ctx.author.id, amount):
            await ctx.send("Not enough coins.")
            return
        add_coins(member.id, amount)
        await ctx.send(f"💸 **{ctx.author.display_name}** sent **{amount} Roast Coins** to **{member.display_name}**.")



    @commands.command(name="blackmarket")
    async def black_market(self, ctx):
        listings = [l for l in load_economy().get("market_listings", []) if l["active"]]
        if not listings:
            await ctx.send("🕶️ **Black Market**\nNo listings right now. Use `!listitem <item> <price>` to sell an upgrade.")
            return
        lines = []
        for l in listings:
            name = self._resolve_name(int(l["seller_id"]), ctx.guild)
            item = shared.SHOP_ITEMS.get(l["item"], {}).get("name", l["item"])
            lines.append(f"**#{l['id']}** — {item} by {name} — {l['price']} coins  →  `!buyitem {l['id']}`")
        await ctx.send("🕶️ **Black Market**\n\n" + "\n".join(lines))



    @commands.command(name="listitem")
    async def list_item(self, ctx, item_name: str = None, price: int = None):
        if not item_name or not price or price <= 0:
            await ctx.send("Usage: `!listitem <item_name> <price>`")
            return
        item_name = item_name.lower()
        if item_name not in shared.SHOP_ITEMS:
            await ctx.send(f"Unknown item. Valid items: {', '.join(shared.SHOP_ITEMS.keys())}")
            return
        eco = load_economy()
        uid = str(ctx.author.id)
        owned = eco.get("inventory", {}).get(uid, [])
        if item_name not in owned:
            await ctx.send(f"You don't have a **{shared.SHOP_ITEMS[item_name]['name']}** in your inventory to sell.")
            return
        owned.remove(item_name)
        eco["inventory"][uid] = owned
        lid = eco.get("next_listing_id", 1)
        eco.setdefault("market_listings", []).append(
            {"id": lid, "seller_id": str(ctx.author.id), "item": item_name, "price": price, "active": True}
        )
        eco["next_listing_id"] = lid + 1
        save_economy(eco)
        await ctx.send(f"🕶️ Listed **{shared.SHOP_ITEMS[item_name]['name']}** for **{price} coins** on the black market (ID #{lid}).")



    @commands.command(name="buyitem")
    async def buy_market_item(self, ctx, listing_id: int = None):
        if not listing_id:
            await ctx.send("Usage: `!buyitem <listing_id>`")
            return
        eco = load_economy()
        listing = next((l for l in eco.get("market_listings", []) if l["id"] == listing_id and l["active"]), None)
        if not listing:
            await ctx.send("Listing not found or already sold.")
            return
        if listing["seller_id"] == str(ctx.author.id):
            await ctx.send("You can't buy your own listing.")
            return
        if not spend_coins(ctx.author.id, listing["price"]):
            await ctx.send("Not enough coins.")
            return
        add_coins(int(listing["seller_id"]), listing["price"])
        listing["active"] = False
        eco.setdefault("inventory", {}).setdefault(str(ctx.author.id), []).append(listing["item"])
        save_economy(eco)
        seller = ctx.guild.get_member(int(listing["seller_id"]))
        seller_name = seller.display_name if seller else "Unknown"
        item_name = shared.SHOP_ITEMS.get(listing["item"], {}).get("name", listing["item"])
        await ctx.send(f"🕶️ **{ctx.author.display_name}** bought **{item_name}** from **{seller_name}** for **{listing['price']} coins**.")



    @commands.command(name="trivialeaderboard")
    async def trivia_leaderboard(self, ctx):
        eco = load_economy()
        wins = eco.get("trivia_wins", {})
        if not wins:
            await ctx.send("Nobody has won a trivia question yet.")
            return
        top = sorted(wins.items(), key=lambda x: x[1], reverse=True)[:10]
        lines = []
        for i, (uid, count) in enumerate(top, 1):
            name = self._resolve_name(int(uid), ctx.guild)
            lines.append(f"{i}. **{name}** — {count} win{'s' if count != 1 else ''}")
        await ctx.send("🧠 **Trivia Leaderboard** _(all-time wins across !trivia and !sportstrivia)_\n" + "\n".join(lines))




async def setup(bot):
    await bot.add_cog(EconomyCog(bot))
