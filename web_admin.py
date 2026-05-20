import os
import asyncio
import secrets
import datetime
import traceback
import html
import collections
import aiohttp.web

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
_sessions: dict = {}

# ── Debug log buffer ──────────────────────────────────────────────────────────
_LOG_BUFFER: collections.deque = collections.deque(maxlen=200)
_LOG_LEVELS = {"INFO": "#58a6ff", "WARN": "#d29922", "ERROR": "#f85149", "EVENT": "#3fb950"}
_LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "bot.log")


def log_event(level: str, message: str) -> None:
    """Append a timestamped entry to the in-memory ring buffer and persist to log file."""
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _LOG_BUFFER.append({"ts": ts, "level": level.upper(), "message": message})
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level.upper():5}] {message}\n")
    except Exception:
        pass

_CSS = """
* { box-sizing: border-box; }
body { font-family: 'Courier New', monospace; background: #0d1117; color: #c9d1d9; padding: 0; margin: 0; }
nav { background: #161b22; border-bottom: 1px solid #30363d; padding: 12px 24px; display: flex; gap: 20px; align-items: center; }
nav .brand { color: #7c83fd; font-weight: bold; font-size: 1.1em; margin-right: 12px; }
nav a { color: #8b949e; text-decoration: none; }
nav a:hover { color: #c9d1d9; }
main { padding: 24px; max-width: 1200px; }
h1 { color: #7c83fd; margin-top: 0; font-size: 1.4em; }
h2 { color: #58a6ff; font-size: 1.1em; margin: 20px 0 8px; }
.cards { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; min-width: 150px; }
.card .val { font-size: 2em; color: #7c83fd; font-weight: bold; }
.card .label { color: #8b949e; font-size: .8em; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; background: #161b22; border: 1px solid #30363d; border-radius: 8px; overflow: hidden; margin: 8px 0; }
th { background: #21262d; color: #58a6ff; padding: 10px 14px; text-align: left; font-size: .85em; border-bottom: 1px solid #30363d; }
td { padding: 8px 14px; border-bottom: 1px solid #21262d; font-size: .9em; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #1c2128; }
input[type=text],input[type=password],input[type=number],select { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 6px 10px; border-radius: 6px; font-family: inherit; }
.btn { background: #238636; color: #fff; border: 1px solid #2ea043; padding: 6px 16px; border-radius: 6px; cursor: pointer; font-family: inherit; font-size: .9em; }
.btn:hover { background: #2ea043; }
.btn.danger { background: #da3633; border-color: #f85149; }
.btn.danger:hover { background: #f85149; }
.btn.secondary { background: #21262d; color: #c9d1d9; border-color: #30363d; }
.btn.secondary:hover { background: #30363d; }
.form-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 6px 0; }
.panel { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin: 12px 0; }
.msg { padding: 10px 14px; border-radius: 6px; margin: 8px 0; font-size: .9em; }
.msg.ok { background: #0d2818; color: #3fb950; border: 1px solid #238636; }
.msg.err { background: #2d1316; color: #f85149; border: 1px solid #da3633; }
.green { color: #3fb950; } .red { color: #f85149; } .yellow { color: #d29922; } .muted { color: #8b949e; }
a { color: #58a6ff; text-decoration: none; }
a:hover { text-decoration: underline; }
"""


