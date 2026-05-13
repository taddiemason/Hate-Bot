import datetime
import random
import discord
from discord.ext import commands
import shared
from shared import (
    load_economy, save_economy, add_coins, spend_coins,
    PROPERTY_TIERS, PROPERTY_COST_SCALING, PROPERTY_SABOTAGE_COST_PCT,
    PROPERTY_SABOTAGE_SUCCESS_RATE, PROPERTY_SABOTAGE_SKIP_DAYS,
    PROPERTY_SABOTAGE_COOLDOWN_HOURS, PROPERTY_SELL_REFUND_PCT,
    init_properties, get_property_count, next_property_cost,
    collect_user_properties, resolve_member_name,
)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


async def _dm(user, text):
    try:
        await user.send(text)
    except (discord.Forbidden, discord.HTTPException):
        pass


class PropertyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="property", aliases=["properties", "realty"])
    async def property_cmd(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        eco = load_economy()
        init_properties(eco)
        uid = str(target.id)
        owned = eco["properties"].get(uid, [])

        lines = [f"🏢 **{target.display_name}'s Property Portfolio**\n"]

        if owned:
            by_type = {}
            for p in owned:
                by_type.setdefault(p["type"], []).append(p)
            lines.append("**Owned:**")
            now = _now()
            for ptype, plist in by_type.items():
                tier = PROPERTY_TIERS.get(ptype)
                if not tier:
                    continue
                count = len(plist)
                net_per_day = tier["gross_per_day"] - tier["upkeep_per_day"]
                ready_days = 0
                sabotaged = 0
                for p in plist:
                    last = datetime.datetime.fromisoformat(p["last_claim"])
                    days_pending = int((now - last).total_seconds() // 86400)
                    ready_days = max(ready_days, days_pending)
                    if p.get("skip_until"):
                        su = datetime.datetime.fromisoformat(p["skip_until"])
                        if su > now:
                            sabotaged += 1
                sab_str = f"  🛠️ {sabotaged} sabotaged" if sabotaged else ""
                lines.append(
                    f"  {tier['emoji']} **{tier['name']}** ×{count} — "
                    f"~{net_per_day * count:,}/day net  |  {ready_days}d pending{sab_str}"
                )
            lines.append("")

        if target.id == ctx.author.id:
            lines.append("**Available to buy:**")
            for ptype, tier in PROPERTY_TIERS.items():
                count = get_property_count(eco, uid, ptype)
                cost = next_property_cost(eco, uid, ptype)
                net = tier["gross_per_day"] - tier["upkeep_per_day"]
                payback = cost // max(net, 1)
                owned_str = f" _(owned: {count})_" if count else ""
                lines.append(
                    f"  {tier['emoji']} **{tier['name']}** (`{ptype}`) — "
                    f"**{cost:,}** coins  →  ~{net:,}/day  (~{payback}d payback){owned_str}"
                )
            lines.append(
                "\nUse `!buyproperty <type>` to purchase, `!collect` to claim earnings, "
                "`!sellproperty <type>` to liquidate, `!sabotage @user <type>` to attack."
            )
        await ctx.send("\n".join(lines))

    @commands.command(name="buyproperty")
    async def buy_property(self, ctx, prop_type: str = None):
        if not prop_type:
            await ctx.send("Usage: `!buyproperty <type>` — see `!property` for available tiers.")
            return
        prop_type = prop_type.lower()
        if prop_type not in PROPERTY_TIERS:
            await ctx.send(f"Unknown property. Available: {', '.join(f'`{k}`' for k in PROPERTY_TIERS)}")
            return
        eco = load_economy()
        init_properties(eco)
        uid = str(ctx.author.id)
        cost = next_property_cost(eco, uid, prop_type)
        if not spend_coins(ctx.author.id, cost):
            bal = load_economy()["balances"].get(uid, 0)
            await ctx.send(f"Not enough coins. You have **{bal:,}**, this costs **{cost:,}**.")
            return
        eco = load_economy()
        init_properties(eco)
        tier = PROPERTY_TIERS[prop_type]
        eco["properties"].setdefault(uid, []).append({
            "type": prop_type,
            "purchased_at": _now().isoformat(),
            "last_claim": _now().isoformat(),
            "skip_until": None,
        })
        save_economy(eco)
        owned = get_property_count(eco, uid, prop_type)
        await ctx.send(
            f"🏢 **{ctx.author.display_name}** bought a **{tier['emoji']} {tier['name']}** for "
            f"**{cost:,} coins**! Now owns **{owned}**. Run `!collect` daily."
        )

    @commands.command(name="sellproperty")
    async def sell_property(self, ctx, prop_type: str = None):
        if not prop_type:
            await ctx.send("Usage: `!sellproperty <type>` — sells one copy at 40% of its original cost.")
            return
        prop_type = prop_type.lower()
        if prop_type not in PROPERTY_TIERS:
            await ctx.send(f"Unknown property. Available: {', '.join(f'`{k}`' for k in PROPERTY_TIERS)}")
            return
        eco = load_economy()
        init_properties(eco)
        uid = str(ctx.author.id)
        owned = [p for p in eco["properties"].get(uid, []) if p["type"] == prop_type]
        if not owned:
            await ctx.send(f"You don't own a **{PROPERTY_TIERS[prop_type]['name']}**.")
            return
        # Sell most recently purchased (highest cost) for the biggest refund.
        target_prop = max(owned, key=lambda p: p["purchased_at"])
        # Calculate what that specific copy cost: it was purchase #(N) so cost = base * scale^(N-1).
        # Without per-copy cost stored, derive from current owned count: the last one cost
        # base * scale^(owned-1).
        tier = PROPERTY_TIERS[prop_type]
        purchase_cost = round(tier["base_cost"] * (PROPERTY_COST_SCALING ** (len(owned) - 1)))
        refund = round(purchase_cost * PROPERTY_SELL_REFUND_PCT)
        eco["properties"][uid].remove(target_prop)
        if not eco["properties"][uid]:
            del eco["properties"][uid]
        save_economy(eco)
        add_coins(ctx.author.id, refund)
        await ctx.send(
            f"💸 Sold one **{tier['emoji']} {tier['name']}** for **{refund:,} coins** "
            f"(40% of {purchase_cost:,})."
        )

    @commands.command(name="collect")
    async def collect_cmd(self, ctx):
        total, results, total_days = collect_user_properties(ctx.author.id)
        if not results:
            await ctx.send("⏳ No properties have pending payouts. Each property pays out once per 24 hours.")
            return

        # Channel summary — keep it tight.
        if total >= 0:
            headline = f"💰 **{ctx.author.display_name}** collected **{total:,} coins** from {len(results)} properties."
        else:
            headline = f"📉 **{ctx.author.display_name}**'s properties cost **{abs(total):,} coins** in upkeep/fines this period."
        await ctx.send(headline)

        # DM the detailed breakdown.
        dm_lines = [f"🏢 **Property Collection Report** — {total_days} property-days settled"]
        for r in results:
            tier = r["tier"]
            dm_lines.append(
                f"\n{tier['emoji']} **{tier['name']}** — {r['days']}d → **{r['net']:+,} coins**"
            )
            if r["events"]:
                for ev in r["events"]:
                    dm_lines.append(f"  • Day {ev['day']}: {ev['emoji']} {ev['label']} ({ev['net']:+,})")
            else:
                dm_lines.append("  • Routine business, no notable events.")
        dm_lines.append(f"\n**Net total: {total:+,} coins**")
        await _dm(ctx.author, "\n".join(dm_lines))

    @commands.command(name="sabotage")
    async def sabotage(self, ctx, member: discord.Member = None, prop_type: str = None):
        if not member or not prop_type:
            await ctx.send("Usage: `!sabotage @user <type>` — costs 10% of property value, 50% success rate.")
            return
        if member.id == ctx.author.id:
            await ctx.send("You can't sabotage your own property.")
            return
        prop_type = prop_type.lower()
        if prop_type not in PROPERTY_TIERS:
            await ctx.send(f"Unknown property. Available: {', '.join(f'`{k}`' for k in PROPERTY_TIERS)}")
            return

        eco = load_economy()
        init_properties(eco)
        attacker_uid = str(ctx.author.id)
        target_uid = str(member.id)

        # Cooldown check
        cd = eco["property_sabotage_cooldowns"].get(attacker_uid)
        if cd:
            cd_dt = datetime.datetime.fromisoformat(cd)
            if cd_dt > _now():
                remaining = cd_dt - _now()
                hrs = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                await ctx.send(f"⏱️ Sabotage on cooldown. Try again in **{hrs}h {mins}m**.")
                return

        # Target must own the property
        targets = [p for p in eco["properties"].get(target_uid, []) if p["type"] == prop_type]
        if not targets:
            await ctx.send(f"**{member.display_name}** doesn't own a **{PROPERTY_TIERS[prop_type]['name']}**.")
            return

        tier = PROPERTY_TIERS[prop_type]
        cost = round(tier["base_cost"] * PROPERTY_SABOTAGE_COST_PCT)
        if not spend_coins(ctx.author.id, cost):
            bal = load_economy()["balances"].get(attacker_uid, 0)
            await ctx.send(f"Sabotage costs **{cost:,} coins** (10% of value). You have **{bal:,}**.")
            return

        # Reload after spend
        eco = load_economy()
        init_properties(eco)
        eco["property_sabotage_cooldowns"][attacker_uid] = (
            _now() + datetime.timedelta(hours=PROPERTY_SABOTAGE_COOLDOWN_HOURS)
        ).isoformat()

        success = random.random() < PROPERTY_SABOTAGE_SUCCESS_RATE
        target_props = [p for p in eco["properties"].get(target_uid, []) if p["type"] == prop_type]
        hit = random.choice(target_props)

        if success:
            skip_until = _now() + datetime.timedelta(days=PROPERTY_SABOTAGE_SKIP_DAYS)
            current_su = hit.get("skip_until")
            if current_su:
                current_dt = datetime.datetime.fromisoformat(current_su)
                if current_dt > skip_until:
                    skip_until = current_dt
            hit["skip_until"] = skip_until.isoformat()
            save_economy(eco)
            await ctx.send(
                f"💀 **SABOTAGE!** {ctx.author.display_name} torched {member.display_name}'s "
                f"**{tier['emoji']} {tier['name']}** — next **{PROPERTY_SABOTAGE_SKIP_DAYS} payouts** skipped."
            )
            await _dm(
                member,
                f"🚨 Your **{tier['emoji']} {tier['name']}** was sabotaged by **{ctx.author.display_name}** — "
                f"next {PROPERTY_SABOTAGE_SKIP_DAYS} payouts on that copy are gone."
            )
        else:
            # Failure: the would-be victim gets a free 1-day payout from that property as comeback.
            payback = tier["gross_per_day"] - tier["upkeep_per_day"]
            eco["balances"][target_uid] = round(eco["balances"].get(target_uid, 0) + payback, 2)
            save_economy(eco)
            await ctx.send(
                f"🤡 **SABOTAGE FAILED!** {ctx.author.display_name} botched the job. "
                f"{member.display_name} pockets **{payback:,} coins** in damages."
            )
            await _dm(
                member,
                f"😎 **{ctx.author.display_name}** tried to sabotage your **{tier['emoji']} {tier['name']}** "
                f"and botched it. You got **{payback:,} coins** in damages."
            )


async def setup(bot):
    await bot.add_cog(PropertyCog(bot))
