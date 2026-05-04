import asyncio
import random
import datetime
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks
import shared
from shared import update_stocks_on_roast, claim_bounties, _t
from database import load_count, save_count, log_roast
from web_admin import log_event

class RoastCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.scheduled_roast.start()
        self.weekly_recap.start()

    async def cog_unload(self):
        self.scheduled_roast.cancel()
        self.weekly_recap.cancel()

    @tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=ZoneInfo("America/New_York")))
    async def scheduled_roast(self):
        today = datetime.datetime.now(ZoneInfo("America/New_York")).weekday()
        guild_channels = shared._get_guild_channels()
        for gid, channel in guild_channels:
            if today == 0:
                await channel.send(_t(random.choice(shared._MONDAY_ROASTS_TMPL), gid))
                asyncio.create_task(shared._apply_roast_stock_impact(gid))
            elif today == 4:
                msg = _t(random.choice(shared._FRIDAY_ROASTS_TMPL), gid)
                await channel.send(msg)
                await shared.tts_queue.put((channel.guild.id, msg))
                asyncio.create_task(shared._apply_roast_stock_impact(gid))



    @tasks.loop(time=datetime.time(hour=21, minute=0, tzinfo=ZoneInfo("America/New_York")))
    async def weekly_recap(self):
        today = datetime.datetime.now(ZoneInfo("America/New_York")).weekday()
        if today != 6:  # Sunday only
            return

        guild_channels = shared._get_guild_channels()
        if not guild_channels:
            return

        total, log = shared.get_weekly_recap()
        busiest_day = hour_label = None
        if total:
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            day_counts = [0] * 7
            hour_counts = [0] * 24
            for ts in log:
                dt = datetime.datetime.fromisoformat(ts)
                day_counts[dt.weekday()] += 1
                hour_counts[dt.hour] += 1
            busiest_day = day_names[day_counts.index(max(day_counts))]
            busiest_hour = hour_counts.index(max(hour_counts))
            hour_label = datetime.datetime(2000, 1, 1, busiest_hour).strftime("%I %p").lstrip("0")

        # Lottery drawing (once — shared economy)
        eco = shared.load_economy()
        shared.init_market(eco)
        tickets = eco.get("lottery_tickets", {})
        pot = eco.get("lottery_pot", 0)
        lottery_winner_id = None
        pool = []
        if tickets and pot > 0:
            for uid, count in tickets.items():
                pool.extend([uid] * count)
            lottery_winner_id = random.choice(pool)
            shared.add_coins(int(lottery_winner_id), pot)
            eco = shared.load_economy()
        eco["lottery_tickets"] = {}
        eco["lottery_pot"] = 500
        # Reset weekly volume
        for ticker in eco.get("market", {}):
            eco["market"][ticker]["volume_today"] = 0
        shared.save_economy(eco)

        for gid, channel in guild_channels:
            tgt_name = shared.get_guild_target(gid)["name"] if gid else shared.TARGET_NAME

            if not total:
                await channel.send(
                    f"📊 **Weekly Roast Recap**\n{tgt_name} somehow avoided getting roasted this week. Suspicious."
                )
            else:
                await channel.send(
                    f"📊 **Weekly Roast Recap**\n"
                    f"{tgt_name} got roasted **{total} times** this week. Impressive dedication everyone.\n\n"
                    f"🏆 Most active day: **{busiest_day}**\n"
                    f"⏰ Peak roast hour: **{hour_label} UTC**\n\n"
                    f"See you all next week for more {tgt_name} disrespect."
                )

            # Portfolio standings (per-guild for member display names)
            eco2 = shared.load_economy()
            all_uids = set(eco2.get("portfolios", {}).keys()) | set(eco2.get("short_positions", {}).keys())
            if all_uids:
                ranked = sorted(all_uids, key=lambda u: shared.get_portfolio_value(eco2, u), reverse=True)
                lines = ["📈 **Weekly Portfolio Standings**\n"]
                for i, uid in enumerate(ranked[:5], 1):
                    member = channel.guild.get_member(int(uid))
                    mname = member.display_name if member else "Unknown"
                    val = shared.get_portfolio_value(eco2, uid)
                    medal = ["🥇", "🥈", "🥉", "4.", "5."][i - 1]
                    lines.append(f"{medal} **{mname}** — {val:.0f} coins")
                if len(ranked) > 1:
                    loser_uid = ranked[-1]
                    loser = channel.guild.get_member(int(loser_uid))
                    loser_name = loser.display_name if loser else "Unknown"
                    loser_val = shared.get_portfolio_value(eco2, loser_uid)
                    lines.append(f"\n💀 Biggest loser: **{loser_name}** — {loser_val:.0f} coins")
                await channel.send("\n".join(lines))

            # Lottery result
            if lottery_winner_id:
                winner_member = channel.guild.get_member(int(lottery_winner_id))
                winner_display = winner_member.display_name if winner_member else "Someone"
                await channel.send(
                    f"🎟️ **WEEKLY LOTTERY DRAWING!**\n\n"
                    f"Out of {len(pool)} tickets...\n"
                    f"🏆 **{winner_display}** wins the **{pot} coin** pot!\n"
                    f"New lottery starts now. Buy tickets with `!lottery <amount>`."
                )
            else:
                await channel.send(
                    "🎟️ No lottery tickets sold this week. New pot resets to **500 coins**."
                )



    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        gid = message.guild.id if message.guild else None
        tgt = shared.get_guild_target(gid)
        tgt_name = tgt["name"]
        tgt_usernames = {u.lower() for u in tgt["usernames"]}

        # First message of the day bonus (per-guild, keyed by guild+date)
        today = datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        eco = shared.load_economy()
        fmtd_key = f"first_message_today_{gid}" if gid else "first_message_today"
        if eco.get(fmtd_key) != today:
            eco[fmtd_key] = today
            shared.save_economy(eco)
            bonus = 30 if shared.is_double_coin_day() else 15
            shared.add_coins(message.author.id, bonus)
            await message.channel.send(f"🌅 {message.author.mention} sent the first message of the day! **+{bonus} coins!**")

        # Higher or lower game responses
        if message.author.id in shared.highlow_games:
            game = shared.highlow_games[message.author.id]
            if message.channel.id == game["channel_id"]:
                content = message.content.lower().strip()
                if content in ("higher", "lower"):
                    new_num = random.randint(1, 100)
                    old_num = game["number"]
                    correct = (content == "higher" and new_num > old_num) or (content == "lower" and new_num < old_num)
                    if new_num == old_num:
                        await message.channel.send(f"🎯 It's **{new_num}** — a tie! Keep going.")
                    elif correct:
                        if content == "higher":
                            p_win = max(0.01, (100 - old_num) / 100)
                        else:
                            p_win = max(0.01, (old_num - 1) / 100)
                        game["multiplier"] = round(game["multiplier"] * (1 / p_win), 2)
                        game["number"] = new_num
                        await message.channel.send(f"✅ **{new_num}!** Correct! Multiplier: **{game['multiplier']}x** — type `higher`, `lower`, or `cashout`.")
                    else:
                        bet = game["bet"]
                        del shared.highlow_games[message.author.id]
                        await message.channel.send(f"❌ **{new_num}!** Wrong! You lost **{bet} coins**.")
                elif content == "cashout":
                    winnings = round(game["bet"] * game["multiplier"])
                    shared.add_coins(message.author.id, winnings)
                    del shared.highlow_games[message.author.id]
                    await message.channel.send(f"💰 Cashed out at **{game['multiplier']}x**! You won **{winnings} coins**!")

        # Guess the roast answer check
        if shared.guessroast_active and not message.author.bot:
            if tgt_name.lower() in message.content.lower():
                shared.guessroast_active = False
                shared.add_coins(message.author.id, 30)
                await message.channel.send(f"✅ {message.author.mention} got it! It was **{tgt_name}** (obviously). **+30 coins!**")

        bot_member = message.guild.get_member(self.bot.user.id) if message.guild else None
        bot_mentioned = self.bot.user in message.mentions or (
            bot_member and any(role in message.role_mentions for role in bot_member.roles)
        )

        if message.author.name.lower() in tgt_usernames:
            shared.add_coins(message.author.id, 1)
            eco = shared.load_economy()
            if eco.get("slow_clap_pending", 0) > 0:
                eco["slow_clap_pending"] -= 1
                shared.save_economy(eco)
                for _ in range(5):
                    await message.add_reaction("👏")

        if message.author.name.lower() in tgt_usernames and len(message.content) > 10 and random.random() < 0.1:
            if await shared.is_hot_take(message.content):
                flagged = await message.reply(
                    f"🚨 **HOT TAKE ALERT** 🚨\n{tgt_name} is at it again. React to cast your vote:"
                )
                await flagged.add_reaction("🔥")
                await flagged.add_reaction("🧊")

        if bot_mentioned:
            try:
                if message.author.name.lower() in tgt_usernames:
                    question = shared.get_question(message)
                    comeback = await shared.argue_with_donovan(question if question else "hey", gid)
                    await message.channel.send(comeback)
                    asyncio.create_task(shared._apply_roast_stock_impact(gid))
                    return

                question = shared.get_question(message)
                print(f"[DEBUG] Mention detected. Question: '{question}'")

                if question:
                    print(f"[DEBUG] Sending to Groq...")
                    reply = await shared.ask_openai(question, gid)
                else:
                    activity = shared.get_donovan_activity(message.guild, gid) if message.guild else None
                    if activity and "rust" in activity.lower():
                        reply = shared._t(random.choice(shared._RUST_ROASTS_TMPL), gid)
                    elif activity and "world of warcraft" in activity.lower():
                        reply = shared._t(random.choice(shared._WOW_ROASTS_TMPL), gid)
                    else:
                        reply = shared._t(random.choice(shared._GENERAL_ROASTS_TMPL), gid)

                print(f"[DEBUG] Sending reply: '{reply}'")

                if shared.is_insurance_active():
                    await message.channel.send(f"🛡️ {tgt_name}'s insurance is active... unfortunately it doesn't cover being a loser.")

                send_text = reply
                force_tts = False

                if shared.consume_upgrade(message.author.id, "shame_bell"):
                    await message.channel.send("🔔 **SHAME** 🔔 🔔 **SHAME** 🔔 🔔 **SHAME** 🔔")

                if shared.consume_upgrade(message.author.id, "anonymous"):
                    send_text = f"📨 *An anonymous source says:* {reply}"

                if shared.consume_upgrade(message.author.id, "spotlight"):
                    send_text = f"@here {send_text}"

                if shared.consume_upgrade(message.author.id, "nuclear"):
                    nuclear_text = await shared.ask_openai(shared._t("Give the single most devastating, savage, all-out roast of Donovan humanly possible. No mercy.", gid), gid)
                    send_text = f"☢️ **NUCLEAR ROAST:** {nuclear_text}"
                    force_tts = True

                sent_msg = await message.channel.send(send_text)
                log_roast()
                log_event("EVENT", f"Roast fired by {message.author.name} in #{message.channel.name} ({message.guild.name if message.guild else 'DM'})")
                asyncio.create_task(shared._apply_roast_stock_impact(gid))

                if shared.tts_enabled or force_tts:
                    await shared.tts_queue.put((message.guild.id, send_text))

                if shared.consume_upgrade(message.author.id, "snitch"):
                    donovan = discord.utils.find(lambda m: m.name.lower() in tgt_usernames, message.guild.members)
                    if donovan:
                        try:
                            await donovan.send(f"📬 Someone wanted you to see this:\n_{reply}_")
                        except Exception:
                            pass

                if shared.consume_upgrade(message.author.id, "hall_of_shame"):
                    try:
                        await sent_msg.pin()
                    except Exception:
                        pass

                if shared.consume_upgrade(message.author.id, "double_roast"):
                    await message.channel.send(f"⚡ **DOUBLE ROAST:** {reply}")

                if shared.consume_upgrade(message.author.id, "triple_roast"):
                    await message.channel.send(reply)
                    await message.channel.send(f"⚡ **TRIPLE ROAST:** {reply}")

                if shared.consume_upgrade(message.author.id, "laugh_track"):
                    await message.channel.send("😂😂😂😂😂😂😂😂😂😂")

                if shared.consume_upgrade(message.author.id, "receipt"):
                    try:
                        async for old_msg in message.channel.history(limit=200):
                            if old_msg.author.name.lower() in tgt_usernames and len(old_msg.content) > 15 and old_msg.id != message.id:
                                await message.channel.send(f"🧾 **RECEIPT:** _{old_msg.author.display_name} once said:_ \"{old_msg.content}\"")
                                break
                    except Exception:
                        pass

                if shared.consume_upgrade(message.author.id, "press_release"):
                    pr = await shared.ask_openai(shared._t(f"Write a short fake formal press release (3-4 sentences) from 'Donovan Industries' announcing his latest embarrassing L. Make it sound official but absurd.", gid), gid)
                    await message.channel.send(f"📰 **PRESS RELEASE:**\n{pr}")

                if shared.consume_upgrade(message.author.id, "breaking_news"):
                    news = await shared.ask_openai(shared._t("Write a fake breaking news alert (1-2 sentences, all caps headline) about Donovan doing something embarrassing or pathetic. Include a fake news network name.", gid), gid)
                    await message.channel.send(f"🚨 **BREAKING NEWS** 🚨\n{news}")

                if shared.consume_upgrade(message.author.id, "intervention"):
                    await message.channel.send(f"@everyone\n\n📢 **FORMAL SERVER INTERVENTION**\n\nThis server has come together to formally address {tgt_name}'s ongoing behaviour. We are concerned. We are united. And we are not impressed.\n\nPlease take this moment to reflect, {tgt_name}.")

                if shared.consume_upgrade(message.author.id, "lore_drop"):
                    lore = await shared.ask_openai(shared._t("Write a short absurd fictional origin story (3-5 sentences) for why Donovan is the way he is. Make it ridiculous, creative, and savage.", gid), gid)
                    await message.channel.send(f"📖 **{tgt_name.upper()} LORE DROP:**\n{lore}")

                if shared.consume_upgrade(message.author.id, "mega_roast"):
                    mega = await shared.ask_openai(shared._t("Give the most savage, creative, brutal roast about Donovan you can. Go all out.", gid), gid)
                    await message.channel.send(f"💥 **MEGA ROAST:** {mega}")

                if shared.consume_upgrade(message.author.id, "scorched_earth"):
                    for i in range(3):
                        roast = await shared.ask_openai(shared._t(f"Give a unique savage roast about Donovan. Make it different each time. Roast #{i+1}.", gid), gid)
                        await message.channel.send(f"🔥 {roast}")

                if shared.consume_upgrade(message.author.id, "exile"):
                    donovan = discord.utils.find(lambda m: m.name.lower() in tgt_usernames, message.guild.members)
                    if donovan:
                        try:
                            until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=60)
                            await donovan.timeout(until, reason="Exile purchased by the people.")
                            await message.channel.send(f"⛔ {tgt_name} has been exiled for 60 seconds. Enjoy the peace.")
                        except Exception:
                            await message.channel.send("⛔ Exile failed — bot needs Moderate Members permission.")

                if shared.consume_upgrade(message.author.id, "eulogy"):
                    eulogy = await shared.ask_openai(shared._t("Write a short dramatic funeral eulogy (3-5 sentences) for Donovan's dignity, as if it has already passed away. Be theatrical, savage, and treat it as a genuine loss to no one.", gid), gid)
                    await message.channel.send(f"⚰️ **EULOGY FOR {tgt_name.upper()}'S DIGNITY:**\n{eulogy}")

                if shared.consume_upgrade(message.author.id, "wanted_poster"):
                    poster = await shared.ask_openai(shared._t("Generate a fake FBI wanted poster description for Donovan. Include: name, aliases, known crimes against the server, last known location, reward amount, and a warning to approach with low expectations.", gid), gid)
                    await message.channel.send(f"🪧 **WANTED** 🪧\n{poster}")

                if shared.consume_upgrade(message.author.id, "therapy_session"):
                    therapy = await shared.ask_openai(shared._t("Roleplay as Donovan's therapist reading case notes aloud. Include diagnosis, presenting complaints, therapist observations, and prognosis. Make it clinical but devastatingly accurate.", gid), gid)
                    await message.channel.send(f"🛋️ **THERAPY SESSION — CASE NOTES:**\n{therapy}")

                if shared.consume_upgrade(message.author.id, "cease_and_desist"):
                    legal = await shared.ask_openai(shared._t("Draft a formal cease and desist letter demanding Donovan immediately stop being himself. Use legal language, cite specific offenses against the server, and threaten consequences. Keep it under 6 sentences.", gid), gid)
                    await message.channel.send(f"⚖️ **CEASE & DESIST:**\n{legal}")

                if shared.consume_upgrade(message.author.id, "linkedin_post"):
                    linkedin = await shared.ask_openai(shared._t("Write a cringe corporate LinkedIn post from Donovan's perspective. He is spinning his latest embarrassing L as a 'growth opportunity' and 'learning experience'. Include hashtags. Make it painfully on-brand for LinkedIn.", gid), gid)
                    await message.channel.send(f"💼 **{tgt_name.upper()}'S LINKEDIN POST:**\n{linkedin}")

                if shared.consume_upgrade(message.author.id, "documentary"):
                    doc = await shared.ask_openai(shared._t("Write a Ken Burns-style documentary narration (4-6 sentences) about a recent Donovan moment. Use a slow, grave, reflective tone. Include dramatic pauses indicated by '...' and treat the subject as historically significant.", gid), gid)
                    await message.channel.send(f"🎬 **DOCUMENTARY NARRATION:**\n{doc}")

                if shared.consume_upgrade(message.author.id, "legacy_mode"):
                    legacy = await shared.ask_openai(shared._t("Compile a devastating highlight reel recap of Donovan's greatest hits — his worst moments, biggest Ls, and most embarrassing behavior. Present it as a formal legacy retrospective. 5-7 sentences.", gid), gid)
                    await message.channel.send(f"🏆 **{tgt_name.upper()}'S LEGACY — HIGHLIGHT REEL:**\n{legacy}")

                if shared.consume_upgrade(message.author.id, "motivational_poster"):
                    poster = await shared.ask_openai(shared._t("Generate a fake motivational poster. Include a short inspirational quote falsely attributed to Donovan, followed by the most embarrassing context that makes the quote hilarious. Format it like a real motivational poster caption.", gid), gid)
                    await message.channel.send(f"🖼️ **MOTIVATIONAL POSTER:**\n{poster}")

                if shared.consume_upgrade(message.author.id, "autopsy_report"):
                    autopsy = await shared.ask_openai(shared._t("Write a clinical medical examiner's autopsy report on the cause of death of Donovan's credibility. Include time of death, cause of death, contributing factors, and examiner's notes. Keep it formal and devastating.", gid), gid)
                    await message.channel.send(f"🔬 **AUTOPSY REPORT — {tgt_name.upper()}'S CREDIBILITY:**\n{autopsy}")

                if shared.consume_upgrade(message.author.id, "wikipedia_page"):
                    wiki = await shared.ask_openai(shared._t("Write a fake Wikipedia-style article about Donovan. Include sections for Early Life, Known For, Controversies, and Legacy. Use encyclopedic tone. The controversies section should be the longest.", gid), gid)
                    await message.channel.send(f"📖 **WIKIPEDIA: {tgt_name.upper()}**\n{wiki}")

                if shared.consume_upgrade(message.author.id, "parole_hearing"):
                    parole = await shared.ask_openai(shared._t("Conduct a formal parole board hearing transcript for Donovan, who is seeking the right to be taken seriously again. Include board questions, his responses, deliberation, and the final verdict — which is always denied. 5-7 sentences.", gid), gid)
                    await message.channel.send(f"🔨 **PAROLE HEARING — VERDICT: DENIED:**\n{parole}")

                if shared.consume_upgrade(message.author.id, "dossier"):
                    dossier = await shared.ask_openai(shared._t("Present a full classified intelligence dossier on Donovan. Include: codename, threat level, known associates, behavioral patterns, noted weaknesses, and current status. Use spy/intelligence report formatting.", gid), gid)
                    await message.channel.send(f"🗂️ **CLASSIFIED DOSSIER: {tgt_name.upper()}**\n{dossier}")

                if shared.consume_upgrade(message.author.id, "state_of_the_union"):
                    sotu = await shared.ask_openai(shared._t("Deliver a presidential State of the Union address formally assessing the ongoing Donovan situation. Address the nation, assess the threat to morale, outline the administration's response plan, and close with hollow optimism. 5-7 sentences.", gid), gid)
                    await message.channel.send(f"🎙️ **STATE OF THE UNION — THE {tgt_name.upper()} SITUATION:**\n{sotu}")

                double_coins = shared.is_double_coin_day()
                coin_reward = 20 if double_coins else 10
                if double_coins:
                    await message.channel.send(f"💰 **2x Roast Coins** — Fuck {tgt_name} Friday/Weekend bonus active!")
                shared.add_coins(message.author.id, coin_reward)
                update_stocks_on_roast(message.author.id)
                bounty_total = claim_bounties(message.author.id)
                if bounty_total > 0:
                    shared.add_coins(message.author.id, bounty_total)
                    await message.channel.send(f"💰 {message.author.mention} collected **{bounty_total} Roast Coins** in active bounties!")

                count = load_count() + 1
                save_count(count)

                if count in shared.MILESTONES:
                    await message.channel.send(
                        f"Congratulations {tgt_name}, you've been insulted {count} times. Keep up the great work!"
                    )

                eco = shared.load_economy()
                milestones_given = eco.get("server_milestones_given", [])
                if count in shared.SERVER_ROAST_MILESTONES and count not in milestones_given:
                    milestones_given.append(count)
                    eco["server_milestones_given"] = milestones_given
                    shared.save_economy(eco)
                    bonus = shared.SERVER_ROAST_MILESTONES[count]
                    for member in message.guild.members:
                        if not member.bot:
                            shared.add_coins(member.id, bonus)
                    log_event("EVENT", f"Server milestone reached: {count} roasts — +{bonus} coins paid to all members")
                    await message.channel.send(
                        f"🎉 **SERVER MILESTONE: {count} total roasts!**\n"
                        f"Everyone gets **+{bonus} Roast Coins** for their dedication to roasting {tgt_name}!"
                    )
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                print(f"[ERROR] on_message crashed: {e}\n{tb}")
                log_event("ERROR", f"on_message crashed in #{getattr(message.channel, 'name', '?')}: {e}")




async def setup(bot):
    await bot.add_cog(RoastCog(bot))
