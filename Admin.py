import json
import base64
import logging
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode

BOT_TOKEN     = "8901957402:AAH0JWNeYvNI2r2U4R7NFjfKTW_y9JtrqlA"
GITHUB_TOKEN  = "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"
GITHUB_OWNER  = "hdhdjdjdhdh3"
GITHUB_REPO   = "Test1"
GITHUB_BRANCH = "main"
GITHUB_PATH = "test1.json"
ALLOWED_IDS   = {6874767181 }

CACHE = {"data": None, "sha": None, "timestamp": None}
CACHE_TTL = 25

(
    S_SEARCH,
    S_EDIT_DEVICE, S_EDIT_KEY, S_EDIT_EXPIRY_CUSTOM,
    S_ADD_DEVICE,  S_ADD_KEY,  S_ADD_EXPIRY_CUSTOM,
) = range(7)

logging.basicConfig(format="%(asctime)s  %(levelname)-8s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_PATH}"
_GH_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

def gh_read() -> tuple[list, str]:
    if (CACHE["data"] is not None and CACHE["timestamp"] and 
        (datetime.now() - CACHE["timestamp"]).seconds < CACHE_TTL):
        return CACHE["data"], CACHE["sha"]

    r = requests.get(_API_URL, headers=_GH_HEADERS, timeout=10)
    r.raise_for_status()
    d = r.json()
    data = json.loads(base64.b64decode(d["content"]).decode())
    
    CACHE["data"] = data
    CACHE["sha"] = d["sha"]
    CACHE["timestamp"] = datetime.now()
    return data, d["sha"]

def gh_write(data: list, sha: str, commit: str = "Update via LicenseBot") -> bool:
    payload = {
        "message": commit,
        "content": base64.b64encode(
            json.dumps(data, indent=2, ensure_ascii=False).encode()
        ).decode(),
        "sha": sha,
        "branch": GITHUB_BRANCH,
    }
    r = requests.put(_API_URL, headers=_GH_HEADERS, json=payload, timeout=15)
    if r.status_code in (200, 201):
        CACHE["data"] = None
        return True
    return False

def allowed(uid: int) -> bool:
    return uid in ALLOWED_IDS

async def guard(update: Update) -> bool:
    if not allowed(update.effective_user.id):
        await update.effective_message.reply_text("⛔ Access denied.")
        return False
    return True

DATE_FMT = "%d-%m-%Y"

def parse_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s.strip(), DATE_FMT)
    except ValueError:
        return None

def fmt_date(dt: datetime) -> str:
    return dt.strftime(DATE_FMT)

def days_left(expiry_str: str) -> str:
    dt = parse_date(expiry_str)
    if not dt:
        return "?"
    diff = (dt - datetime.now()).days
    if diff < 0:
        return f"⛔ Expired {abs(diff)}d ago"
    if diff == 0:
        return "⚠️ Expires TODAY"
    if diff <= 7:
        return f"⚠️ {diff}d left"
    return f"✅ {diff}d left"

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 All Licenses", callback_data="list_0"),
            InlineKeyboardButton("🔍 Search", callback_data="search"),
        ],
        [
            InlineKeyboardButton("➕ Add License", callback_data="add"),
            InlineKeyboardButton("🗑 Delete", callback_data="delete_menu"),
        ],
        [
            InlineKeyboardButton("📊 Dashboard", callback_data="stats"),
        ],
    ])

def kb_license(idx: int, total: int, offline: bool) -> InlineKeyboardMarkup:
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"list_{idx-1}"))
    nav.append(InlineKeyboardButton(f"• {idx+1}/{total} •", callback_data="noop"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"list_{idx+1}"))

    offline_label = "📡 Offline: ON ✅" if offline else "📡 Offline: OFF ❌"

    return InlineKeyboardMarkup([
        nav,
        [
            InlineKeyboardButton("✏️ Edit Device ID", callback_data=f"edit_dev_{idx}"),
            InlineKeyboardButton("🔑 Edit Key", callback_data=f"edit_key_{idx}"),
        ],
        [
            InlineKeyboardButton("📅 Change Expiry", callback_data=f"expiry_menu_{idx}"),
            InlineKeyboardButton(offline_label, callback_data=f"toggle_off_{idx}"),
        ],
        [
            InlineKeyboardButton("🗑 Delete This", callback_data=f"del_confirm_{idx}"),
            InlineKeyboardButton("🏠 Home", callback_data="home"),
        ],
    ])

