import datetime
import random
import discord
from discord.ext import commands
import shared
from shared import (
    load_economy, save_economy, add_coins, spend_coins,
    PROPERTY_TIERS, PROPERTY_PERKS, PROPERTY_COST_SCALING,
    PROPERTY_SABOTAGE_COST_PCT, PROPERTY_SABOTAGE_SUCCESS_RATE,
    PROPERTY_SABOTAGE_SKIP_DAYS, PROPERTY_SABOTAGE_COOLDOWN_HOURS,
    PROPERTY_SELL_REFUND_PCT,
    init_properties, get_property_count, next_property_cost,
    collect_user_properties, get_property_rotation,
)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


async def _dm(user, text):
    try:
        await user.send(text)
    except (discord.Forbidden, discord.HTTPException):
        pass


def _resolve_tier_arg(arg):
    """Match a tier key by exact key, partial key, or display name. Returns key or None."""
    if not arg:
        return None
    a = arg.lower().replace(" ", "_").replace("-", "_")
    if a in PROPERTY_TIERS:
        return a
    for key, tier in PROPERTY_TIERS.items():
        if tier["name"].lower() == arg.lower():
            return key
    # Partial match by key prefix
    matches = [k for k in PROPERTY_TIERS if k.startswith(a)]
    if len(matches) == 1:
        return matches[0]
    return None


def _resolve_perk_arg(arg):
    if not arg:
        return None
    a = arg.lower()
    if a in PROPERTY_PERKS:
        return a
    for key, perk in PROPERTY_PERKS.items():
        if perk["label"].lower() == a:
            return key
    return None


class PropertyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="property", aliases=["properties", "realty"])
    async def property_cmd(self, ctx, *, arg: str = None):
        """`!property` — overview. `!property <tier>` — detailed view of one tier."""
        eco = load_economy()
        init_properties(eco)
        uid = str(ctx.author.id)

        # If the arg is a member mention, show that user's portfolio. If it's a tier key,
        # show tier detail. Otherwise show the overview for the author.
        tier_key = _resolve_tier_arg(arg) if arg else None

        if tier_key:
            await self._send_tier_detail(ctx, tier_key)
            return

        # Try resolving as @member (existing behaviour) — but only if it parses.
        member = None
        if arg and ctx.message.mentions:
            member = ctx.message.mentions[0]
        target = member or ctx.author

        rotation, expires = get_property_rotation()
        secs_left = max(0, int((expires - _now()).total_seconds()))
        hrs, mins = secs_left // 3600, (secs_left % 3600) // 60

        owned = eco["properties"].get(str(target.id), [])

        lines = [f"🏢 **{target.display_name}'s Property Portfolio**"]
        if owned:
            lines.append("")
            lines.append("**Owned:**")
            # Group by (tier, perk)
            by_variant = {}
            now = _now()
            for p in owned:
                key = (p["type"], p.get("perk"))
                by_variant.setdefault(key, []).append(p)
            for (ptype, perk_key), plist in by_variant.items():
                tier = PROPERTY_TIERS.get(ptype)
                perk = PROPERTY_PERKS.get(perk_key)
                if not tier or not perk:
                    continue
                count = len(plist)
                base_net = tier["gross_per_day"] - tier["upkeep_per_day"]
                gross = tier["gross_per_day"] * perk.get("gross_mult", 1.0)
                upkeep = tier["upkeep_per_day"] * perk.get("upkeep_mult", 1.0)
                net_per_day = round(gross - upkeep)
                pending = 0
                sabotaged = 0
                for p in plist:
                    last = datetime.datetime.fromisoformat(p["last_claim"])
                    days = int((now - last).total_seconds() // 86400)
                    pending = max(pending, days)
                    if p.get("skip_until"):
                        su = datetime.datetime.fromisoformat(p["skip_until"])
                        if su > now:
                            sabotaged += 1
                sab_str = f" ({sabotaged} sabotaged)" if sabotaged else ""
                lines.append(
                    f"  {tier['emoji']} **{perk['label']} {tier['name']}** ×{count} — "
                    f"~{net_per_day * count:,}/day net | {pending}d pending{sab_str}"
                )

        if target.id == ctx.author.id:
            lines.append("")
            lines.append(f"**Today's Rotation** _(refreshes in {hrs}h {mins}m)_")
            for tier_key, tier in PROPERTY_TIERS.items():
                perks_today = rotation.get(tier_key, [])
                count = get_property_count(eco, uid, tier_key)
                cost = next_property_cost(eco, uid, tier_key)
                owned_str = f" _(owned: {count})_" if count else ""
                if perks_today:
                    pk = perks_today[0]
                    perk = PROPERTY_PERKS[pk]
                    perk_str = f"**{perk['label']}** — _{perk['desc']}_"
                else:
                    perk_str = "_(no variant today)_"
                lines.append(
                    f"  {tier['emoji']} **{tier['name']}** — {cost:,} coins · {perk_str}{owned_str}"
                )
            lines.append(
                "\n`!buyproperty <tier>` to purchase today's variant. `!collect` to claim. "
                "`!sellproperty <tier> [perk]` to sell. `!sabotage @user <tier>` to attack."
            )

        # Discord caps single messages around 2000 chars. Split if needed.
        text = "\n".join(lines)
        if len(text) <= 1900:
            await ctx.send(text)
        else:
            chunk, length = [], 0
            for line in lines:
                if length + len(line) > 1800:
                    await ctx.send("\n".join(chunk))
                    chunk, length = [], 0
                chunk.append(line)
                length += len(line) + 1
            if chunk:
                await ctx.send("\n".join(chunk))

    async def _send_tier_detail(self, ctx, tier_key):
        rotation, expires = get_property_rotation()
        eco = load_economy()
        init_properties(eco)
        uid = str(ctx.author.id)
        tier = PROPERTY_TIERS[tier_key]
        perks_today = rotation.get(tier_key, [])
        secs_left = max(0, int((expires - _now()).total_seconds()))
        hrs, mins = secs_left // 3600, (secs_left % 3600) // 60
        count = get_property_count(eco, uid, tier_key)
        cost = next_property_cost(eco, uid, tier_key)
        base_net = tier["gross_per_day"] - tier["upkeep_per_day"]
        payback = cost // max(base_net, 1)

        lines = [
            f"{tier['emoji']} **{tier['name']}** _(rotation refreshes in {hrs}h {mins}m)_",
            f"Next purchase: **{cost:,}** coins · Base: {tier['gross_per_day']:,} gross − {tier['upkeep_per_day']:,} upkeep = **{base_net:,}/day** (~{payback}d payback)",
            "",
        ]
        for perk_key in perks_today:
            perk = PROPERTY_PERKS[perk_key]
            gross = round(tier["gross_per_day"] * perk.get("gross_mult", 1.0))
            upkeep = round(tier["upkeep_per_day"] * perk.get("upkeep_mult", 1.0))
            net = gross - upkeep
            lines.append(
                f"**{perk['label']}** — _{perk['desc']}_\n"
                f"~{net:,}/day net → `!buyproperty {tier_key}`"
            )
        await ctx.send("\n".join(lines))

    @commands.command(name="buyproperty")
    async def buy_property(self, ctx, prop_type: str = None, perk_arg: str = None):
        tier_key = _resolve_tier_arg(prop_type)
        if not tier_key:
            await ctx.send(f"Usage: `!buyproperty <tier> [perk]`. See `!property` for what's in rotation.")
            return

        rotation, _ = get_property_rotation()
        todays_perks = rotation.get(tier_key, [])

        if perk_arg:
            perk_key = _resolve_perk_arg(perk_arg)
            if not perk_key:
                await ctx.send(f"Unknown perk `{perk_arg}`. Run `!property {tier_key}` to see today's variant.")
                return
        else:
            if not todays_perks:
                await ctx.send(f"No variant is in rotation for **{PROPERTY_TIERS[tier_key]['name']}** today.")
                return
            perk_key = todays_perks[0]

        if perk_key not in todays_perks:
            await ctx.send(
                f"**{PROPERTY_PERKS[perk_key]['label']} {PROPERTY_TIERS[tier_key]['name']}** isn't in today's rotation. "
                f"Run `!property {tier_key}` to see what is."
            )
            return

        eco = load_economy()
        init_properties(eco)
        uid = str(ctx.author.id)
        cost = next_property_cost(eco, uid, tier_key)
        if not spend_coins(ctx.author.id, cost):
            bal = load_economy()["balances"].get(uid, 0)
            await ctx.send(f"Not enough coins. You have **{bal:,}**, this costs **{cost:,}**.")
            return
        eco = load_economy()
        init_properties(eco)
        tier = PROPERTY_TIERS[tier_key]
        perk = PROPERTY_PERKS[perk_key]
        eco["properties"].setdefault(uid, []).append({
            "type": tier_key,
            "perk": perk_key,
            "purchased_at": _now().isoformat(),
            "last_claim": _now().isoformat(),
            "skip_until": None,
        })
        save_economy(eco)
        total = get_property_count(eco, uid, tier_key)
        await ctx.send(
            f"🏢 **{ctx.author.display_name}** bought a {tier['emoji']} "
            f"**{perk['label']} {tier['name']}** for **{cost:,} coins**! "
            f"Now owns **{total}** of this tier. Run `!collect` once 24h have passed."
        )

    @commands.command(name="sellproperty")
    async def sell_property(self, ctx, prop_type: str = None, perk_arg: str = None):
        tier_key = _resolve_tier_arg(prop_type)
        if not tier_key:
            await ctx.send("Usage: `!sellproperty <tier> [perk]` — sells one copy at 40% of its purchase cost.")
            return
        perk_key = _resolve_perk_arg(perk_arg) if perk_arg else None

        eco = load_economy()
        init_properties(eco)
        uid = str(ctx.author.id)
        all_of_tier = [p for p in eco["properties"].get(uid, []) if p["type"] == tier_key]
        if not all_of_tier:
            await ctx.send(f"You don't own any **{PROPERTY_TIERS[tier_key]['name']}**.")
            return

        candidates = (
            [p for p in all_of_tier if p.get("perk") == perk_key] if perk_key else all_of_tier
        )
        if not candidates:
            await ctx.send(
                f"You don't own a **{PROPERTY_PERKS[perk_key]['label']} {PROPERTY_TIERS[tier_key]['name']}**."
            )
            return

        # Sell most recently purchased copy (highest derived cost).
        target_prop = max(candidates, key=lambda p: p["purchased_at"])
        tier = PROPERTY_TIERS[tier_key]
        purchase_cost = round(tier["base_cost"] * (PROPERTY_COST_SCALING ** (len(all_of_tier) - 1)))
        refund = round(purchase_cost * PROPERTY_SELL_REFUND_PCT)
        eco["properties"][uid].remove(target_prop)
        if not eco["properties"][uid]:
            del eco["properties"][uid]
        save_economy(eco)
        add_coins(ctx.author.id, refund)
        perk = PROPERTY_PERKS.get(target_prop.get("perk"), {"label": ""})
        await ctx.send(
            f"💸 Sold one {tier['emoji']} **{perk.get('label','')} {tier['name']}** for "
            f"**{refund:,} coins** (40% of {purchase_cost:,})."
        )

    @commands.command(name="collect")
    async def collect_cmd(self, ctx):
        total, results, total_days = collect_user_properties(ctx.author.id)
        if not results:
            await ctx.send("⏳ No properties have pending payouts. Each property pays once per 24 hours.")
            return

        if total >= 0:
            headline = f"💰 **{ctx.author.display_name}** collected **{total:,} coins** from {len(results)} properties."
        else:
            headline = f"📉 **{ctx.author.display_name}**'s properties cost **{abs(total):,} coins** in upkeep/fines this period."
        await ctx.send(headline)

        # DM detailed breakdown
        dm_lines = [f"🏢 **Property Collection Report** — {total_days} property-days settled"]
        for r in results:
            tier = r["tier"]
            prop = r["prop"]
            perk = PROPERTY_PERKS.get(prop.get("perk"), {"label": ""})
            dm_lines.append(
                f"\n{tier['emoji']} **{perk.get('label','')} {tier['name']}** — {r['days']}d → **{r['net']:+,} coins**"
            )
            if r["events"]:
                for ev in r["events"]:
                    dm_lines.append(f"  • Day {ev['day']}: {ev['label']} ({ev['net']:+,})")
            else:
                dm_lines.append("  • Routine business, no notable events.")
        dm_lines.append(f"\n**Net total: {total:+,} coins**")
        await _dm(ctx.author, "\n".join(dm_lines))

    @commands.command(name="sabotage")
    async def sabotage(self, ctx, member: discord.Member = None, prop_type: str = None):
        if not member or not prop_type:
            await ctx.send("Usage: `!sabotage @user <tier>` — 10% cost, 50% success, 24h cooldown.")
            return
        if member.id == ctx.author.id:
            await ctx.send("You can't sabotage your own property.")
            return
        tier_key = _resolve_tier_arg(prop_type)
        if not tier_key:
            await ctx.send(f"Unknown tier. Available: {', '.join(f'`{k}`' for k in PROPERTY_TIERS)}")
            return

        eco = load_economy()
        init_properties(eco)
        attacker_uid = str(ctx.author.id)
        target_uid = str(member.id)

        cd = eco["property_sabotage_cooldowns"].get(attacker_uid)
        if cd:
            cd_dt = datetime.datetime.fromisoformat(cd)
            if cd_dt > _now():
                remaining = cd_dt - _now()
                hrs = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                await ctx.send(f"⏱️ Sabotage on cooldown. Try again in **{hrs}h {mins}m**.")
                return

        targets = [p for p in eco["properties"].get(target_uid, []) if p["type"] == tier_key]
        if not targets:
            await ctx.send(f"**{member.display_name}** doesn't own a **{PROPERTY_TIERS[tier_key]['name']}**.")
            return

        tier = PROPERTY_TIERS[tier_key]
        cost = round(tier["base_cost"] * PROPERTY_SABOTAGE_COST_PCT)
        if not spend_coins(ctx.author.id, cost):
            bal = load_economy()["balances"].get(attacker_uid, 0)
            await ctx.send(f"Sabotage costs **{cost:,} coins** (10% of value). You have **{bal:,}**.")
            return

        eco = load_economy()
        init_properties(eco)
        eco["property_sabotage_cooldowns"][attacker_uid] = (
            _now() + datetime.timedelta(hours=PROPERTY_SABOTAGE_COOLDOWN_HOURS)
        ).isoformat()

        success = random.random() < PROPERTY_SABOTAGE_SUCCESS_RATE
        target_props = [p for p in eco["properties"].get(target_uid, []) if p["type"] == tier_key]
        hit = random.choice(target_props)
        hit_perk = PROPERTY_PERKS.get(hit.get("perk"), {"emoji": "", "label": ""})

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
                f"{tier['emoji']} **{hit_perk.get('label','')} {tier['name']}** — "
                f"next **{PROPERTY_SABOTAGE_SKIP_DAYS} payouts** skipped on that copy."
            )
            await _dm(
                member,
                f"🚨 Your {tier['emoji']} **{hit_perk.get('label','')} {tier['name']}** "
                f"was sabotaged by **{ctx.author.display_name}** — "
                f"next {PROPERTY_SABOTAGE_SKIP_DAYS} payouts on that copy are gone."
            )
        else:
            payback = round(tier["gross_per_day"] - tier["upkeep_per_day"])
            eco["balances"][target_uid] = round(eco["balances"].get(target_uid, 0) + payback, 2)
            save_economy(eco)
            await ctx.send(
                f"🤡 **SABOTAGE FAILED!** {ctx.author.display_name} botched the job. "
                f"{member.display_name} pockets **{payback:,} coins** in damages."
            )
            await _dm(
                member,
                f"😎 **{ctx.author.display_name}** tried to sabotage your **{tier['name']}** and botched it. "
                f"You got **{payback:,} coins** in damages."
            )

    @commands.command(name="propertyhelp", aliases=["realtyhelp"])
    async def property_help(self, ctx):
        page1 = (
            "🏢 **Property Guide — Basics**\n\n"
            "Property is passive income for coins. Buy a business, let it run, claim earnings every 24 hours.\n\n"
            "**Core commands**\n"
            "`!property` — Today's rotation + your owned properties.\n"
            "`!property <tier>` — Detailed view of one tier's variants (e.g. `!property casino`).\n"
            "`!buyproperty <tier> [perk]` — Buy today's variant for that tier (the `<perk>` arg is optional since only one variant rotates per tier per day).\n"
            "`!collect` — Claim accumulated earnings. Channel shows the total; the per-day event log is DMed.\n"
            "`!sellproperty <tier> [perk]` — Sell one copy for **40%** of its purchase cost.\n"
            "`!sabotage @user <tier>` — Attack someone else's property.\n\n"
            "**Tiers** _(9 total, scaling cost)_\n"
            "🍋 Lemonade Stand · 🚚 Food Truck · 🎣 Bait & Tackle · 🍕 Pizza Place · 💨 Vape Shop · "
            "🏬 Strip Mall · 🚗 Used Car Lot · 🎰 Casino · ⛏️ Crypto Mine\n\n"
            "Each tier has a base purchase cost. **Each additional copy of the same tier costs 1.5× more** "
            "(so the 2nd Lemonade Stand is 7,500, the 3rd is 11,250, etc.). This keeps whales from buying 100 "
            "Crypto Mines and breaking the economy.\n\n"
            "_Page 1/3_"
        )
        page2 = (
            "🏢 **Property Guide — Daily Rotation & Perks**\n\n"
            "Every tier has a pool of **10 themed perk variants**. **One variant per tier rotates into availability each day**, "
            "refreshing at midnight America/New_York. You can only buy whichever variant is currently in rotation for that tier.\n\n"
            "Once you buy it, the perk is **permanent** — a Sunny Lemonade Stand stays Sunny forever, even after rotation moves on.\n\n"
            "**Perk archetypes**\n"
            "**Sunny** — +25% gross income\n"
            "**Lean** — −40% upkeep\n"
            "**Hot Spot** — +75% boom chance\n"
            "**Fortified** — −60% disaster chance\n"
            "**Tax Haven** — Immune to audits & lawsuits\n"
            "**Insured** — Immune to fires & vandalism\n"
            "**Volatile** — +40% gross, but +100% disaster chance\n"
            "**Steady** — −60% disasters AND −60% booms (low variance)\n"
            "**Premium** — +15% gross AND −15% upkeep\n"
            "**Automated** — −75% upkeep BUT −25% gross\n\n"
            "Different perks suit different playstyles — Tax Haven on a Casino, Automated on a Crypto Mine, "
            "Volatile when you want to gamble for big payouts. Wait for the right roll, or buy what's there today.\n\n"
            "_Page 2/3_"
        )
        page3 = (
            "🏢 **Property Guide — Collection, Events & Sabotage**\n\n"
            "**Manual collection**\n"
            "Earnings accumulate at one payout per 24 hours per property. `!collect` settles every elapsed full day across "
            "everything you own. If you go 5 days without collecting, you get ~5 days of payouts at once (with 5 independent "
            "event rolls). Channel shows the net total; **a full per-day breakdown is DMed to you.**\n\n"
            "**Random events** _(rolled per simulated day per property)_\n"
            "Disasters:  🚨 Health inspector · 💀 Vandalism · 📋 Tax audit · ⚖️ Lawsuit · 🔥 Kitchen fire\n"
            "Booms:  📱 Viral TikTok (2×) · 🎤 Celebrity sighting (3×) · 💎 Lucky day (1.5×)\n"
            "Your perk shifts these odds. Audits/lawsuits also charge a fine equal to 5% of the property's base value.\n\n"
            "**Sabotage**\n"
            "`!sabotage @user <tier>` lets you attack someone's property for **10% of its base value** in coins. "
            "**50% success rate** — on success, one random copy of that tier they own loses its next **3 payouts**. "
            "On failure, the target gets a free day's earnings as compensation. 24-hour cooldown per attacker.\n\n"
            "**Selling**\n"
            "`!sellproperty <tier> [perk]` refunds **40%** of the most recent purchase cost for that tier. "
            "Useful if you bought the wrong perk or need liquidity, but you take a 60% hit.\n\n"
            "_Page 3/3_"
        )
        for page in (page1, page2, page3):
            await ctx.send(page)


async def setup(bot):
    await bot.add_cog(PropertyCog(bot))
