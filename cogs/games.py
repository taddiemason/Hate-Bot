import asyncio
import random
import datetime
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands
import shared
from shared import (
    load_economy, save_economy, add_coins, spend_coins, get_guild_target,
    is_donovan, record_trivia_win, get_portfolio_value, init_market, init_derivatives,
    _t, new_deck, card_str, hand_str, hand_value, is_blackjack,
    generate_trivia_question, generate_sports_question, generate_buffalo_question,
    generate_buffalo_ny_question, judge_trivia_answer, judge_sports_answer,
    _trivia_quick_match, ask_openai,
    trivia_recent, trivia_recent_answers, trivia_recent_cats,
)

class GamesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="trivia")
    async def trivia(self, ctx):
        if shared.trivia_active:
            await ctx.send("A trivia question is already active!")
            return
        shared.trivia_active = True
        try:
            recent_q = trivia_recent.get(ctx.channel.id, [])
            recent_ans = trivia_recent_answers.get(ctx.channel.id, [])
            recent_cats = trivia_recent_cats.get(ctx.channel.id, [])
            question, answer, category = await generate_trivia_question(
                used_topics=recent_q or None,
                used_categories=recent_cats or None,
                used_answers=recent_ans or None,
            )
            trivia_recent[ctx.channel.id] = (recent_q + [question])[-20:]
            trivia_recent_answers[ctx.channel.id] = (recent_ans + [answer])[-20:]
            trivia_recent_cats[ctx.channel.id] = (recent_cats + [category])[-8:]
            await ctx.send(
                f"🧠 **TRIVIA** _{category.title()}_ — First to answer wins **50 coins!**\n\n"
                f"_{question}_\n\nYou have 30 seconds!"
            )
            def check(m):
                return m.channel == ctx.channel and not m.author.bot and not m.content.startswith("!") and len(m.content.strip()) > 1

            winner = None
            deadline = asyncio.get_running_loop().time() + 30
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    msg = await self.bot.wait_for("message", check=check, timeout=remaining)
                    user_answer = msg.content.strip()
                    if _trivia_quick_match(answer, user_answer):
                        correct = True
                    elif len(user_answer.split()) > 5:
                        correct = answer.lower() in user_answer.lower()
                    else:
                        correct = await judge_trivia_answer(question, answer, user_answer)
                    if correct:
                        winner = msg
                        break
                except asyncio.TimeoutError:
                    break

            if winner:
                add_coins(winner.author.id, 50)
                record_trivia_win(winner.author.id)
                await ctx.send(f"✅ {winner.author.mention} got it! The answer was **{answer.title()}**. **+50 coins!**")
            else:
                await ctx.send(f"⏱️ Time's up! The answer was **{answer.title()}**.")
        finally:
            shared.trivia_active = False



    @commands.command(name="guessroast")
    async def guess_roast(self, ctx):
        if shared.guessroast_active:
            await ctx.send("A guess the roast game is already active!")
            return
        gid = ctx.guild.id if ctx.guild else None
        tn = get_guild_target(gid)["name"]
        shared.guessroast_active = True
        tmpl = random.choice(shared._GENERAL_ROASTS_TMPL + shared._RUST_ROASTS_TMPL + shared._WOW_ROASTS_TMPL)
        roast = _t(tmpl, gid)
        blanked = roast.replace(tn, "**[???]**").replace(tn.lower(), "**[???]**")
        await ctx.send(f"🎭 **GUESS WHO THIS ROAST IS AIMED AT:**\n\n_{blanked}_\n\nFirst to type the name wins **30 coins!** (20 seconds)")
        await asyncio.sleep(20)
        if shared.guessroast_active:
            shared.guessroast_active = False
            await ctx.send(f"⏱️ Time's up! It was **{tn}**. Obviously.")



    @commands.command(name="highlow")
    async def highlow(self, ctx, amount: int = None):
        if not amount or amount <= 0:
            await ctx.send("Usage: `!highlow <amount>`")
            return
        if ctx.author.id in shared.highlow_games:
            await ctx.send("You already have a game in progress! Type `higher`, `lower`, or `cashout`.")
            return
        if not spend_coins(ctx.author.id, amount):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins. You have **{bal}**.")
            return
        number = random.randint(1, 100)
        shared.highlow_games[ctx.author.id] = {"number": number, "bet": amount, "multiplier": 1.0, "channel_id": ctx.channel.id}
        await ctx.send(
            f"🎯 The number is **{number}**.\n"
            f"Will the next be `higher` or `lower`? Type your answer!\n"
            f"Type `cashout` to take your winnings at any time."
        )



    @commands.command(name="blackjack")
    async def blackjack(self, ctx, amount: int = 10):
        if amount <= 0:
            amount = 10

        channel_id = ctx.channel.id

        # Join an existing waiting game
        if channel_id in shared.blackjack_games and shared.blackjack_games[channel_id]["state"] == "waiting":
            game = shared.blackjack_games[channel_id]
            if any(p["user_id"] == ctx.author.id for p in game["players"]):
                await ctx.send("You're already at this table.")
                return
            if not spend_coins(ctx.author.id, amount):
                bal = load_economy()["balances"].get(str(ctx.author.id), 0)
                await ctx.send(f"Not enough coins. You have **{bal}**.")
                return
            game["players"].append({
                "user_id": ctx.author.id, "name": ctx.author.display_name,
                "bet": amount, "hand": [], "stood": False, "busted": False,
            })
            await ctx.send(f"✅ **{ctx.author.display_name}** joined for **{amount} coins**!")
            return

        # Block if a round is mid-game
        if channel_id in shared.blackjack_games:
            await ctx.send("A blackjack game is already running. Wait for the next round.")
            return

        if not spend_coins(ctx.author.id, amount):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins. You have **{bal}**.")
            return

        shared.blackjack_games[channel_id] = {
            "state": "waiting",
            "players": [{"user_id": ctx.author.id, "name": ctx.author.display_name,
                         "bet": amount, "hand": [], "stood": False, "busted": False}],
            "dealer_hand": [],
            "deck": [],
        }

        await ctx.send(
            f"🃏 **BLACKJACK** — **{ctx.author.display_name}** opened a table for **{amount} coins**!\n"
            f"Others: `!blackjack <bet>` to join. Starting in **20 seconds**..."
        )
        await asyncio.sleep(20)

        if channel_id not in shared.blackjack_games:
            return

        game = shared.blackjack_games[channel_id]
        game["state"] = "playing"

        deck = new_deck()
        game["deck"] = deck
        for p in game["players"]:
            p["hand"] = [deck.pop(), deck.pop()]
        game["dealer_hand"] = [deck.pop(), deck.pop()]

        # Show initial state
        lines = ["🃏 **BLACKJACK — CARDS DEALT**\n",
                 f"**Dealer:** {hand_str(game['dealer_hand'], hide_second=True)}\n"]
        for p in game["players"]:
            val = hand_value(p["hand"])
            bj = " — 🃏 **BLACKJACK!**" if is_blackjack(p["hand"]) else f" ({val})"
            lines.append(f"**{p['name']}:** {hand_str(p['hand'])}{bj}")
        await ctx.send("\n".join(lines))

        # Player turns
        for player in game["players"]:
            if is_blackjack(player["hand"]):
                player["stood"] = True
                await ctx.send(f"🃏 **{player['name']}** has Blackjack — auto-stand!")
                continue

            await ctx.send(f"➡️ **{player['name']}'s turn** — `hit` or `stand` (30s)")

            def check(m, pid=player["user_id"]):
                return m.author.id == pid and m.channel.id == channel_id and m.content.lower() in ("hit", "stand")

            while not player["stood"] and not player["busted"]:
                try:
                    msg = await self.bot.wait_for("message", check=check, timeout=30)
                    if msg.content.lower() == "stand":
                        player["stood"] = True
                        await ctx.send(f"✋ **{player['name']}** stands at **{hand_value(player['hand'])}**.")
                    else:
                        card = game["deck"].pop()
                        player["hand"].append(card)
                        val = hand_value(player["hand"])
                        if val > 21:
                            player["busted"] = True
                            await ctx.send(f"💥 **{player['name']}** hits {card_str(card)} → **{val} — BUST!**")
                        elif val == 21:
                            player["stood"] = True
                            await ctx.send(f"🎯 **{player['name']}** hits {card_str(card)} → **21!** Auto-stand.")
                        else:
                            await ctx.send(f"🃏 **{player['name']}** hits {card_str(card)} → **{val}**. Hit or stand?")
                except asyncio.TimeoutError:
                    player["stood"] = True
                    await ctx.send(f"⏱️ **{player['name']}** timed out — auto-stand at **{hand_value(player['hand'])}**.")

        # Dealer plays (only if someone didn't bust)
        dealer_val = hand_value(game["dealer_hand"])
        await ctx.send(f"🤖 **Dealer reveals:** {hand_str(game['dealer_hand'])} ({dealer_val})")

        active = [p for p in game["players"] if not p["busted"]]
        if active:
            while dealer_val < 17:
                card = game["deck"].pop()
                game["dealer_hand"].append(card)
                dealer_val = hand_value(game["dealer_hand"])
                await asyncio.sleep(1)
                await ctx.send(f"🤖 Dealer hits {card_str(card)} → **{dealer_val}**")

        dealer_bust = dealer_val > 21
        if dealer_bust:
            await ctx.send(f"💥 **Dealer busts at {dealer_val}!**")

        # Results
        result_lines = ["🃏 **BLACKJACK — RESULTS**\n"]
        for p in game["players"]:
            pval = hand_value(p["hand"])
            if p["busted"]:
                result_lines.append(f"❌ **{p['name']}** — Bust — lost **{p['bet']} coins**")
            elif is_blackjack(p["hand"]) and not is_blackjack(game["dealer_hand"]):
                payout = int(p["bet"] * 2.5)
                add_coins(p["user_id"], payout)
                result_lines.append(f"🃏 **{p['name']}** — Blackjack! — won **{payout - p['bet']} coins**")
            elif is_blackjack(p["hand"]) and is_blackjack(game["dealer_hand"]):
                add_coins(p["user_id"], p["bet"])
                result_lines.append(f"🤝 **{p['name']}** — Blackjack push — bet returned")
            elif dealer_bust or pval > dealer_val:
                add_coins(p["user_id"], p["bet"] * 2)
                result_lines.append(f"✅ **{p['name']}** — {pval} vs {dealer_val} — won **{p['bet']} coins**")
            elif pval == dealer_val:
                add_coins(p["user_id"], p["bet"])
                result_lines.append(f"🤝 **{p['name']}** — {pval} push — bet returned")
            else:
                result_lines.append(f"❌ **{p['name']}** — {pval} vs {dealer_val} — lost **{p['bet']} coins**")

        del shared.blackjack_games[channel_id]
        await ctx.send("\n".join(result_lines))



    @commands.command(name="dice")
    async def dice_duel(self, ctx, opponent: discord.Member = None, amount: int = None):
        if not opponent or not amount or amount <= 0:
            await ctx.send("Usage: `!dice @user <amount>`")
            return
        if opponent.id == ctx.author.id:
            await ctx.send("You can't challenge yourself.")
            return
        if opponent.bot:
            await ctx.send("You can't challenge a bot. Coward.")
            return

        if not spend_coins(ctx.author.id, amount):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins. You have **{bal}**.")
            return

        msg = await ctx.send(
            f"🎲 **DICE DUEL**\n\n"
            f"**{ctx.author.display_name}** challenges **{opponent.mention}** for **{amount} coins** a side!\n\n"
            f"React ✅ to accept or ❌ to decline. (30 seconds)"
        )
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        def check(reaction, user):
            return user.id == opponent.id and str(reaction.emoji) in ("✅", "❌") and reaction.message.id == msg.id

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", check=check, timeout=30)
        except asyncio.TimeoutError:
            add_coins(ctx.author.id, amount)
            await ctx.send(f"⏱️ **{opponent.display_name}** never showed up. {ctx.author.mention} refunded.")
            return

        if str(reaction.emoji) == "❌":
            add_coins(ctx.author.id, amount)
            await ctx.send(f"❌ **{opponent.display_name}** backed out. {ctx.author.mention} refunded.")
            return

        if not spend_coins(opponent.id, amount):
            add_coins(ctx.author.id, amount)
            bal = load_economy()["balances"].get(str(opponent.id), 0)
            await ctx.send(f"**{opponent.display_name}** accepted but only has **{bal} coins**. Challenge cancelled, {ctx.author.mention} refunded.")
            return

        pot = amount * 2
        await ctx.send(f"✅ **{opponent.display_name}** accepted! Pot: **{pot} coins**. Rolling...")

        while True:
            await asyncio.sleep(1)
            a_total = random.randint(1, 100)
            b_total = random.randint(1, 100)

            await ctx.send(
                f"🎲 **{ctx.author.display_name}:** **{a_total}**\n"
                f"🎲 **{opponent.display_name}:** **{b_total}**"
            )

            if a_total > b_total:
                add_coins(ctx.author.id, pot)
                await ctx.send(f"🏆 **{ctx.author.display_name}** wins and takes **{pot} coins!**")
                break
            elif b_total > a_total:
                add_coins(opponent.id, pot)
                await ctx.send(f"🏆 **{opponent.display_name}** wins and takes **{pot} coins!**")
                break
            else:
                await ctx.send("🤝 **TIE — rolling again!**")



    @commands.command(name="sportstrivia")
    async def sports_trivia(self, ctx):
        channel_id = ctx.channel.id
        if shared.sports_trivia_active.get(channel_id):
            await ctx.send("A sports trivia game is already running in this channel!")
            return

        shared.sports_trivia_active[channel_id] = True
        scores = {}

        try:
            await ctx.send("🏈🏒🏀 **SPORTS TRIVIA** — 5 rounds, **20 coins** per correct answer! First to answer wins each round!")
            await asyncio.sleep(2)

            sport_rotation = ["NHL", "NFL", "NBA", "NHL", "NFL"]
            used_topics = []
            for round_num, sport in enumerate(sport_rotation, 1):
                question, answer = await generate_sports_question(sport, used_topics)
                used_topics.append(f"{answer} (from: {question[:60]})")

                await ctx.send(f"**Round {round_num}/5**\n\n_{question}_\n\n⏱️ 30 seconds!")

                def check(m):
                    return m.channel.id == channel_id and not m.author.bot and not m.content.startswith("!") and len(m.content.strip()) > 1

                winner = None
                deadline = asyncio.get_running_loop().time() + 30

                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        msg = await self.bot.wait_for("message", check=check, timeout=remaining)
                        user_answer = msg.content.strip()
                        # Skip slow AI judge for obvious chat messages to avoid blocking the loop
                        if len(user_answer.split()) > 5:
                            correct = answer.lower() in user_answer.lower()
                        else:
                            correct = await judge_sports_answer(question, answer, user_answer)
                        if correct:
                            winner = msg.author
                            break
                    except asyncio.TimeoutError:
                        break

                if winner:
                    add_coins(winner.id, 20)
                    record_trivia_win(winner.id)
                    scores[winner.id] = scores.get(winner.id, 0) + 20
                    await ctx.send(f"✅ **{winner.display_name}** got it! The answer was **{answer}** — **+20 coins!**")
                else:
                    await ctx.send(f"⏱️ Time's up! The answer was **{answer}**.")

                if round_num < 5:
                    await asyncio.sleep(3)

            if scores:
                top = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                board = "\n".join(
                    f"{ctx.guild.get_member(uid).display_name if ctx.guild.get_member(uid) else 'Unknown'}: {c} coins"
                    for uid, c in top
                )
                mvp = ctx.guild.get_member(top[0][0])
                mvp_name = mvp.display_name if mvp else "Unknown"
                await ctx.send(f"🏆 **SPORTS TRIVIA OVER!**\n\n{board}\n\nMVP: **{mvp_name}** with **{top[0][1]} coins** earned!")
            else:
                await ctx.send("🏆 **SPORTS TRIVIA OVER!** Nobody scored a single point. Embarrassing.")

        except Exception as e:
            print(f"[ERROR] Sports trivia crashed: {e}")
            gid = ctx.guild.id if ctx.guild else None
            tn = get_guild_target(gid)["name"]
            await ctx.send(f"Sports trivia crashed. Blame {tn}.")
        finally:
            shared.sports_trivia_active[channel_id] = False



    @commands.command(name="buffalotrivia")
    async def buffalo_trivia(self, ctx):
        channel_id = ctx.channel.id
        if shared.sports_trivia_active.get(channel_id):
            await ctx.send("A trivia game is already running in this channel!")
            return

        shared.sports_trivia_active[channel_id] = True
        scores = {}

        try:
            await ctx.send(
                "🦬🏈🏒 **BUFFALO SPORTS TRIVIA** — 5 rounds, **25 coins** per correct answer!\n"
                "Bills. Sabres. Heartbreak. Glory. Let's go Buffalo! 🔵🔴"
            )
            await asyncio.sleep(2)

            used_topics = []
            city_round = random.randint(1, 5)
            for round_num in range(1, 6):
                if round_num == city_round:
                    question, answer = await generate_buffalo_ny_question(used_topics)
                    round_label = f"**Round {round_num}/5 — 🌆 Buffalo City Trivia**"
                else:
                    question, answer = await generate_buffalo_question(used_topics)
                    round_label = f"**Round {round_num}/5**"
                used_topics.append(f"{answer} (from: {question[:60]})")

                await ctx.send(f"{round_label}\n\n_{question}_\n\n⏱️ 30 seconds!")

                def check(m):
                    return m.channel.id == channel_id and not m.author.bot and not m.content.startswith("!") and len(m.content.strip()) > 1

                winner = None
                deadline = asyncio.get_running_loop().time() + 30

                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        msg = await self.bot.wait_for("message", check=check, timeout=remaining)
                        user_answer = msg.content.strip()
                        if len(user_answer.split()) > 6:
                            correct = answer.lower() in user_answer.lower()
                        else:
                            correct = await judge_sports_answer(question, answer, user_answer)
                        if correct:
                            winner = msg.author
                            break
                    except asyncio.TimeoutError:
                        break

                if winner:
                    add_coins(winner.id, 25)
                    record_trivia_win(winner.id)
                    scores[winner.id] = scores.get(winner.id, 0) + 25
                    await ctx.send(f"✅ **{winner.display_name}** got it! The answer was **{answer}** — **+25 coins!**")
                else:
                    await ctx.send(f"⏱️ Time's up! The answer was **{answer}**.")

                if round_num < 5:
                    await asyncio.sleep(3)

            if scores:
                top = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                board = "\n".join(
                    f"{ctx.guild.get_member(uid).display_name if ctx.guild.get_member(uid) else 'Unknown'}: {c} coins"
                    for uid, c in top
                )
                mvp = ctx.guild.get_member(top[0][0])
                mvp_name = mvp.display_name if mvp else "Unknown"
                await ctx.send(
                    f"🦬 **BUFFALO TRIVIA OVER!**\n\n{board}\n\n"
                    f"MVP: **{mvp_name}** with **{top[0][1]} coins** earned! Let's gooo Buffalo!"
                )
            else:
                await ctx.send("🦬 **BUFFALO TRIVIA OVER!** Nobody scored. You all failed this city.")

        except Exception as e:
            print(f"[ERROR] Buffalo trivia crashed: {e}")
            await ctx.send("Buffalo trivia crashed. Fitting, really.")
        finally:
            shared.sports_trivia_active[channel_id] = False



    @commands.command(name="lottery")
    async def lottery(self, ctx, amount: int = None):
        if not amount or amount < 10:
            eco = load_economy()
            pot = eco.get("lottery_pot", 500)
            tickets = eco.get("lottery_tickets", {}).get(str(ctx.author.id), 0)
            await ctx.send(f"🎟️ **Weekly Lottery** — 10 coins per ticket\nCurrent pot: **{pot} coins** | Your tickets: **{tickets}**\nUsage: `!lottery <amount>` (must be multiple of 10)")
            return
        tickets = amount // 10
        cost = tickets * 10
        if not spend_coins(ctx.author.id, cost):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins. You have **{bal}**.")
            return
        eco = load_economy()
        uid = str(ctx.author.id)
        eco.setdefault("lottery_tickets", {})[uid] = eco.get("lottery_tickets", {}).get(uid, 0) + tickets
        eco["lottery_pot"] = eco.get("lottery_pot", 0) + cost
        save_economy(eco)
        await ctx.send(f"🎟️ Bought **{tickets} ticket(s)** for **{cost} coins**! Pot is now **{eco['lottery_pot']} coins**. Drawing Sunday at 9 PM EST!")



    @commands.command(name="Guesswhosaidit")
    async def guess_who(self, ctx):

        gid = ctx.guild.id if ctx.guild else None
        tn = get_guild_target(gid)["name"]

        if is_donovan(ctx.author, gid):
            await ctx.send(f"You're not allowed to play this game {tn}. You might recognise yourself.")
            return

        if shared.guess_game_active:
            await ctx.send("A game is already running. One humiliation at a time.")
            return

        shared.guess_game_active = True
        scores = {}
        quotes_pool = [{"text": _t(q["text"], gid), "is_donovan": q["is_donovan"]} for q in shared._QUOTES_TMPL]
        pool = random.sample(quotes_pool, min(3, len(quotes_pool)))

        try:
            await ctx.send(f"🎮 **GUESS WHO SAID IT** 🎮\n3 rounds, 30 seconds each.\nReact 🇩 if you think **{tn}** said it, 🤷 if **someone else** did.")

            for round_num, quote in enumerate(pool, 1):
                msg = await ctx.send(
                    f"**Round {round_num}/3**\n\n"
                    f'*"{quote["text"]}"*\n\n'
                    f"🇩 = {tn}    🤷 = Not {tn}"
                )
                await msg.add_reaction("🇩")
                await msg.add_reaction("🤷")

                await asyncio.sleep(30)

                msg = await ctx.channel.fetch_message(msg.id)
                donovan_voters = set()
                not_donovan_voters = set()

                for reaction in msg.reactions:
                    async for user in reaction.users():
                        if user.bot:
                            continue
                        if str(reaction.emoji) == "🇩":
                            donovan_voters.add(user.id)
                        elif str(reaction.emoji) == "🤷":
                            not_donovan_voters.add(user.id)

                correct_voters = donovan_voters if quote["is_donovan"] else not_donovan_voters
                for uid in correct_voters:
                    scores[uid] = scores.get(uid, 0) + 1

                answer = f"**{tn.upper()}** said that. Shocking." if quote["is_donovan"] else f"A normal human said that. {tn} could never."
                correct_count = len(correct_voters)
                await ctx.send(f"⏱️ Time's up! {answer}\n✅ {correct_count} people got it right.")

            if scores:
                sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                winner_id, top_score = sorted_scores[0]
                winner = ctx.guild.get_member(winner_id)
                winner_name = winner.display_name if winner else "Someone"
                board = "\n".join(
                    f"{ctx.guild.get_member(uid).display_name if ctx.guild.get_member(uid) else 'Unknown'}: {s}/3"
                    for uid, s in sorted_scores
                )
                await ctx.send(
                    f"🏆 **GAME OVER**\n\n{board}\n\n"
                    f"Winner: **{winner_name}** with {top_score}/3 — the only one here who truly understands how big of a loser {tn} is."
                )
            else:
                await ctx.send(f"🏆 **GAME OVER**\nNobody scored a single point. {tn} would fit right in.")

        except Exception as e:
            print(f"[ERROR] Guess game failed: {e}")
            await ctx.send(f"The game crashed. Blame {tn}.")
        finally:
            shared.guess_game_active = False



    @commands.command(name="Trial")
    async def trial(self, ctx, *, reason: str = None):

        gid = ctx.guild.id if ctx.guild else None
        tn = get_guild_target(gid)["name"]

        if is_donovan(ctx.author, gid):
            await ctx.send(f"You can't put yourself on trial {tn}. Though honestly you should.")
            return

        if shared.trial_active:
            await ctx.send(f"A trial is already in progress. {tn} can only be humiliated one case at a time.")
            return

        if not reason:
            await ctx.send("You need to provide a charge. Usage: `!Trial <reason>`")
            return

        shared.trial_active = True
        try:
            msg = await ctx.send(
                f"⚖️ **THE PEOPLE VS. {tn.upper()}** ⚖️\n\n"
                f"**Charge:** {reason}\n\n"
                f"Cast your vote:\n"
                f"👨‍⚖️ = GUILTY\n"
                f"🆓 = NOT GUILTY\n\n"
                f"_Voting closes in 60 seconds._"
            )
            await msg.add_reaction("👨‍⚖️")
            await msg.add_reaction("🆓")

            await asyncio.sleep(60)

            msg = await ctx.channel.fetch_message(msg.id)
            guilty = 0
            not_guilty = 0
            for reaction in msg.reactions:
                if str(reaction.emoji) == "👨‍⚖️":
                    guilty = reaction.count - 1
                elif str(reaction.emoji) == "🆓":
                    not_guilty = reaction.count - 1

            if guilty >= not_guilty:
                sentence = random.choice(shared.SENTENCES)
                await ctx.send(
                    f"⚖️ **VERDICT: GUILTY** ⚖️\n"
                    f"_{guilty} guilty — {not_guilty} not guilty_\n\n"
                    f"**Sentence:** {sentence}"
                )
            else:
                await ctx.send(
                    f"⚖️ **VERDICT: NOT GUILTY** ⚖️\n"
                    f"_{not_guilty} not guilty — {guilty} guilty_\n\n"
                    f"{tn} walks free today. Don't worry, they'll embarrass themselves again soon enough."
                )
        except Exception as e:
            print(f"[ERROR] Trial failed: {e}")
            await ctx.send(f"The trial collapsed due to {tn}'s overwhelming incompetence. Court dismissed.")
        finally:
            shared.trial_active = False




async def setup(bot):
    await bot.add_cog(GamesCog(bot))