def kb_expiry(idx: int) -> InlineKeyboardMarkup:
    now = datetime.now()
    presets = [
        ("+7 Days",   fmt_date(now + timedelta(days=7))),
        ("+30 Days",  fmt_date(now + timedelta(days=30))),
        ("+90 Days",  fmt_date(now + timedelta(days=90))),
        ("+180 Days", fmt_date(now + timedelta(days=180))),
        ("+1 Year",   fmt_date(now + timedelta(days=365))),
        ("+2 Years",  fmt_date(now + timedelta(days=730))),
    ]
    rows = []
    for label, date_str in presets:
        rows.append([InlineKeyboardButton(
            f"🌈 {label} → {date_str}", 
            callback_data=f"expiry_set_{idx}_{date_str}"
        )])
    rows.append([InlineKeyboardButton("⌨️ Custom Date", callback_data=f"expiry_custom_{idx}")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data=f"list_{idx}")])
    return InlineKeyboardMarkup(rows)

def kb_delete_menu(licenses: list) -> InlineKeyboardMarkup:
    rows = []
    for i, lic in enumerate(licenses):
        did = lic.get("device_id", "???")[:25]
        rows.append([InlineKeyboardButton(
            f"🗑 [{i+1}] {did}", callback_data=f"del_confirm_{i}"
        )])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def kb_confirm_del(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, Delete", callback_data=f"del_do_{idx}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"list_{idx}"),
    ]])

def kb_back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Home", callback_data="home")]])

