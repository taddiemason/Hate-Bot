import asyncio
import subprocess
import datetime
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks
import shared
from shared import (
    load_economy, save_economy, get_guild_target, get_guild_config,
    set_guild_config, update_target, is_donovan, _t,
    _post_hate_vote, _tally_hate_vote,
)
from web_admin import log_event

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.weekly_vote_start.start()
        self.weekly_vote_end.start()

    async def cog_unload(self):
        self.weekly_vote_start.cancel()
        self.weekly_vote_end.cancel()

    @tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=ZoneInfo("America/New_York")))
    async def weekly_vote_start(self):
        """Open the vote every Monday at 9 AM ET."""
        if datetime.datetime.now(ZoneInfo("America/New_York")).weekday() != 0:
            return
        await shared._post_hate_vote()



    @tasks.loop(time=datetime.time(hour=20, minute=0, tzinfo=ZoneInfo("America/New_York")))
    async def weekly_vote_end(self):
        """Close the vote every Sunday at 8 PM ET (one hour before weekly recap)."""
        if datetime.datetime.now(ZoneInfo("America/New_York")).weekday() != 6:
            return
        await shared._tally_hate_vote()



    @commands.command(name="startvote")
    @commands.has_permissions(administrator=True)
    async def start_vote(self, ctx):
        """Manually open a hate vote in the current channel."""
        if not ctx.guild:
            await ctx.send("This command must be used in a server.")
            return
        eco = load_economy()
        if eco.get("active_votes", {}).get(str(ctx.guild.id)):
            await ctx.send("⚠️ A vote is already running in this server. Use `!tallyvote` to close it first.")
            return
        await _post_hate_vote(ctx.channel)



    @commands.command(name="tallyvote")
    @commands.has_permissions(administrator=True)
    async def tally_vote(self, ctx):
        """Manually close and tally the current vote."""
        if not ctx.guild:
            await ctx.send("This command must be used in a server.")
            return
        eco = load_economy()
        if not eco.get("active_votes", {}).get(str(ctx.guild.id)):
            await ctx.send("No active vote to tally in this server.")
            return
        await _tally_hate_vote(guild_id=ctx.guild.id)



    @commands.command(name="currenttarget")
    async def current_target(self, ctx):
        """Show who the bot is currently targeting."""
        gid = ctx.guild.id if ctx.guild else None
        tgt = get_guild_target(gid)
        usernames = tgt.get("usernames") or []
        await ctx.send(
            f"🎯 Current target: **{tgt['name']}**\n"
            f"Usernames: `{'`, `'.join(usernames) if usernames else 'none set'}`\n"
            f"Stock ticker: `${tgt['ticker']}`"
        )



    @commands.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def setup_guild(self, ctx):
        """Register this channel as the roast channel for this server."""
        if not ctx.guild:
            await ctx.send("This command must be used in a server.")
            return
        set_guild_config(ctx.guild.id, roast_channel=ctx.channel.id)
        await ctx.send(
            f"✅ **Setup complete!** This channel is now the roast channel for **{ctx.guild.name}**.\n"
            f"Use `!settarget <display_name> <discord_username> [ticker]` to set who gets hated on here."
        )



    @commands.command(name="settarget")
    @commands.has_permissions(administrator=True)
    async def set_target_cmd(self, ctx, name: str = None, username: str = None, ticker: str = None):
        """Set the hate target for this server. Usage: !settarget <name> <username> [ticker]"""
        if not ctx.guild:
            await ctx.send("This command must be used in a server.")
            return
        if not name or not username:
            gid = ctx.guild.id
            tgt = get_guild_target(gid)
            await ctx.send(
                f"Usage: `!settarget <display_name> <discord_username> [ticker]`\n"
                f"Current target: **{tgt['name']}** (`{', '.join(tgt.get('usernames', []))}`) ${tgt['ticker']}"
            )
            return
        set_guild_target(ctx.guild.id, name, [username], ticker)
        final_ticker = (ticker or name.upper()[:8]).upper()
        await ctx.send(
            f"🎯 Target updated for **{ctx.guild.name}**!\n"
            f"Name: **{name}** | Username: `{username}` | Ticker: `${final_ticker}`\n"
            f"The hate machine is now aimed at **{name}**."
        )



    @commands.command(name="togglevoteswitch")
    @commands.has_permissions(administrator=True)
    async def toggle_vote_switch(self, ctx):
        """Toggle whether the hate vote winner replaces the target for this server."""
        if not ctx.guild:
            await ctx.send("This command must be used in a server.")
            return
        cfg = get_guild_config(ctx.guild.id)
        current = cfg.get("vote_changes_target", True)
        new_value = not current
        set_guild_config(ctx.guild.id, vote_changes_target=new_value)
        if new_value:
            await ctx.send(
                "🗳️ **Vote target switching ENABLED** — the winner of each hate vote will become the new roast target."
            )
        else:
            await ctx.send(
                "🗳️ **Vote target switching DISABLED** — votes will still run and show results, but the current target won't change."
            )



    @commands.command(name="TTS")
    async def toggle_tts(self, ctx, state: str = None):

        gid = ctx.guild.id if ctx.guild else None
        tn = get_guild_target(gid)["name"]
        if is_donovan(ctx.author, gid):
            await ctx.send(f"Lmao no. You don't get a say in this, {tn}.")
            return

        if state is None or state.lower() not in ("on", "off"):
            await ctx.send(f"TTS is currently **{'on' if shared.tts_enabled else 'off'}**. Use `!TTS on` or `!TTS off`.")
            return

        shared.tts_enabled = state.lower() == "on"
        await ctx.send(f"TTS roasts turned **{state.lower()}**.")



    @commands.command(name="update")
    @commands.has_permissions(administrator=True)
    async def update_bot(self, ctx):
        import subprocess
        await ctx.send("⬇️ Pulling latest changes...")
        result = subprocess.run(["git", "pull", "origin", "Main"], capture_output=True, text=True)
        output = result.stdout.strip() or result.stderr.strip() or "No output."
        await ctx.send(f"```{output}```")
        if result.returncode != 0:
            await ctx.send("❌ Git pull failed. Not restarting.")
            return
        await ctx.send("✅ Update complete. Restarting...")
        subprocess.run(["pkill", "-f", "bot.py"])




    @commands.command(name="commands")
    async def commands_list(self, ctx):
        gid = ctx.guild.id if ctx.guild else None
        tgt = get_guild_target(gid)
        tn = tgt["name"]
        ticker = tgt["ticker"]

        await ctx.send(
            f"**📋 {tn} Hate Bot — Commands (1/3)**\n\n"
            f"**`@{tn} Hate Bot`** — Roasts {tn}. Ask it a question for a smart response.\n"
            f"**`!Trial <reason>`** — Puts {tn} on trial. Server votes guilty/not guilty for 60 seconds.\n"
            f"**`!Guesswhosaidit`** — 3 round game. Guess if the quote was {tn} or someone else.\n"
            f"**`!TTS on/off`** — Toggles voice channel roasts. ({tn} cannot use this.)\n\n"
            "**💰 Economy**\n"
            "**`!balance`** — Check your Roast Coin balance.\n"
            "**`!leaderboard`** — Top 5 coin holders.\n"
            "**`!shop`** — View upgrades for sale.\n"
            "**`!buy <item>`** — Purchase an upgrade (goes to inventory).\n"
            "**`!inventory`** — View your owned and armed items.\n"
            "**`!use <item>`** — Arm an item from your inventory (fires on next @mention).\n"
            "**`!bounty <amount> <description>`** — Post a bounty paid to whoever triggers the next roast.\n"
            "**`!bounties`** — View active bounties.\n"
            f"**`!insurance <minutes>`** — {tn} only: buy temporary (useless) protection.\n"
            "**`!give @user <amount>`** — Transfer coins to another member.\n"
            "**`!blackmarket`** — View peer-to-peer upgrade listings.\n"
            "**`!listitem <item> <price>`** — List an owned upgrade for sale.\n"
            "**`!buyitem <id>`** — Buy an upgrade from the black market.\n"
            "**`!settarget <name> <username> [ticker]`** — (Admin) Set who the bot hates on this server.\n"
            "**`!setup`** — (Admin) Register this channel as the roast channel for this server."
        )
        await ctx.send(
            f"**📋 {tn} Hate Bot — Commands (2/3)**\n\n"
            "**🎮 Minigames & Rewards**\n"
            "**`!daily`** — Daily check-in. Streak builds a multiplier (day 7 = 2x, day 30 = 5x).\n"
            "**`!flip <amount> heads/tails`** — Coinflip gamble.\n"
            "**`!slots <amount>`** — Slot machine. Match symbols for big payouts.\n"
            "**`!trivia`** — First to answer wins 50 coins.\n"
            "**`!sportstrivia`** — 5 rounds of AI-generated NHL/NFL/NBA trivia. 20 coins per correct answer.\n"
            "**`!guessroast`** — Roast posted with name blanked, guess who it's about.\n"
            "**`!dice @user <amount>`** — Challenge someone to a dice duel. Roll 1-100, highest wins the pot. Ties re-roll.\n"
            "**`!highlow <amount>`** — Guess higher or lower, chain correct answers for a multiplier.\n"
            "**`!blackjack [bet]`** — Multiplayer blackjack vs the dealer. Bet defaults to 10 coins. Others can join before the round starts.\n"
            "**`!lottery <amount>`** — Buy lottery tickets (10 coins each). Drawn every Sunday at 9 PM EST."
        )
        await ctx.send(
            f"**📋 {tn} Hate Bot — Commands (3/3)**\n\n"
            "**📈 Stock Market**\n"
            f"**`!stockmarket`** — View current prices for all stocks (${ticker}, $RUST, $BIGMAC, $TORTA, $TRUMP, $COCAINE).\n"
            "**`!stocktrend <TICKER>`** — Sparkline chart, 30min/2hr/8hr performance, momentum indicator, and range for any stock.\n"
            "**`!stockalert <TICKER> <price>`** — Get pinged when a stock crosses your target price.\n"
            "**`!stockhelp`** — 3-page guide to stocks, options, and futures.\n"
            "**`!buystock <TICKER> <shares>`** — Buy shares at market price.\n"
            "**`!sellstock <TICKER> <shares>`** — Sell shares you own.\n"
            "**`!short <TICKER> <shares>`** — Open a short position (profit if price drops).\n"
            "**`!cover <TICKER> <shares>`** — Close a short position.\n"
            "**`!portfolio [@user]`** — View your (or someone else's) open positions and P&L.\n"
            "**`!limitorder <buy|sell|short|cover> <TICKER> <shares> <price>`** — Place a limit order that fills automatically.\n"
            "**`!orders`** — View your pending limit orders.\n"
            "**`!cancellimit <id>`** — Cancel a pending limit order.\n"
            "**`!futures <long|short> <TICKER> <contracts>`** — Open a leveraged 7-day futures contract (20% margin).\n"
            "**`!closefutures <id>`** — Close a futures contract early.\n"
            "**`!myfutures`** — View your open futures contracts.\n"
            "**`!buyoption <call|put> <TICKER> <contracts> <strike> [days]`** — Buy a call or put option.\n"
            "**`!exercise <id>`** — Exercise an option if it's in the money.\n"
            "**`!myoptions`** — View your open options.\n\n"
            "**`!commands`** — Shows this list."
        )


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
