import os
import asyncio
import datetime
import math
import traceback
import aiohttp.web
from dotenv import load_dotenv

load_dotenv()

from database import init_db
import discord
from discord.ext import commands
from web_admin import create_web_app, log_event
import shared

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

EXTENSIONS = ("cogs.roast", "cogs.economy", "cogs.games", "cogs.stocks", "cogs.admin")


class HateBot(commands.Bot):
    async def setup_hook(self):
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
            except commands.ExtensionAlreadyLoaded:
                await self.reload_extension(ext)


_admin_server_started = False
_tts_worker_started = False
_loop_exc_last: dict[str, float] = {}
_LOOP_EXC_COOLDOWN = 5.0  # seconds between identical loop exception log entries

_RESTART_DELAY = 30  # seconds between crash restarts
_WATCHDOG_INTERVAL = 60  # seconds between connection health checks
_WATCHDOG_LATENCY_LIMIT = 30.0  # seconds; force reconnect above this


def _tail(text: str, limit: int = 4000) -> str:
    """Keep log payloads compact enough for the admin log sink."""
    return text if len(text) <= limit else f"...{text[-limit:]}"


async def _start_admin_server(bot):
    global _admin_server_started
    app = create_web_app(
        shared.load_economy, shared.save_economy, shared.get_shop_rotation,
        shared.SHOP_ITEMS, shared.MARKET_STOCKS, bot, shared.tts_queue,
    )
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    for port in range(47832, 47842):
        try:
            site = aiohttp.web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            _admin_server_started = True
            print(f"Admin dashboard running at http://0.0.0.0:{port}")
            return
        except OSError:
            continue
    print("Admin dashboard failed to start: no available port in range 47832-47841")


async def _connection_watchdog(bot):
    """Detect zombie connections and force a clean reconnect when needed.

    Discord sessions can silently stall after a resume: the gateway appears
    alive but heartbeat ACKs stop arriving, causing bot.latency to become nan.
    Closing the bot here lets the outer restart loop bring it back cleanly.
    """
    try:
        await asyncio.sleep(30)  # let the connection stabilize after on_ready
        while not bot.is_closed():
            await asyncio.sleep(_WATCHDOG_INTERVAL)
            if bot.is_closed() or not bot.is_ready():
                continue
            latency = bot.latency
            if math.isnan(latency) or latency > _WATCHDOG_LATENCY_LIMIT:
                log_event(
                    "WARN",
                    f"Watchdog: unhealthy connection (latency={latency!r}s) — forcing reconnect",
                )
                try:
                    await bot.close()
                except Exception as e:
                    log_event("WARN", f"Watchdog: error during forced close: {e!r}")
                return
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log_event("ERROR", f"Watchdog crashed: {e!r}")


def _register_events(bot):
    @bot.event
    async def on_ready():
        global _admin_server_started, _tts_worker_started
        init_db()
        shared.set_bot(bot)
        bot._online_since = datetime.datetime.now(datetime.timezone.utc)
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
        log_event("INFO", f"Bot online: {bot.user} (ID: {bot.user.id}) — {len(bot.guilds)} guild(s)")

        eco = shared.load_economy()
        saved = eco.get("active_target")
        if saved:
            shared.update_target(saved["name"], saved.get("usernames", []), saved.get("ticker"), save=False)
            log_event("INFO", f"Target restored: {shared.TARGET_NAME} / {shared.TARGET_USERNAMES} / ${shared.TARGET_STOCK_TICKER}")

        if not _tts_worker_started:
            asyncio.create_task(shared.tts_worker())
            _tts_worker_started = True
        if not _admin_server_started:
            asyncio.create_task(_start_admin_server(bot))

        # (Re)start watchdog on every on_ready so it always reflects the live connection.
        prev = getattr(bot, "_watchdog_task", None)
        if prev and not prev.done():
            prev.cancel()
        bot._watchdog_task = asyncio.create_task(_connection_watchdog(bot))

    @bot.event
    async def on_resumed():
        latency = bot.latency
        log_event("INFO", f"Bot reconnected to Discord (session resumed, latency={latency:.3f}s)")

    @bot.event
    async def on_disconnect():
        log_event("WARN", "Bot disconnected from Discord (waiting for automatic reconnect)")

    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.CheckFailure):
            try:
                await ctx.send("❌ You don't have permission to use this command.")
            except discord.HTTPException:
                pass
            return
        print(f"[ERROR] Command '{ctx.command}' raised: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        log_event("ERROR", f"Command '{ctx.command}' in #{getattr(ctx.channel, 'name', '?')} raised: {error}")
        try:
            await ctx.send(f"❌ Command error: `{error}`")
        except discord.HTTPException:
            pass

    @bot.event
    async def on_error(event: str, *args, **kwargs):
        tb = traceback.format_exc()
        print(f"[ERROR] Unhandled exception in event '{event}':\n{tb}")
        log_event("ERROR", f"Unhandled exception in event '{event}':\n{_tail(tb)}")

    @bot.event
    async def on_shard_disconnect(shard_id):
        log_event("WARN", f"Shard {shard_id} disconnected (waiting for automatic reconnect)")

    @bot.event
    async def on_shard_resumed(shard_id):
        log_event("INFO", f"Shard {shard_id} resumed")


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log_event("ERROR", "DISCORD_TOKEN is not set; shutting down")
        return

    loop = asyncio.get_running_loop()

    def _loop_exception_handler(loop, context):
        import time
        msg = context.get("message", "Unhandled asyncio loop exception")
        exc = context.get("exception")
        tb = ""
        if exc:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        elif context.get("future"):
            tb = repr(context["future"])
        key = f"{msg}:{type(exc).__name__ if exc else ''}"
        now = time.monotonic()
        if now - _loop_exc_last.get(key, 0) < _LOOP_EXC_COOLDOWN:
            return
        _loop_exc_last[key] = now
        log_event("ERROR", f"{msg}\n{_tail(tb)}")

    loop.set_exception_handler(_loop_exception_handler)

    while True:
        # Build a fresh bot every iteration. Reusing an instance after close()
        # leaves a closed aiohttp session inside HTTPClient, causing
        # `RuntimeError: Session is closed` on the next login attempt.
        bot = HateBot(command_prefix="!", intents=intents)
        shared.set_bot(bot)
        _register_events(bot)

        clean_exit = False
        try:
            async with bot:
                await bot.start(token, reconnect=True)
            clean_exit = True
        except discord.LoginFailure:
            log_event("ERROR", "Invalid Discord token — cannot login, shutting down")
            return
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            tb = traceback.format_exc()
            log_event("ERROR", f"Bot crashed: {e} — restarting in {_RESTART_DELAY}s\n{_tail(tb)}")
        finally:
            wd = getattr(bot, "_watchdog_task", None)
            if wd and not wd.done():
                wd.cancel()

        if clean_exit:
            log_event("INFO", f"Bot exited cleanly — restarting in {_RESTART_DELAY}s")
        await asyncio.sleep(_RESTART_DELAY)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