def render_card(lic: dict, idx: int, total: int) -> str:
    exp_str = lic.get("expirydate", "")
    status = days_left(exp_str)
    offline = "✅ Allowed" if lic.get("Allowoffline") else "❌ Disabled"

    dt = parse_date(exp_str)
    filled = min(10, max(0, (dt - datetime.now()).days // 36)) if dt else 0
    bar = "█" * filled + "░" * (10 - filled)

    return (
        f"┌─────────────────────────────┐\n"
        f"│  🪪  <b>License {idx+1}/{total}</b>\n"
        f"├─────────────────────────────┤\n"
        f"│ 📟 <b>Device ID</b>\n│ <code>{lic.get('device_id', '—')}</code>\n│\n"
        f"│ 🔑 <b>Key</b>\n│ <code>{lic.get('key', '—')}</code>\n│\n"
        f"│ 📅 <b>Expiry</b>  ·  {exp_str or '—'}\n"
        f"│ [{bar}]  {status}\n│\n"
        f"│ 📡 <b>Offline</b>  ·  {offline}\n"
        f"└─────────────────────────────┘"
    )

def render_stats(licenses: list) -> str:
    total = len(licenses)
    active = sum(1 for l in licenses if (parse_date(l.get("expirydate", "")) or datetime.min) >= datetime.now())
    expiring_soon = sum(1 for l in licenses if 0 <= ((parse_date(l.get("expirydate", "")) or datetime.min) - datetime.now()).days <= 7)
    offline_on = sum(1 for l in licenses if l.get("Allowoffline", False))

    return (
        f"📊 <b>Dashboard</b>\n\n"
        f"📋 Total Licenses   : <b>{total}</b>\n"
        f"✅ Active           : <b>{active}</b>\n"
        f"⛔ Expired          : <b>{total - active}</b>\n"
        f"⚠️ Expiring ≤7d     : <b>{expiring_soon}</b>\n"
        f"📡 Offline Allowed  : <b>{offline_on}</b>\n\n"
        f"<i>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>"
    )

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not allowed(q.from_user.id):
        return await q.edit_message_text("⛔ Access denied.")

    d = q.data

    if d == "noop":
        return

    if d == "home":
        await q.edit_message_text(
            "🔐 <b>License Manager</b> v2.1\n\nSelect an action below.",
            parse_mode=ParseMode.HTML, reply_markup=kb_main()
        )
        return ConversationHandler.END

    if d == "stats":
        try:
            lics, _ = gh_read()
            await q.edit_message_text(
                render_stats(lics), parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("👥 View Licenses", callback_data="list_0"),
                    InlineKeyboardButton("🏠 Home", callback_data="home"),
                ]])
            )
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=kb_back_home())
        return

    if d.startswith("list_"):
        idx = int(d.split("_")[1])
        try:
            lics, _ = gh_read()
            if not lics:
                return await q.edit_message_text("📭 No licenses found.", reply_markup=kb_main())
            idx = max(0, min(idx, len(lics) - 1))
            await q.edit_message_text(
                render_card(lics[idx], idx, len(lics)),
                parse_mode=ParseMode.HTML,
                reply_markup=kb_license(idx, len(lics), lics[idx].get("Allowoffline", False))
            )
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=kb_back_home())
        return

    if d == "search":
        ctx.user_data.clear()
        await q.edit_message_text(
            "🔍 <b>Search License</b>\n\nSend any part of Device ID, Key or Expiry date:",
            parse_mode=ParseMode.HTML, reply_markup=kb_back_home()
        )
        return S_SEARCH

    if d == "delete_menu":
        try:
            lics, _ = gh_read()
        except Exception as e:
            return await q.edit_message_text(f"❌ Error: {e}", reply_markup=kb_back_home())
        if not lics:
            return await q.edit_message_text("📭 Nothing to delete.", reply_markup=kb_main())
        await q.edit_message_text(
            "🗑 <b>Select license to delete:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_delete_menu(lics)
        )
        return

    if d.startswith("del_confirm_"):
        idx = int(d.split("_")[2])
        try:
            lics, _ = gh_read()
            lic = lics[idx]
        except Exception as e:
            return await q.edit_message_text(f"❌ Error: {e}", reply_markup=kb_back_home())
        await q.edit_message_text(
            f"⚠️ <b>Confirm Delete</b>\n\n"
            f"Device: <code>{lic.get('device_id')}</code>\n"
            f"Key: <code>{lic.get('key')}</code>\n\n"
            f"This action cannot be undone!",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_confirm_del(idx)
        )
        return

    if d.startswith("del_do_"):
        idx = int(d.split("_")[2])
        try:
            lics, sha = gh_read()
            removed = lics.pop(idx)
            if gh_write(lics, sha, f"Delete {removed.get('device_id','')}"):
                await q.edit_message_text(
                    f"✅ Deleted <code>{removed.get('device_id','')}</code>",
                    parse_mode=ParseMode.HTML, reply_markup=kb_main()
                )
            else:
                await q.edit_message_text("❌ GitHub write failed.", reply_markup=kb_back_home())
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=kb_back_home())
        return

    if d.startswith("toggle_off_"):
        idx = int(d.split("_")[2])
        try:
            lics, sha = gh_read()
            lics[idx]["Allowoffline"] = not lics[idx].get("Allowoffline", False)
            if gh_write(lics, sha, f"Toggle offline - {lics[idx]['device_id']}"):
                await q.edit_message_text(
                    render_card(lics[idx], idx, len(lics)),
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb_license(idx, len(lics), lics[idx]["Allowoffline"])
                )
            else:
                await q.edit_message_text("❌ GitHub write failed.", reply_markup=kb_back_home())
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=kb_back_home())
        return

    if d.startswith("expiry_menu_"):
        idx = int(d.split("_")[2])
        try:
            lics, _ = gh_read()
            cur = lics[idx].get("expirydate", "—")
        except Exception as e:
            return await q.edit_message_text(f"❌ Error: {e}", reply_markup=kb_back_home())
        await q.edit_message_text(
            f"📅 <b>Change Expiry</b>\n\nCurrent: <code>{cur}</code>  {days_left(cur)}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_expiry(idx)
        )
        return

    if d.startswith("expiry_set_"):
        parts = d.split("_", 3)
        idx, date_str = int(parts[2]), parts[3]
        try:
            lics, sha = gh_read()
            lics[idx]["expirydate"] = date_str
            if gh_write(lics, sha, f"Set expiry {date_str}"):
                await q.edit_message_text(
                    render_card(lics[idx], idx, len(lics)),
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb_license(idx, len(lics), lics[idx].get("Allowoffline", False))
                )
            else:
                await q.edit_message_text("❌ GitHub write failed.", reply_markup=kb_back_home())
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=kb_back_home())
        return

    if d.startswith("expiry_custom_"):
        idx = int(d.split("_")[2])
        ctx.user_data["edit_idx"] = idx
        await q.edit_message_text(
            "⌨️ <b>Custom Expiry Date</b>\n\nFormat: <code>DD-MM-YYYY</code>\nExample: <code>31-12-2027</code>",
            parse_mode=ParseMode.HTML, reply_markup=kb_back_home()
        )
        return S_EDIT_EXPIRY_CUSTOM

    if d.startswith("edit_dev_"):
        idx = int(d.split("_")[2])
        ctx.user_data["edit_idx"] = idx
        await q.edit_message_text(
            "✏️ <b>Edit Device ID</b>\n\nSend new Device ID:",
            parse_mode=ParseMode.HTML, reply_markup=kb_back_home()
        )
        return S_EDIT_DEVICE

    if d.startswith("edit_key_"):
        idx = int(d.split("_")[2])
        ctx.user_data["edit_idx"] = idx
        await q.edit_message_text(
            "🔑 <b>Edit Key</b>\n\nSend new Key:",
            parse_mode=ParseMode.HTML, reply_markup=kb_back_home()
        )
        return S_EDIT_KEY

    if d == "add":
        ctx.user_data.clear()
        ctx.user_data["new"] = {}
        await q.edit_message_text(
            "➕ <b>Add License (1/3)</b>\n\nSend Device ID:",
            parse_mode=ParseMode.HTML, reply_markup=kb_back_home()
        )
        return S_ADD_DEVICE