def _page(title: str, body: str, nav: bool = True) -> aiohttp.web.Response:
    nav_html = ""
    if nav:
        nav_html = """<nav>
  <span class="brand">Bot Admin</span>
  <a href="/">Dashboard</a>
  <a href="/economy">Economy</a>
  <a href="/shop">Shop</a>
  <a href="/stocks">Stocks</a>
  <a href="/messages">Messages</a>
  <a href="/sports">Sports</a>
  <a href="/logs">Logs</a>
  <a href="/logout">Logout</a>
</nav>"""
    return aiohttp.web.Response(
        content_type="text/html",
        text=f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Admin — {title}</title>
<style>{_CSS}</style></head>
<body>{nav_html}<main><h1>{title}</h1>{body}</main></body></html>""",
    )


def _check_auth(request: aiohttp.web.Request) -> bool:
    token = request.cookies.get("admin_token")
    return bool(token and _sessions.get(token))


def _svg_sparkline(prices, width=100, height=28):
    """Generate an inline SVG sparkline from a list of prices."""
    if len(prices) < 2:
        return '<span class="muted">—</span>'
    mn, mx = min(prices), max(prices)
    color = "#3fb950" if prices[-1] >= prices[0] else "#f85149"
    n = len(prices)
    if mx == mn:
        pts = " ".join(f"{int(i / (n - 1) * width)},{height // 2}" for i in range(n))
    else:
        pts = " ".join(
            f"{int(i / (n - 1) * width)},{int((1 - (p - mn) / (mx - mn)) * (height - 4) + 2)}"
            for i, p in enumerate(prices)
        )
    return (
        f'<svg width="{width}" height="{height}" style="vertical-align:middle;display:block">'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>'
        f'</svg>'
    )


def create_web_app(load_eco, save_eco, get_shop, shop_items, market_stocks, bot, tts_queue=None):

    def _user_name(uid: str) -> str:
        user = bot.get_user(int(uid))
        return user.display_name if user else uid

    def _portfolio_value(eco: dict, uid: str) -> float:
        stocks = eco.get("stocks", {}).get(uid, {})
        total = 0.0
        for ticker, shares in stocks.items():
            price = eco.get("market", {}).get(ticker, {}).get(
                "price", market_stocks.get(ticker, {}).get("base_price", 0)
            )
            total += shares * price
        return total

    # ── Auth ─────────────────────────────────────────────────────────────────

    async def handle_login_get(request):
        msg = (
            '<div class="msg err">Wrong password.</div>'
            if request.rel_url.query.get("err")
            else ""
        )
        body = f"""{msg}
<div class="panel" style="max-width:320px">
  <h2 style="margin-top:0">Login</h2>
  <form method="post" action="/login">
    <div class="form-row">
      <label>Password&nbsp;</label>
      <input type="password" name="password" autofocus>
    </div>
    <div class="form-row"><input type="submit" class="btn" value="Login"></div>
  </form>
</div>"""
        return _page("Login", body, nav=False)

    async def handle_login_post(request):
        data = await request.post()
        if data.get("password") == ADMIN_PASSWORD:
            token = secrets.token_hex(32)
            _sessions[token] = True
            resp = aiohttp.web.HTTPFound("/")
            resp.set_cookie("admin_token", token, httponly=True)
            return resp
        return aiohttp.web.HTTPFound("/login?err=1")

    async def handle_logout(request):
        token = request.cookies.get("admin_token")
        _sessions.pop(token, None)
        resp = aiohttp.web.HTTPFound("/login")
        resp.del_cookie("admin_token")
        return resp

    # ── Dashboard ────────────────────────────────────────────────────────────

    async def handle_dashboard(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        eco = load_eco()
        msg = ""
        if request.rel_url.query.get("ok"):
            msg = f'<div class="msg ok">{html.escape(request.rel_url.query["ok"])}</div>'
        if request.rel_url.query.get("err"):
            msg = f'<div class="msg err">{html.escape(request.rel_url.query["err"])}</div>'
        balances = eco.get("balances", {})
        total_coins = sum(balances.values())
        rotation, expires = get_shop()
        now = datetime.datetime.now(datetime.timezone.utc)
        secs = max(0, int((expires - now).total_seconds()))
        h, m = secs // 3600, (secs % 3600) // 60

        top5 = sorted(balances.items(), key=lambda x: x[1], reverse=True)[:5]
        top5_rows = "".join(
            f"<tr><td><a href='/user/{uid}'>{_user_name(uid)}</a></td>"
            f"<td>{bal:,.0f}</td></tr>"
            for uid, bal in top5
        )

        shop_rows = "".join(
            f"<tr><td><b>{shop_items[k]['name']}</b></td>"
            f"<td class='muted'>{k}</td>"
            f"<td>{shop_items[k]['cost']}</td></tr>"
            for k in rotation
            if k in shop_items
        )

        stock_rows = ""
        for ticker, info in market_stocks.items():
            price = eco.get("market", {}).get(ticker, {}).get("price", info.get("base_price", 0))
            stock_rows += (
                f"<tr><td><b>{ticker}</b></td><td>{info.get('name', ticker)}</td>"
                f"<td>{price:.2f}</td></tr>"
            )

        # ── Bot health ────────────────────────────────────────────────────────
        is_ready = bot.is_ready()
        latency = bot.latency
        import math as _math
        disconnected_since = getattr(bot, "_disconnected_since", None)
        if not is_ready:
            if disconnected_since:
                off_secs = int((now - disconnected_since).total_seconds())
                off_m, off_s = divmod(off_secs, 60)
                off_str = f"{off_m}m {off_s}s" if off_m else f"{off_s}s"
                status_html = (
                    f'<span class="yellow" style="font-size:1.1em">&#9679;</span> '
                    f'<b class="yellow">Reconnecting</b> '
                    f'<span class="muted" style="font-size:.85em">({off_str})</span>'
                )
            else:
                status_html = '<span class="red" style="font-size:1.1em">&#9679;</span> <b class="red">Offline</b>'
            latency_html = '<span class="muted">—</span>'
        elif _math.isnan(latency):
            status_html = '<span class="yellow" style="font-size:1.1em">&#9679;</span> <b class="yellow">No heartbeat</b>'
            latency_html = '<span class="red">nan</span>'
        elif latency > 5.0:
            status_html = '<span class="yellow" style="font-size:1.1em">&#9679;</span> <b class="yellow">Degraded</b>'
            latency_html = f'<span class="red">{latency * 1000:.0f} ms</span>'
        else:
            status_html = '<span class="green" style="font-size:1.1em">&#9679;</span> <b class="green">Online</b>'
            latency_html = f'<span class="green">{latency * 1000:.0f} ms</span>'

        online_since = getattr(bot, "_online_since", None)
        if online_since:
            up_secs = int((now - online_since).total_seconds())
            up_d, up_rem = divmod(up_secs, 86400)
            up_h, up_rem = divmod(up_rem, 3600)
            up_m = up_rem // 60
            if up_d:
                uptime_str = f"{up_d}d {up_h}h {up_m}m"
            elif up_h:
                uptime_str = f"{up_h}h {up_m}m"
            else:
                uptime_str = f"{up_m}m"
            uptime_html = f'{uptime_str} <span class="muted">(since {online_since.strftime("%Y-%m-%d %H:%M")} UTC)</span>'
        else:
            uptime_html = '<span class="muted">unknown</span>'

        guild_rows = "".join(
            f"<tr><td>{html.escape(g.name)}</td>"
            f"<td class='muted' style='font-size:.8em'>{g.id}</td>"
            f"<td>{g.member_count}</td></tr>"
            for g in sorted(bot.guilds, key=lambda g: g.name)
        )

        health_panel = f"""
<div class="panel" style="margin-bottom:20px">
  <h2 style="margin-top:0;margin-bottom:12px">Bot Health</h2>
  <div style="display:flex;gap:32px;flex-wrap:wrap;align-items:flex-start">
    <div>
      <div class="label" style="margin-bottom:4px">Status</div>
      <div style="font-size:1em">{status_html}</div>
    </div>
    <div>
      <div class="label" style="margin-bottom:4px">Gateway latency</div>
      <div style="font-size:1em">{latency_html}</div>
    </div>
    <div>
      <div class="label" style="margin-bottom:4px">Uptime</div>
      <div style="font-size:.9em">{uptime_html}</div>
    </div>
  </div>
  <table style="margin-top:14px;width:auto;min-width:320px">
    <thead><tr><th>Guild</th><th>ID</th><th>Members</th></tr></thead>
    <tbody>{guild_rows}</tbody>
  </table>
</div>"""

        guild_targets = eco.get("guild_targets", {})
        target_forms = ""
        for guild in sorted(bot.guilds, key=lambda g: g.name):
            tgt = guild_targets.get(str(guild.id), {})
            t_name = html.escape(tgt.get("name", ""))
            t_users = html.escape(", ".join(tgt.get("usernames", [])))
            t_ticker = html.escape(tgt.get("ticker", ""))
            t_bio = html.escape(tgt.get("bio", ""))
            target_forms += f"""
<div class="panel">
  <h2 style="margin-top:0">{html.escape(guild.name)} <span class="muted" style="font-size:.8em">({guild.id})</span></h2>
  <form method="post" action="/api/settarget">
    <input type="hidden" name="guild_id" value="{guild.id}">
    <div class="form-row">
      <label>Name</label>
      <input type="text" name="name" value="{t_name}" placeholder="Donovan" style="min-width:220px">
      <label>Usernames</label>
      <input type="text" name="usernames" value="{t_users}" placeholder="Donovan, donovan123" style="min-width:280px">
      <label>Ticker</label>
      <input type="text" name="ticker" value="{t_ticker}" placeholder="DONOVAN" style="width:120px">
      <input type="submit" class="btn" value="Save Target">
    </div>
  </form>
  <form method="post" action="/api/settargetbio" style="margin-top:10px">
    <input type="hidden" name="guild_id" value="{guild.id}">
    <div style="display:flex;flex-direction:column;gap:6px">
      <label style="font-weight:600">Roast Bio <span class="muted" style="font-weight:normal;font-size:.85em">— facts the bot weaves into insults (hobbies, habits, running jokes, etc.)</span></label>
      <textarea name="bio" rows="3" placeholder="e.g. obsessed with fantasy football, never finishes projects, calls himself an entrepreneur" style="width:100%;max-width:700px;font-family:monospace;font-size:.9em">{t_bio}</textarea>
      <div><input type="submit" class="btn secondary" value="Save Bio"></div>
    </div>
  </form>
</div>"""

        body = f"""
{msg}
{health_panel}
<div class="cards">
  <div class="card"><div class="val">{len(balances)}</div><div class="label">Users</div></div>
  <div class="card"><div class="val">{total_coins:,.0f}</div><div class="label">Coins in circulation</div></div>
  <div class="card"><div class="val">{len(rotation)}</div><div class="label">Shop items today</div></div>
  <div class="card"><div class="val">{len(market_stocks)}</div><div class="label">Stocks tracked</div></div>
</div>

<h2>Today's Shop <span class="muted" style="font-size:.8em">— refreshes in {h}h {m}m</span></h2>
<table><thead><tr><th>Item</th><th>Key</th><th>Cost</th></tr></thead>
<tbody>{shop_rows}</tbody></table>

<h2>Top Balances</h2>
<table><thead><tr><th>User</th><th>Coins</th></tr></thead>
<tbody>{top5_rows}</tbody></table>

<h2>Stock Prices</h2>
<table><thead><tr><th>Ticker</th><th>Name</th><th>Price</th></tr></thead>
<tbody>{stock_rows}</tbody></table>

<h2>Server Targets</h2>
{target_forms}
"""
        return _page("Dashboard", body)

    async def handle_settarget_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        data = await request.post()
        guild_id = data.get("guild_id", "").strip()
        name = data.get("name", "").strip()
        usernames_raw = data.get("usernames", "").strip()
        ticker = data.get("ticker", "").strip().upper()
        if not guild_id:
            return aiohttp.web.HTTPFound("/?err=Missing+guild+id")
        if not name:
            return aiohttp.web.HTTPFound("/?err=Name+is+required")
        usernames = [u.strip() for u in usernames_raw.split(",") if u.strip()]
        if not usernames:
            return aiohttp.web.HTTPFound("/?err=At+least+one+username+is+required")
        if not ticker:
            ticker = name.upper()[:8]
        eco = load_eco()
        existing = eco.get("guild_targets", {}).get(guild_id, {})
        eco.setdefault("guild_targets", {})[guild_id] = {
            "name": name,
            "usernames": usernames,
            "ticker": ticker,
            "bio": existing.get("bio", ""),
        }
        save_eco(eco)
        log_event("WARN", f"[Admin] Target set for guild {guild_id}: {name} / {usernames} / ${ticker}")
        return aiohttp.web.HTTPFound("/?ok=Target+saved")

    async def handle_settargetbio_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        data = await request.post()
        guild_id = data.get("guild_id", "").strip()
        bio = data.get("bio", "").strip()
        if not guild_id:
            return aiohttp.web.HTTPFound("/?err=Missing+guild+id")
        eco = load_eco()
        target = eco.get("guild_targets", {}).get(guild_id)
        if not target:
            return aiohttp.web.HTTPFound("/?err=No+target+set+for+that+server")
        target["bio"] = bio
        save_eco(eco)
        log_event("INFO", f"[Admin] Bio updated for guild {guild_id}: {bio[:80]}")
        return aiohttp.web.HTTPFound("/?ok=Bio+saved")

    # ── Economy ──────────────────────────────────────────────────────────────

    async def handle_economy(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        eco = load_eco()
        balances = eco.get("balances", {})
        msg = ""
        if request.rel_url.query.get("ok"):
            msg = f'<div class="msg ok">{request.rel_url.query["ok"]}</div>'
        if request.rel_url.query.get("err"):
            msg = f'<div class="msg err">{request.rel_url.query["err"]}</div>'

        rows = "".join(
            f"<tr><td><a href='/user/{uid}'>{_user_name(uid)}</a></td>"
            f"<td class='muted' style='font-size:.8em'>{uid}</td>"
            f"<td>{bal:,.0f}</td>"
            f"<td>{_portfolio_value(eco, uid):,.0f}</td>"
            f"<td>{bal + _portfolio_value(eco, uid):,.0f}</td></tr>"
            for uid, bal in sorted(balances.items(), key=lambda x: x[1], reverse=True)
        )

        body = f"""{msg}
<div class="panel">
  <h2 style="margin-top:0">Adjust Coins</h2>
  <form method="post" action="/api/coins">
    <div class="form-row">
      <label>User ID</label>
      <input type="text" name="uid" placeholder="Discord user ID" style="width:180px">
      <label>Amount</label>
      <input type="number" name="amount" placeholder="e.g. 500" style="width:120px">
      <select name="op">
        <option value="add">Add</option>
        <option value="remove">Remove</option>
        <option value="set">Set</option>
      </select>
      <input type="submit" class="btn" value="Apply">
    </div>
  </form>
</div>

<h2>All Balances ({len(balances)} users)</h2>
<table>
  <thead><tr><th>User</th><th>ID</th><th>Cash</th><th>Portfolio</th><th>Net Worth</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""
        return _page("Economy", body)

    async def handle_coins_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        data = await request.post()
        uid = data.get("uid", "").strip()
        op = data.get("op", "add")
        try:
            amount = float(data.get("amount", "0"))
        except ValueError:
            return aiohttp.web.HTTPFound("/economy?err=Invalid+amount")
        if not uid:
            return aiohttp.web.HTTPFound("/economy?err=User+ID+required")
        eco = load_eco()
        current = eco.get("balances", {}).get(uid, 0)
        if op == "add":
            eco.setdefault("balances", {})[uid] = current + amount
            msg = f"Added {amount:,.0f} coins to {uid}. New balance: {eco['balances'][uid]:,.0f}"
        elif op == "remove":
            eco.setdefault("balances", {})[uid] = max(0, current - amount)
            msg = f"Removed {amount:,.0f} coins from {uid}. New balance: {eco['balances'][uid]:,.0f}"
        else:
            eco.setdefault("balances", {})[uid] = amount
            msg = f"Set {uid} balance to {amount:,.0f}"
        save_eco(eco)
        log_event("WARN", f"[Admin] Coin adjustment: {msg}")
        return aiohttp.web.HTTPFound(f"/economy?ok={msg.replace(' ', '+')}")

    # ── Shop ─────────────────────────────────────────────────────────────────

    async def handle_shop(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        rotation, expires = get_shop()
        now = datetime.datetime.now(datetime.timezone.utc)
        secs = max(0, int((expires - now).total_seconds()))
        h, m = secs // 3600, (secs % 3600) // 60
        msg = (
            '<div class="msg ok">Shop rotation reset successfully!</div>'
            if request.rel_url.query.get("ok")
            else ""
        )

        rows = "".join(
            f"<tr><td><b>{shop_items[k]['name']}</b></td>"
            f"<td class='muted'>{k}</td>"
            f"<td>{shop_items[k]['cost']}</td>"
            f"<td>{shop_items[k]['description']}</td></tr>"
            for k in rotation
            if k in shop_items
        )

        body = f"""{msg}
<p class="muted">Rotation expires in <b>{h}h {m}m</b></p>
<table>
  <thead><tr><th>Item</th><th>Key</th><th>Cost</th><th>Description</th></tr></thead>
  <tbody>{rows}</tbody>
</table>

<div class="panel">
  <h2 style="margin-top:0">Force Reset</h2>
  <p class="muted">Immediately rotate to a new set of items, excluding the current ones.</p>
  <form method="post" action="/api/resetshop">
    <input type="submit" class="btn danger" value="Reset Shop Now">
  </form>
</div>"""
        return _page("Shop", body)

    async def handle_resetshop_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        eco = load_eco()
        eco["shop_rotation"] = None
        eco["shop_rotation_expires"] = None
        save_eco(eco)
        get_shop()
        return aiohttp.web.HTTPFound("/shop?ok=1")

    # ── Stocks ───────────────────────────────────────────────────────────────

    async def handle_stocks(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        eco = load_eco()
        msg = ""
        if request.rel_url.query.get("ok"):
            msg = f'<div class="msg ok">{request.rel_url.query["ok"]}</div>'
        if request.rel_url.query.get("err"):
            msg = f'<div class="msg err">{request.rel_url.query["err"]}</div>'

        # Collect current guild target tickers so we can flag orphaned stocks
        current_target_tickers = {
            v.get("ticker", "").upper()
            for v in eco.get("guild_targets", {}).values()
            if v.get("ticker")
        }

        rows = ""
        for ticker, info in market_stocks.items():
            mdata = eco.get("market", {}).get(ticker, {})
            price = mdata.get("price", info.get("base_price", 0))
            outstanding = info.get("shares_outstanding", 1000)
            total_shorted = sum(
                pos.get(ticker, {}).get("shares", 0)
                for pos in eco.get("short_positions", {}).values()
            )
            si_pct = (total_shorted / outstanding * 100) if outstanding else 0
            si_class = "red" if si_pct > 20 else ("yellow" if si_pct > 10 else "green")
            # Target tickers are shown in the Target Stocks section below
            if ticker in current_target_tickers:
                continue

            remove_btn = ""
            # Show Force Remove for orphaned stocks (no base_price in original spec)
            is_orphan = not info.get("_builtin", True)
            if is_orphan:
                remove_btn = (
                    f'<form method="post" action="/api/removestock" style="display:inline;margin-left:6px">'
                    f'<input type="hidden" name="ticker" value="{ticker}">'
                    f'<input type="submit" class="btn danger" value="Remove" '
                    f'onclick="return confirm(\'Force-remove ${ticker} from the market? Holders will be liquidated at current price.\')">'
                    f'</form>'
                )
            import shared as _shared
            news_options = "".join(
                f'<option value="{i}">{e["headline"][:80]}{"…" if len(e["headline"]) > 80 else ""}</option>'
                for i, e in enumerate(_shared._STOCK_NEWS.get(ticker, []))
            )
            trigger_form = (
                f'<form method="post" action="/api/triggerevent" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:4px">'
                f'<input type="hidden" name="ticker" value="{ticker}">'
                f'<select name="event_index" style="max-width:300px;font-size:11px">{news_options}</select>'
                f'<input type="submit" class="btn" value="Fire" style="background:#7c83fd">'
                f'</form>'
            ) if news_options else ""
            price_history = mdata.get("price_history", [price])
            sparkline_svg = _svg_sparkline(price_history)
            ath = mdata.get("all_time_high", price)
            atl = mdata.get("all_time_low", price)
            chg_1 = price - price_history[-2] if len(price_history) >= 2 else 0
            chg_cls = "green" if chg_1 >= 0 else "red"
            chg_str = f'<span class="{chg_cls}">{chg_1:+.2f}</span>'
            rows += f"""<tr>
  <td><b>{ticker}</b></td><td>{info.get('name', ticker)}</td>
  <td>{price:.2f} {chg_str}</td>
  <td class="{si_class}">{si_pct:.1f}%</td>
  <td style="min-width:110px">{sparkline_svg}<span class="muted" style="font-size:.75em">H:{ath:.2f} L:{atl:.2f}</span></td>
  <td style="display:flex;flex-direction:column;gap:6px">
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <form method="post" action="/api/setprice" style="display:flex;gap:6px;align-items:center">
        <input type="hidden" name="ticker" value="{ticker}">
        <input type="number" name="price" value="{price:.2f}" step="0.01" min="0.01" style="width:90px">
        <input type="submit" class="btn secondary" value="Set">
      </form>
      {remove_btn}
    </div>
    {trigger_form}
  </td>
</tr>"""

        # ── Target stocks: current + historical ──
        delist_grace = datetime.timedelta(hours=48)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        target_rows = ""
        for guild in sorted(bot.guilds, key=lambda g: g.name):
            gid = str(guild.id)
            guild_name = html.escape(guild.name)

            # Current active target for this guild
            current = eco.get("guild_targets", {}).get(gid, {})
            cur_ticker = current.get("ticker", "")
            cur_name = current.get("name", cur_ticker)
            if cur_ticker:
                price_t = eco.get("market", {}).get(cur_ticker, {}).get("price", 0.0)
                cur_delist_action = (
                    f'<form method="post" action="/api/deliststock" style="display:inline">'
                    f'<input type="hidden" name="guild_id" value="{gid}">'
                    f'<input type="hidden" name="ticker" value="{html.escape(cur_ticker)}">'
                    f'<input type="hidden" name="source" value="current">'
                    f'<input type="submit" class="btn danger" value="Delist" '
                    f'onclick="return confirm(\'Start 48hr delist countdown for {html.escape(cur_ticker)}? The stock will be auto-liquidated after the grace period.\')">'
                    f'</form>'
                )
                target_rows += (
                    f"<tr><td><b>{html.escape(cur_ticker)}</b></td>"
                    f"<td>{html.escape(cur_name)}</td>"
                    f"<td>{guild_name}</td>"
                    f"<td>{price_t:.2f}</td>"
                    f"<td><span style='color:#7c83fd'>Current Target</span></td>"
                    f"<td>{cur_delist_action}</td></tr>"
                )

            # Historical targets for this guild
            history = eco.get("target_history", {}).get(gid, [])
            for entry in history:
                ticker_t = entry.get("ticker", "")
                name_t = entry.get("name", ticker_t)
                if not ticker_t:
                    continue
                price_t = eco.get("market", {}).get(ticker_t, {}).get("price", 0.0)
                delisted_at_str = entry.get("delisted_at")
                if delisted_at_str:
                    deadline = datetime.datetime.fromisoformat(delisted_at_str) + delist_grace
                    if deadline <= now_utc:
                        status_html = '<span class="muted">Delisted</span>'
                    else:
                        hrs = round((deadline - now_utc).total_seconds() / 3600, 1)
                        status_html = f'<span class="yellow">Delisting — {hrs}h left</span>'
                    action_html = ""
                else:
                    status_html = '<span class="green">Active</span>'
                    action_html = (
                        f'<form method="post" action="/api/deliststock" style="display:inline">'
                        f'<input type="hidden" name="guild_id" value="{gid}">'
                        f'<input type="hidden" name="ticker" value="{html.escape(ticker_t)}">'
                        f'<input type="submit" class="btn danger" value="Delist" '
                        f'onclick="return confirm(\'Start 48hr delist countdown for {html.escape(ticker_t)}?\')">'
                        f'</form>'
                    )
                target_rows += (
                    f"<tr><td><b>{html.escape(ticker_t)}</b></td>"
                    f"<td>{html.escape(name_t)}</td>"
                    f"<td>{guild_name}</td>"
                    f"<td>{price_t:.2f}</td>"
                    f"<td>{status_html}</td>"
                    f"<td>{action_html}</td></tr>"
                )

        target_section = ""
        if target_rows:
            target_section = f"""
<h2>Target Stocks</h2>
<table>
  <thead><tr><th>Ticker</th><th>Name</th><th>Server</th><th>Price</th><th>Status</th><th>Action</th></tr></thead>
  <tbody>{target_rows}</tbody>
</table>"""

        body = f"""{msg}
<div class="panel">
  <h2 style="margin-top:0">Manual Actions</h2>
  <form method="post" action="/api/triggerdividends" onsubmit="return confirm('Pay dividends right now using current market prices?');">
    <input type="submit" class="btn" value="Run Dividend Payout Now">
  </form>
</div>
<table>
  <thead><tr><th>Ticker</th><th>Name</th><th>Price</th><th>Short Interest</th><th>Trend</th><th>Override Price</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
{target_section}"""
        return _page("Stocks", body)

    async def handle_deliststock_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        data = await request.post()
        guild_id = data.get("guild_id", "").strip()
        ticker = data.get("ticker", "").strip().upper()
        source = data.get("source", "history")
        if not guild_id or not ticker:
            return aiohttp.web.HTTPFound("/stocks?err=Missing+parameters")
        eco = load_eco()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if source == "current":
            # Archive the current target into target_history with delisted_at set now
            current = eco.get("guild_targets", {}).get(guild_id, {})
            if not current or current.get("ticker", "").upper() != ticker:
                return aiohttp.web.HTTPFound(f"/stocks?err={ticker}+is+not+the+current+target+for+this+server")
            history = eco.setdefault("target_history", {}).setdefault(guild_id, [])
            # Avoid duplicate if already queued
            for entry in history:
                if entry.get("ticker", "").upper() == ticker and entry.get("delisted_at"):
                    return aiohttp.web.HTTPFound(f"/stocks?err={ticker}+already+queued+for+delisting")
            history.append({
                "name": current.get("name", ticker),
                "usernames": current.get("usernames", []),
                "ticker": ticker,
                "delisted_at": now_iso,
            })
        else:
            # Historical entry — just set delisted_at
            history = eco.get("target_history", {}).get(guild_id, [])
            found = False
            for entry in history:
                if entry.get("ticker") == ticker and not entry.get("delisted_at"):
                    entry["delisted_at"] = now_iso
                    found = True
                    break
            if not found:
                return aiohttp.web.HTTPFound(f"/stocks?err={ticker}+not+found+or+already+delisting")

        save_eco(eco)
        return aiohttp.web.HTTPFound(f"/stocks?ok={ticker}+marked+for+delisting+%2848hr+grace+period+started%29")

    async def handle_removestock_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        data = await request.post()
        ticker = data.get("ticker", "").strip().upper()
        if not ticker:
            return aiohttp.web.HTTPFound("/stocks?err=Missing+ticker")
        eco = load_eco()
        price = eco.get("market", {}).get(ticker, {}).get("price", 0.0)
        liquidated = 0
        # Pay out all holders at current price (skip legacy non-user keys)
        for uid, portfolio in eco.get("stocks", {}).items():
            if not uid.isdigit() or not isinstance(portfolio, dict):
                continue
            shares = portfolio.get(ticker, 0)
            if shares > 0:
                payout = round(shares * price, 2)
                eco.setdefault("balances", {})[uid] = eco["balances"].get(uid, 0) + payout
                portfolio[ticker] = 0
                liquidated += 1
        # Remove from market data and market_stocks in-memory dict
        eco.get("market", {}).pop(ticker, None)
        market_stocks.pop(ticker, None)
        save_eco(eco)
        msg = f"Removed+{ticker}+from+market"
        if liquidated:
            msg += f"+and+liquidated+{liquidated}+holder(s)+at+%24{price:.2f}"
        return aiohttp.web.HTTPFound(f"/stocks?ok={msg}")

    async def handle_setprice_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        data = await request.post()
        ticker = data.get("ticker", "").upper()
        try:
            price = float(data.get("price", "0"))
        except ValueError:
            return aiohttp.web.HTTPFound("/stocks?err=Invalid+price")
        if ticker not in market_stocks:
            return aiohttp.web.HTTPFound("/stocks?err=Unknown+ticker")
        if price <= 0:
            return aiohttp.web.HTTPFound("/stocks?err=Price+must+be+positive")
        eco = load_eco()
        old_price = eco.get("market", {}).get(ticker, {}).get("price", "?")
        eco.setdefault("market", {}).setdefault(ticker, {})["price"] = price
        save_eco(eco)
        log_event("WARN", f"[Admin] Stock price override: ${ticker} {old_price} → {price:.2f}")
        return aiohttp.web.HTTPFound(f"/stocks?ok=Set+{ticker}+price+to+{price:.2f}")

    async def handle_triggerevent_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        import shared as _shared, random as _random
        data = await request.post()
        ticker = data.get("ticker", "").upper()
        try:
            event_index = int(data.get("event_index", 0))
        except ValueError:
            return aiohttp.web.HTTPFound("/stocks?err=Invalid+event+index")
        news_list = _shared._STOCK_NEWS.get(ticker, [])
        if not news_list or event_index >= len(news_list):
            return aiohttp.web.HTTPFound("/stocks?err=Invalid+event")
        event = news_list[event_index]
        eco = load_eco()
        _shared.init_market(eco)
        if ticker not in eco.get("market", {}):
            return aiohttp.web.HTTPFound(f"/stocks?err={ticker}+not+in+market")

        headline = event["headline"]

        impact_pct = _random.uniform(*event["impact"])
        impacts = {ticker: impact_pct}
        for linked_ticker, linked_range in event.get("linked", []):
            impacts[linked_ticker] = _random.uniform(*linked_range)

        old_prices = {}
        for t, pct in impacts.items():
            if t in eco["market"]:
                old_prices[t] = eco["market"][t]["price"]
                new_price = old_prices[t] * (1 + pct / 100)
                _shared._apply_price_event(eco["market"][t], new_price)
        save_eco(eco)

        arrow = "📈" if impact_pct > 0 else "📉"
        new_p = eco["market"][ticker]["price"]
        analyst = _random.choice(_shared._ANALYST_QUOTES)
        linked_str = "".join(
            f" | **${t}** → **${eco['market'][t]['price']:.2f}** ({pct:+.1f}%)"
            for t, pct in impacts.items() if t != ticker
        )
        broadcast_channels = _shared._get_guild_channels()
        for gid, ch in broadcast_channels:
            localized = _shared._t(headline, gid).replace("{member}", _shared._get_random_member_name(gid))
            asyncio.ensure_future(ch.send(
                f"{arrow} **BREAKING — ${ticker}:** {localized}\n"
                f"**${old_prices.get(ticker, new_p):.2f} → ${new_p:.2f}** ({impact_pct:+.1f}%){linked_str}\n"
                f"*{analyst}*"
            ))
        log_event("WARN", f"[Admin] Manual event fired: ${ticker} — {headline[:60]}")
        return aiohttp.web.HTTPFound(f"/stocks?ok=Event+fired+for+{ticker}")

    async def handle_triggerdividends_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        import shared as _shared
        eco = load_eco()
        _shared.init_market(eco)
        payouts = {}

        for ticker, info in _shared.MARKET_STOCKS.items():
            rate = info.get("dividend_rate")
            if not rate:
                continue
            price = eco.get("market", {}).get(ticker, {}).get("price", info.get("base_price", 0))
            per_share = round(price * rate, 2)
            if per_share <= 0:
                continue
            for uid, port in eco.get("portfolios", {}).items():
                shares = port.get(ticker, {}).get("shares", 0)
                if shares <= 0:
                    continue
                earned = round(per_share * shares)
                eco.setdefault("balances", {})[uid] = eco.get("balances", {}).get(uid, 0) + earned
                payouts.setdefault(uid, 0)
                payouts[uid] += earned

        save_eco(eco)
        if not payouts:
            log_event("WARN", "[Admin] Manual dividend payout ran: no eligible holders")
            return aiohttp.web.HTTPFound("/stocks?ok=Dividend+payout+ran+%28no+eligible+holders%29")

        total_paid = sum(payouts.values())
        log_event("WARN", f"[Admin] Manual dividend payout ran: {len(payouts)} user(s), {total_paid} coins paid")
        return aiohttp.web.HTTPFound(
            f"/stocks?ok=Dividend+payout+complete%3A+paid+{total_paid}+coins+to+{len(payouts)}+user%28s%29"
        )

    # ── User Detail ──────────────────────────────────────────────────────────

    async def handle_user(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        uid = request.match_info["uid"]
        eco = load_eco()
        name = _user_name(uid)
        balance = eco.get("balances", {}).get(uid, 0)
        msg = ""
        if request.rel_url.query.get("ok"):
            msg = f'<div class="msg ok">{request.rel_url.query["ok"]}</div>'

        # Portfolio
        stocks = eco.get("stocks", {}).get(uid, {})
        port_value = 0.0
        port_rows = ""
        for ticker, shares in stocks.items():
            price = eco.get("market", {}).get(ticker, {}).get(
                "price", market_stocks.get(ticker, {}).get("base_price", 0)
            )
            val = shares * price
            port_value += val
            port_rows += (
                f"<tr><td>{ticker}</td><td>{shares}</td>"
                f"<td>{price:.2f}</td><td>{val:,.2f}</td></tr>"
            )

        # Shorts
        shorts = eco.get("short_positions", {}).get(uid, {})
        short_rows = ""
        for ticker, pos in shorts.items():
            cur_price = eco.get("market", {}).get(ticker, {}).get(
                "price", market_stocks.get(ticker, {}).get("base_price", 0)
            )
            pnl = (pos["avg_price"] - cur_price) * pos["shares"]
            cls = "green" if pnl >= 0 else "red"
            short_rows += (
                f"<tr><td>{ticker}</td><td>{pos['shares']}</td>"
                f"<td>{pos['avg_price']:.2f}</td><td>{cur_price:.2f}</td>"
                f"<td class='{cls}'>{pnl:+.2f}</td></tr>"
            )

        inventory = eco.get("inventory", {}).get(uid, [])
        inv_html = (
            ", ".join(
                f"<b>{shop_items.get(i, {}).get('name', i)}</b>" for i in inventory
            )
            or "<span class='muted'>empty</span>"
        )

        port_table = (
            f"<table><thead><tr><th>Ticker</th><th>Shares</th><th>Price</th><th>Value</th></tr></thead>"
            f"<tbody>{port_rows or '<tr><td colspan=4 class=muted>No positions</td></tr>'}</tbody></table>"
        )
        short_table = (
            f"<table><thead><tr><th>Ticker</th><th>Shares</th><th>Entry</th><th>Current</th><th>P&L</th></tr></thead>"
            f"<tbody>{short_rows}</tbody></table>"
            if short_rows
            else "<p class='muted'>No short positions.</p>"
        )

        body = f"""{msg}
<p class="muted">User ID: {uid}</p>
<div class="cards">
  <div class="card"><div class="val">{balance:,.0f}</div><div class="label">Cash</div></div>
  <div class="card"><div class="val">{port_value:,.0f}</div><div class="label">Portfolio</div></div>
  <div class="card"><div class="val">{balance + port_value:,.0f}</div><div class="label">Net Worth</div></div>
</div>

<h2>Stock Portfolio</h2>{port_table}
<h2>Short Positions</h2>{short_table}
<h2>Inventory</h2><p>{inv_html}</p>

<div class="panel">
  <h2 style="margin-top:0">Adjust Coins</h2>
  <form method="post" action="/api/coins">
    <input type="hidden" name="uid" value="{uid}">
    <div class="form-row">
      <input type="number" name="amount" placeholder="Amount">
      <select name="op">
        <option value="add">Add</option>
        <option value="remove">Remove</option>
        <option value="set">Set</option>
      </select>
      <input type="submit" class="btn" value="Apply">
    </div>
  </form>
</div>"""
        return _page(f"User: {name}", body)

    # ── Messages ─────────────────────────────────────────────────────────────

    async def handle_messages(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        msg = ""
        if request.rel_url.query.get("ok"):
            msg = f'<div class="msg ok">{request.rel_url.query["ok"]}</div>'
        if request.rel_url.query.get("err"):
            msg = f'<div class="msg err">{request.rel_url.query["err"]}</div>'

        options = ""
        for guild in sorted(bot.guilds, key=lambda g: g.name):
            options += f'<optgroup label="{guild.name}">'
            for ch in sorted(guild.text_channels, key=lambda c: c.position):
                options += f'<option value="{ch.id}">#{ch.name}</option>'
            options += "</optgroup>"

        body = f"""{msg}
<div class="panel">
  <form method="post" action="/api/sendmessage">
    <div class="form-row">
      <label>Channel</label>
      <select name="channel_id" style="min-width:220px">{options}</select>
    </div>
    <div class="form-row" style="align-items:flex-start">
      <label style="margin-top:6px">Message</label>
      <textarea name="content" rows="6" style="flex:1;min-width:300px;background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:8px;border-radius:6px;font-family:inherit;font-size:.9em;resize:vertical"></textarea>
    </div>
    <div class="form-row">
      <label><input type="checkbox" name="tts" value="1"> Also play via TTS</label>
    </div>
    <div class="form-row">
      <input type="submit" class="btn" value="Send Message">
    </div>
  </form>
</div>"""
        return _page("Messages", body)

    async def handle_sendmessage_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        data = await request.post()
        channel_id = data.get("channel_id", "").strip()
        content = data.get("content", "").strip()
        if not channel_id:
            return aiohttp.web.HTTPFound("/messages?err=No+channel+selected")
        if not content:
            return aiohttp.web.HTTPFound("/messages?err=Message+cannot+be+empty")
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            return aiohttp.web.HTTPFound("/messages?err=Channel+not+found")
        await channel.send(content)
        ch_name = getattr(channel, "name", channel_id)
        if data.get("tts") == "1" and tts_queue is not None:
            guild_id = getattr(channel.guild, "id", None)
            await tts_queue.put((guild_id, content))
        return aiohttp.web.HTTPFound(f"/messages?ok=Message+sent+to+%23{ch_name}")

    # ── Debug log ─────────────────────────────────────────────────────────────

    async def handle_logs(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")

        level_filter = request.rel_url.query.get("level", "").upper()
        entries = list(reversed(_LOG_BUFFER))
        if level_filter and level_filter != "ALL":
            entries = [e for e in entries if e["level"] == level_filter]

        rows = ""
        for e in entries:
            color = _LOG_LEVELS.get(e["level"], "#c9d1d9")
            rows += (
                f"<tr>"
                f"<td class='muted' style='white-space:nowrap'>{html.escape(e['ts'])}</td>"
                f"<td style='color:{color};font-weight:bold;white-space:nowrap'>{html.escape(e['level'])}</td>"
                f"<td style='word-break:break-word'>{html.escape(e['message'])}</td>"
                f"</tr>"
            )

        if not rows:
            rows = "<tr><td colspan=3 class='muted' style='text-align:center'>No log entries yet.</td></tr>"

        filter_links = " &nbsp;".join(
            f"<a href='/logs?level={lvl}' style='color:{col}'>{lvl}</a>"
            for lvl, col in _LOG_LEVELS.items()
        )

        # ── Persistent file log (survives crashes) ────────────────────────────
        file_log_html = ""
        if os.path.exists(_LOG_FILE):
            try:
                with open(_LOG_FILE, "r", encoding="utf-8") as f:
                    raw_lines = f.readlines()
                last_lines = raw_lines[-200:]
                file_rows = "".join(
                    f"<tr><td style='word-break:break-word;font-size:.82em'>{html.escape(line.rstrip())}</td></tr>"
                    for line in reversed(last_lines)
                )
                file_size = os.path.getsize(_LOG_FILE)
                size_str = f"{file_size / 1024:.1f} KB" if file_size < 1024 * 1024 else f"{file_size / 1024 / 1024:.1f} MB"
                file_log_html = f"""
<h2>📄 Persistent Log File <span class="muted" style="font-size:.8em;font-weight:normal">— survives crashes — {len(raw_lines)} total lines ({size_str}) — showing last 200</span></h2>
<div style="display:flex;gap:8px;margin-bottom:8px">
  <a href="/logs/download" class="btn secondary" style="font-size:.85em">⬇ Download full log</a>
  <a href="/logs/clearfile" class="btn danger" style="font-size:.85em" onclick="return confirm('Delete log file?')">🗑 Clear file</a>
</div>
<table>
  <thead><tr><th>Entry (newest first)</th></tr></thead>
  <tbody>{file_rows}</tbody>
</table>"""
            except Exception as exc:
                file_log_html = f"<p class='msg err'>Could not read log file: {html.escape(str(exc))}</p>"
        else:
            file_log_html = "<p class='muted'>No log file yet — entries will appear here after the first event is logged.</p>"

        body = f"""
<div class="panel" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
  <span>Filter: <a href="/logs">ALL</a> &nbsp;{filter_links}</span>
  <span class="muted" style="font-size:.85em">Last {len(entries)} of {len(_LOG_BUFFER)} entries (newest first) — auto-refreshes every 15s</span>
  <a href="/logs/clearbuffer" class="btn danger" style="font-size:.85em;margin-left:auto" onclick="return confirm('Clear in-memory buffer?')">🗑 Clear buffer</a>
</div>
<h2>🧠 In-Memory Buffer <span class="muted" style="font-size:.8em;font-weight:normal">— lost on crash/restart</span></h2>
<table>
  <thead><tr><th style="width:180px">Time</th><th style="width:70px">Level</th><th>Message</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
{file_log_html}
<meta http-equiv="refresh" content="15">"""
        return _page("Debug Log", body)

    async def handle_clearlogs_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        _LOG_BUFFER.clear()
        return aiohttp.web.HTTPFound("/logs")

    async def handle_clearbuffer_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        _LOG_BUFFER.clear()
        return aiohttp.web.HTTPFound("/logs")

    async def handle_clearfile_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        try:
            open(_LOG_FILE, "w").close()
        except Exception:
            pass
        return aiohttp.web.HTTPFound("/logs")

    async def handle_download_log(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        if not os.path.exists(_LOG_FILE):
            return aiohttp.web.Response(text="No log file found.", status=404)
        with open(_LOG_FILE, "rb") as f:
            data = f.read()
        return aiohttp.web.Response(
            body=data,
            content_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=bot.log"},
        )

    # ── Sports ───────────────────────────────────────────────────────────────

    _ALL_SPORTS = {
        "NFL": "🏈 NFL",
        "NBA": "🏀 NBA",
        "MLB": "⚾ MLB",
        "NHL": "🏒 NHL",
        "KBO": "⚾ KBO (Korean Baseball)",
        "NPB": "⚾ NPB (Japanese Baseball)",
        "UFC": "🥊 UFC/MMA",
    }

    async def handle_sports(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        try:
            return await _handle_sports_inner(request)
        except Exception as exc:
            import traceback as _tb
            tb_str = html.escape(_tb.format_exc())
            log_event("ERROR", f"[Admin] /sports page error: {exc!r}")
            return _page("Sports — Error", f'<div class="msg err"><b>{html.escape(str(exc))}</b><br><pre style="font-size:.8em;white-space:pre-wrap">{tb_str}</pre></div>')

    async def _handle_sports_inner(request):
        eco = load_eco()
        msg = ""
        if request.rel_url.query.get("ok"):
            msg = f'<div class="msg ok">{html.escape(request.rel_url.query["ok"])}</div>'
        if request.rel_url.query.get("err"):
            msg = f'<div class="msg err">{html.escape(request.rel_url.query["err"])}</div>'

        disabled = set(eco.get("sports_config", {}).get("disabled_sports", []))

        rows = ""
        for key, label in _ALL_SPORTS.items():
            checked = "" if key in disabled else "checked"
            status_cls = "green" if key not in disabled else "red"
            status_txt = "Enabled" if key not in disabled else "Disabled"
            rows += (
                f"<tr>"
                f"<td>{label}</td>"
                f"<td><span class='{status_cls}'>{status_txt}</span></td>"
                f"<td><label style='display:flex;align-items:center;gap:8px;cursor:pointer'>"
                f"<input type='checkbox' name='sport_{key}' value='1' {checked} "
                f"style='width:16px;height:16px;cursor:pointer'>"
                f"<span class='muted' style='font-size:.85em'>Allow betting</span></label></td>"
                f"</tr>"
            )

        now = datetime.datetime.now(datetime.timezone.utc)

        def _parse_dt_safe(s):
            """Parse ISO datetime string; always returns a UTC-aware datetime."""
            if not s:
                return now
            try:
                s = s.replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                return dt
            except (ValueError, AttributeError):
                return now

        sports_events = eco.get("sports_events") or {}
        sports_bets = eco.get("sports_bets") or []
        sports_parlays = eco.get("sports_parlays") or []

        # Live open bet counts per sport
        bet_counts = {}
        parlay_counts = {}
        for b in sports_bets:
            if not isinstance(b, dict) or b.get("settled"):
                continue
            ev = sports_events.get(b.get("game_id", ""), {})
            sport = ev.get("sport", "?")
            bet_counts[sport] = bet_counts.get(sport, 0) + 1
        for p in sports_parlays:
            if not isinstance(p, dict) or p.get("settled"):
                continue
            for leg in (p.get("legs") or []):
                ev = sports_events.get(leg.get("game_id", ""), {})
                sport = ev.get("sport", "?")
                parlay_counts[sport] = parlay_counts.get(sport, 0) + 1

        stats_rows = "".join(
            f"<tr><td>{_ALL_SPORTS.get(s, s)}</td>"
            f"<td>{bet_counts.get(s, 0)}</td>"
            f"<td>{parlay_counts.get(s, 0)}</td></tr>"
            for s in _ALL_SPORTS
        )

        # Pending settlement: unsettled events past their start time
        pending_events = []
        for sid, ev in sports_events.items():
            if not isinstance(ev, dict) or ev.get("settled"):
                continue
            try:
                if _parse_dt_safe(ev.get("commence_time", "")) <= now:
                    pending_events.append((sid, ev))
            except Exception:
                pass
        pending_events.sort(key=lambda x: x[1].get("commence_time", ""))

        settle_rows = ""
        for sid, ev in pending_events:
            sport_emoji = {"NFL": "🏈", "NBA": "🏀", "MLB": "⚾", "NHL": "🏒",
                           "KBO": "⚾", "NPB": "⚾", "UFC": "🥊"}.get(ev.get("sport", ""), "🏆")
            matchup = html.escape(f"{ev.get('away', '?')} @ {ev.get('home', '?')}")
            home_lbl = html.escape(ev.get("home", "Home"))
            away_lbl = html.escape(ev.get("away", "Away"))
            ct = _parse_dt_safe(ev.get("commence_time", ""))
            try:
                ct_str = ct.strftime("%a %b %-d %-I:%M %p UTC")
            except ValueError:
                ct_str = ct.strftime("%a %b %d %I:%M %p UTC")
            open_bets = sum(
                1 for b in sports_bets
                if isinstance(b, dict) and b.get("game_id") == sid and not b.get("settled")
            )
            open_parlays = sum(
                1 for p in sports_parlays
                if isinstance(p, dict) and not p.get("settled")
                and any(lg.get("game_id") == sid for lg in (p.get("legs") or []))
            )
            bet_info = f"{open_bets} bet{'s' if open_bets != 1 else ''}"
            if open_parlays:
                bet_info += f", {open_parlays} parlay{'s' if open_parlays != 1 else ''}"

            is_ufc = ev.get("sport") == "UFC"
            sport_key = html.escape(ev.get("sport", ""))
            safe_matchup = matchup.replace("'", "\\'")
            if is_ufc:
                score_fields = (
                    f"<select name='winner' style='max-width:180px;font-size:.85em'>"
                    f"<option value='home'>{home_lbl}</option>"
                    f"<option value='away'>{away_lbl}</option>"
                    f"</select>"
                )
            else:
                score_fields = (
                    f"<div style='display:flex;align-items:center;gap:4px'>"
                    f"<span class='muted' style='font-size:.78em'>Away</span>"
                    f"<input type='number' name='away_score' min='0' step='1' "
                    f"style='width:52px;text-align:center;padding:4px 6px'>"
                    f"<span class='muted' style='font-size:.9em'>–</span>"
                    f"<input type='number' name='home_score' min='0' step='1' "
                    f"style='width:52px;text-align:center;padding:4px 6px'>"
                    f"<span class='muted' style='font-size:.78em'>Home</span>"
                    f"</div>"
                )

            bet_cls = "yellow" if open_bets or open_parlays else "muted"
            settle_rows += (
                f"<tr>"
                f"<td style='white-space:nowrap'>{sport_emoji} <b>#{sid}</b><br>"
                f"<span class='muted' style='font-size:.75em'>{ct_str}</span></td>"
                f"<td>{matchup}</td>"
                f"<td style='white-space:nowrap'><span class='{bet_cls}'>{bet_info}</span></td>"
                f"<td>"
                f"<form method='post' action='/api/settlegame' "
                f"style='display:flex;gap:8px;align-items:center;flex-wrap:nowrap'>"
                f"<input type='hidden' name='game_id' value='{sid}'>"
                f"<input type='hidden' name='sport' value='{sport_key}'>"
                f"{score_fields}"
                f"<button type='submit' name='action' value='Settle' class='btn' style='white-space:nowrap' "
                f"onclick=\"return confirm('Settle #{sid}?')\">Settle</button>"
                f"<button type='submit' name='action' value='Refund' class='btn danger' style='white-space:nowrap;font-size:.82em' "
                f"onclick=\"return confirm('Refund all bets on #{sid}?')\">Refund</button>"
                f"</form>"
                f"</td>"
                f"</tr>"
            )

        if not settle_rows:
            settle_rows = "<tr><td colspan=4 class='muted' style='text-align:center;padding:16px'>No games awaiting settlement.</td></tr>"

        body = f"""{msg}
<h2>Pending Settlement</h2>
<p class="muted">Games past their start time that haven't been settled yet. Enter the final score and click <b>Settle</b>, or <b>Refund</b> to return all wagers.</p>
<div style="overflow-x:auto">
<table style="min-width:700px">
  <thead><tr><th style="width:130px">Game</th><th>Matchup</th><th style="width:100px">Bets</th><th>Score &amp; Action</th></tr></thead>
  <tbody>{settle_rows}</tbody>
</table>
</div>

<div class="panel" style="margin-top:20px">
  <h2 style="margin-top:0">Sport Toggles</h2>
  <p class="muted">Disabled sports won't appear in <code>!odds</code> and new bets will be rejected. Existing open bets still settle normally.</p>
  <form method="post" action="/api/sportsconfig">
    <table>
      <thead><tr><th>Sport</th><th>Status</th><th>Toggle</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <div style="margin-top:14px"><input type="submit" class="btn" value="Save Changes"></div>
  </form>
</div>

<h2>Open Bets by Sport</h2>
<table>
  <thead><tr><th>Sport</th><th>Open Straight Bets</th><th>Open Parlay Legs</th></tr></thead>
  <tbody>{stats_rows}</tbody>
</table>"""
        return _page("Sports Betting", body)

    async def handle_sportsconfig_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        data = await request.post()
        enabled = {key for key in _ALL_SPORTS if data.get(f"sport_{key}") == "1"}
        disabled = [key for key in _ALL_SPORTS if key not in enabled]
        eco = load_eco()
        eco.setdefault("sports_config", {})["disabled_sports"] = disabled
        save_eco(eco)
        log_event("WARN", f"[Admin] Sports config updated — disabled: {disabled or 'none'}")
        msg = "All sports enabled." if not disabled else f"Disabled: {', '.join(disabled)}"
        return aiohttp.web.HTTPFound(f"/sports?ok={msg.replace(' ', '+')}")

    async def handle_settlegame_api(request):
        if not _check_auth(request):
            return aiohttp.web.HTTPFound("/login")
        from cogs.sports import _settle_event, _settle_parlays, _init_sports
        data = await request.post()
        game_id = data.get("game_id", "").strip()
        action = data.get("action", "Settle")
        sport = data.get("sport", "")
        if not game_id:
            return aiohttp.web.HTTPFound("/sports?err=Missing+game+ID")

        eco = load_eco()
        _init_sports(eco)
        ev = eco["sports_events"].get(game_id)
        if not ev:
            return aiohttp.web.HTTPFound(f"/sports?err=Game+%23{game_id}+not+found")
        if ev.get("settled"):
            return aiohttp.web.HTTPFound(f"/sports?err=Game+%23{game_id}+is+already+settled")

        matchup = f"{ev.get('away','?')} @ {ev.get('home','?')}"

        if action == "Refund":
            _settle_event(eco, game_id, 0, 0)
            ev["status"] = "cancelled"
            ev["home_score"] = None
            ev["away_score"] = None
            _settle_parlays(eco, game_id)
            save_eco(eco)
            log_event("WARN", f"[Admin] Refunded game #{game_id}: {matchup}")
            return aiohttp.web.HTTPFound(f"/sports?ok=Refunded+all+bets+on+%23{game_id}+{matchup.replace(' ', '+')}")

        # Settle with scores
        if sport == "UFC":
            winner = data.get("winner", "home")
            hs = 1.0 if winner == "home" else 0.0
            as_ = 0.0 if winner == "home" else 1.0
        else:
            try:
                hs = float(data.get("home_score", "").strip())
                as_ = float(data.get("away_score", "").strip())
            except (ValueError, AttributeError):
                return aiohttp.web.HTTPFound(f"/sports?err=Invalid+scores+for+%23{game_id}")

        _settle_event(eco, game_id, hs, as_)
        _settle_parlays(eco, game_id)
        save_eco(eco)
        score_str = f"{int(as_)}–{int(hs)}" if sport != "UFC" else f"{'home' if hs > as_ else 'away'} wins"
        log_event("WARN", f"[Admin] Settled game #{game_id}: {matchup} ({score_str})")
        return aiohttp.web.HTTPFound(
            f"/sports?ok=Settled+%23{game_id}+{matchup.replace(' ', '+')}+%28{score_str.replace(' ', '+')}%29"
        )

    # ── Wire up routes ────────────────────────────────────────────────────────

    @aiohttp.web.middleware
    async def error_middleware(request, handler):
        try:
            return await handler(request)
        except aiohttp.web.HTTPException:
            raise
        except Exception:
            traceback.print_exc()
            return aiohttp.web.Response(status=500, text="500 Internal Server Error — check bot terminal for details")

    app = aiohttp.web.Application(middlewares=[error_middleware])
    app.router.add_get("/login", handle_login_get)
    app.router.add_post("/login", handle_login_post)
    app.router.add_get("/logout", handle_logout)
    app.router.add_get("/", handle_dashboard)
    app.router.add_post("/api/settarget", handle_settarget_api)
    app.router.add_post("/api/settargetbio", handle_settargetbio_api)
    app.router.add_get("/economy", handle_economy)
    app.router.add_post("/api/coins", handle_coins_api)
    app.router.add_get("/shop", handle_shop)
    app.router.add_post("/api/resetshop", handle_resetshop_api)
    app.router.add_get("/stocks", handle_stocks)
    app.router.add_post("/api/setprice", handle_setprice_api)
    app.router.add_post("/api/triggerevent", handle_triggerevent_api)
    app.router.add_post("/api/triggerdividends", handle_triggerdividends_api)
    app.router.add_post("/api/deliststock", handle_deliststock_api)
    app.router.add_post("/api/removestock", handle_removestock_api)
    app.router.add_get("/user/{uid}", handle_user)
    app.router.add_get("/messages", handle_messages)
    app.router.add_post("/api/sendmessage", handle_sendmessage_api)
    app.router.add_get("/sports", handle_sports)
    app.router.add_post("/api/sportsconfig", handle_sportsconfig_api)
    app.router.add_post("/api/settlegame", handle_settlegame_api)
    app.router.add_get("/logs", handle_logs)
    app.router.add_post("/api/clearlogs", handle_clearlogs_api)
    app.router.add_get("/logs/clearbuffer", handle_clearbuffer_api)
    app.router.add_get("/logs/clearfile", handle_clearfile_api)
    app.router.add_get("/logs/download", handle_download_log)
    return app