async def msg_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    q = update.message.text.strip().lower()
    try:
        lics, _ = gh_read()
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=kb_main())
        return ConversationHandler.END

    hits = [(i, l) for i, l in enumerate(lics) if q in json.dumps(l).lower()]
    if not hits:
        await update.message.reply_text(f"🔍 No results for <code>{q}</code>", parse_mode=ParseMode.HTML, reply_markup=kb_main())
        return ConversationHandler.END

    await update.message.reply_text(f"🔍 <b>{len(hits)} result(s)</b> for <code>{q}</code>", parse_mode=ParseMode.HTML)
    for i, lic in hits:
        await update.message.reply_text(
            render_card(lic, i, len(lics)),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_license(i, len(lics), lic.get("Allowoffline", False))
        )
    return ConversationHandler.END

async def msg_edit_device(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    idx = ctx.user_data.get("edit_idx", 0)
    val = update.message.text.strip()
    try:
        lics, sha = gh_read()
        old = lics[idx].get("device_id", "")
        lics[idx]["device_id"] = val
        if gh_write(lics, sha, f"Edit device {old} → {val}"):
            await update.message.reply_text(
                f"✅ Device ID updated!\n\n{render_card(lics[idx], idx, len(lics))}",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_license(idx, len(lics), lics[idx].get("Allowoffline", False))
            )
        else:
            await update.message.reply_text("❌ GitHub write failed.", reply_markup=kb_main())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=kb_main())
    return ConversationHandler.END

async def msg_edit_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    idx = ctx.user_data.get("edit_idx", 0)
    val = update.message.text.strip()
    try:
        lics, sha = gh_read()
        lics[idx]["key"] = val
        if gh_write(lics, sha, f"Edit key - {lics[idx]['device_id']}"):
            await update.message.reply_text(
                f"✅ Key updated!\n\n{render_card(lics[idx], idx, len(lics))}",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_license(idx, len(lics), lics[idx].get("Allowoffline", False))
            )
        else:
            await update.message.reply_text("❌ GitHub write failed.", reply_markup=kb_main())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=kb_main())
    return ConversationHandler.END

async def msg_edit_expiry_custom(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    val = update.message.text.strip()
    if not parse_date(val):
        await update.message.reply_text("⚠️ Wrong format! Use <code>DD-MM-YYYY</code>", parse_mode=ParseMode.HTML)
        return S_EDIT_EXPIRY_CUSTOM
    idx = ctx.user_data.get("edit_idx", 0)
    try:
        lics, sha = gh_read()
        lics[idx]["expirydate"] = val
        if gh_write(lics, sha, f"Set expiry {val}"):
            await update.message.reply_text(
                f"✅ Expiry updated!\n\n{render_card(lics[idx], idx, len(lics))}",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_license(idx, len(lics), lics[idx].get("Allowoffline", False))
            )
        else:
            await update.message.reply_text("❌ GitHub write failed.", reply_markup=kb_main())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=kb_main())
    return ConversationHandler.END

async def msg_add_device(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    ctx.user_data["new"]["device_id"] = update.message.text.strip()
    await update.message.reply_text(
        "➕ <b>Add License (2/3)</b>\n\nSend the Key:",
        parse_mode=ParseMode.HTML, reply_markup=kb_back_home()
    )
    return S_ADD_KEY

async def msg_add_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    ctx.user_data["new"]["key"] = update.message.text.strip()
    await update.message.reply_text(
        "➕ <b>Add License (3/3)</b>\n\nSend expiry date <code>DD-MM-YYYY</code>",
        parse_mode=ParseMode.HTML, reply_markup=kb_back_home()
    )
    return S_ADD_EXPIRY_CUSTOM

async def msg_add_expiry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    val = update.message.text.strip()
    if not parse_date(val):
      
