"""
🎶 Яндекс музыка — Telegram Music Bot
"""

from __future__ import annotations

import json
import logging
import random
import asyncio
import subprocess
import time
from pathlib import Path

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, InputMediaPhoto, InputMediaVideo,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from ytmusicapi import YTMusic
import yt_dlp

# ═══════════════════════════════════════════════════
#  НАСТРОЙКИ
# ═══════════════════════════════════════════════════

BOT_TOKEN = "8617995058:AAEfzyouPEB0iECaBXOHKoNKODjxyvmmAjE"

ADMIN_ID = 8535260202  # ← замени на свой Telegram ID (узнать у @userinfobot)

# ═══════════════════════════════════════════════════
#  ОБЯЗАТЕЛЬНАЯ ПОДПИСКА
# ═══════════════════════════════════════════════════

CHANNEL_USERNAME = "FamelonovDev"
CHANNEL_LINK = "https://t.me/FamelonovDev"

DOWNLOADS    = Path("downloads")
DOWNLOADS.mkdir(exist_ok=True)
FAV_FILE     = Path("favorites.json")
USERS_FILE   = Path("users.json")
COOKIES_FILE = Path("cookies.txt")

SEARCH_PER_PAGE = 5
SEARCH_LIMIT    = 100
WAVE_SIZE       = 10

ytmusic = YTMusic()

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
#  ИЗБРАННОЕ
# ═══════════════════════════════════════════════════

def _db() -> dict:
    if FAV_FILE.exists():
        return json.loads(FAV_FILE.read_text("utf-8"))
    return {}

def _db_save(d: dict):
    FAV_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")

def fav_list(uid: int) -> list[dict]:
    return _db().get(str(uid), [])

def fav_add(uid: int, t: dict) -> bool:
    d = _db(); k = str(uid)
    d.setdefault(k, [])
    if any(x["id"] == t["id"] for x in d[k]):
        return False
    d[k].append(t)
    _db_save(d)
    return True

def fav_rm(uid: int, vid: str):
    d = _db(); k = str(uid)
    if k in d:
        d[k] = [x for x in d[k] if x["id"] != vid]
        _db_save(d)

def fav_ok(uid: int, vid: str) -> bool:
    return any(x["id"] == vid for x in fav_list(uid))

# ═══════════════════════════════════════════════════
#  УЧЁТ ПОЛЬЗОВАТЕЛЕЙ
# ═══════════════════════════════════════════════════

def _udb() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text("utf-8"))
    return {"users": {}, "total_searches": 0, "total_downloads": 0}

def _udb_save(d: dict):
    USERS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")

def users_register(uid: int, username: str = "", first_name: str = ""):
    d = _udb(); k = str(uid)
    if k not in d["users"]:
        d["users"][k] = {
            "username": username,
            "first_name": first_name,
            "joined": int(time.time()),
            "searches": 0,
            "downloads": 0,
        }
    else:
        d["users"][k]["username"] = username
        d["users"][k]["first_name"] = first_name
    _udb_save(d)

def users_inc_search(uid: int):
    d = _udb(); k = str(uid)
    d["users"].setdefault(k, {})
    d["users"][k]["searches"] = d["users"][k].get("searches", 0) + 1
    d["total_searches"] = d.get("total_searches", 0) + 1
    _udb_save(d)

def users_inc_dl(uid: int):
    d = _udb(); k = str(uid)
    d["users"].setdefault(k, {})
    d["users"][k]["downloads"] = d["users"][k].get("downloads", 0) + 1
    d["total_downloads"] = d.get("total_downloads", 0) + 1
    _udb_save(d)

def users_all_ids() -> list[int]:
    return [int(k) for k in _udb().get("users", {}).keys()]

def users_stats() -> dict:
    d = _udb()
    return {
        "total": len(d.get("users", {})),
        "searches": d.get("total_searches", 0),
        "downloads": d.get("total_downloads", 0),
    }

# ═══════════════════════════════════════════════════
#  YOUTUBE MUSIC — ПОИСК / ВОЛНА
# ═══════════════════════════════════════════════════

def yt_search(query: str, limit: int = SEARCH_LIMIT) -> list[dict]:
    try:
        raw = ytmusic.search(query, filter="songs", limit=limit)
    except Exception as e:
        log.error("search: %s", e); return []
    out = []
    for r in raw[:limit]:
        vid = r.get("videoId")
        if not vid: continue
        artists = ", ".join(a["name"] for a in r.get("artists", [])) or "—"
        out.append({
            "id": vid,
            "title": r.get("title", "—"),
            "artist": artists,
            "dur": r.get("duration", ""),
        })
    return out


def yt_wave(uid: int) -> list[dict]:
    favs = fav_list(uid)
    if not favs:
        q = random.choice(["top hits 2025", "хиты 2025", "trending songs", "лучшие треки"])
        return yt_search(q, WAVE_SIZE)

    wave: list[dict] = []
    seeds = random.sample(favs, min(3, len(favs)))
    seen = {f["id"] for f in favs}

    for s in seeds:
        try:
            pl = ytmusic.get_watch_playlist(videoId=s["id"], limit=25)
            for t in pl.get("tracks", [])[1:]:
                vid = t.get("videoId")
                if not vid or vid in seen: continue
                seen.add(vid)
                wave.append({
                    "id": vid,
                    "title": t.get("title", "—"),
                    "artist": ", ".join(a["name"] for a in t.get("artists", [])) or "—",
                    "dur": t.get("duration", ""),
                })
        except Exception as e:
            log.error("wave: %s", e)

    random.shuffle(wave)
    return wave[:WAVE_SIZE]

# ═══════════════════════════════════════════════════
#  СКАЧИВАНИЕ
# ═══════════════════════════════════════════════════

def _clean(vid: str):
    for f in DOWNLOADS.glob(f"{vid}*"):
        try: f.unlink()
        except: pass

def _find(vid: str):
    for ext in (".mp3", ".m4a", ".opus", ".ogg", ".webm"):
        p = DOWNLOADS / f"{vid}{ext}"
        if p.exists() and p.stat().st_size > 10000:
            return p
    return None

def _base_opts(vid: str) -> dict:
    return {
        "format": "bestaudio/best",
        "outtmpl": str(DOWNLOADS / f"{vid}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "geo_bypass": True,
    }

def _dl_soundcloud(vid: str, title: str, artist: str) -> Path | None:
    query = f"{artist} - {title}" if artist and artist != "—" else title
    opts = _base_opts(vid)
    try:
        log.info("[soundcloud] %s", query)
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([f"scsearch1:{query}"])
        p = _find(vid)
        if p:
            log.info("✅ SoundCloud OK")
            return p
    except Exception as e:
        log.warning("[soundcloud] %s", str(e)[:120])
    return None

def _dl_youtube(vid: str) -> Path | None:
    cookie = str(COOKIES_FILE) if COOKIES_FILE.exists() else None
    configs = [
        ("android", {"extractor_args": {"youtube": {"player_client": ["android"]}}}),
        ("ios", {"extractor_args": {"youtube": {"player_client": ["ios"]}}}),
        ("android+cookies", {"cookiefile": cookie, "extractor_args": {"youtube": {"player_client": ["android"]}}}),
        ("web+cookies", {"cookiefile": cookie}),
    ]
    url = f"https://www.youtube.com/watch?v={vid}"
    for name, extra in configs:
        _clean(vid)
        opts = {**_base_opts(vid), **extra, "no_check_formats": True}
        try:
            log.info("[yt-dlp] %s: %s", name, vid)
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([url])
            p = _find(vid)
            if p:
                log.info("✅ yt-dlp OK (%s)", name)
                return p
        except Exception as e:
            log.warning("[yt-dlp] %s: %s", name, str(e)[:80])
        time.sleep(1)
    return None

def yt_dl(vid: str, title: str = "", artist: str = "") -> Path | None:
    _clean(vid)
    if title:
        path = _dl_soundcloud(vid, title, artist)
        if path: return path
    path = _dl_youtube(vid)
    if path: return path
    log.error("❌ Не удалось: %s (%s — %s)", vid, artist, title)
    return None

# ═══════════════════════════════════════════════════
#  ПРОВЕРКА ПОДПИСКИ
# ═══════════════════════════════════════════════════

async def is_subscribed(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(
            chat_id=f"@{CHANNEL_USERNAME}" if not str(CHANNEL_USERNAME).lstrip("-").isdigit() else int(CHANNEL_USERNAME),
            user_id=user_id,
        )
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        log.warning("sub check error: %s", e)
        return False

async def _send_sub_required(bot, chat_id: int, message_id: int | None = None):
    text = (
        "🔒 <b>Доступ закрыт</b>\n\n"
        "Чтобы пользоваться ботом, подпишитесь на наш канал.\n"
        "После подписки нажмите кнопку <b>✅ Проверить</b>."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub")],
    ])
    if message_id:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id,
                parse_mode="HTML", reply_markup=kb,
            )
            return
        except:
            pass
    await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

# ═══════════════════════════════════════════════════
#  UI HELPERS
# ═══════════════════════════════════════════════════

CUT = 38

def _cut(s: str) -> str:
    return s if len(s) <= CUT else s[:CUT - 1] + "…"

async def _ed(target, text: str, kb=None):
    try:
        if hasattr(target, "message"):
            await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        else:
            bot, cid, mid = target
            await bot.edit_message_text(text, chat_id=cid, message_id=mid,
                                        reply_markup=kb, parse_mode="HTML")
    except: pass

# ═══════════════════════════════════════════════════
#  ЭКРАНЫ
# ═══════════════════════════════════════════════════

MENU_TEXT = "<b>🎶 Muss Music</b>"
MENU_KB  = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔎 Поиск",     callback_data="search")],
    [InlineKeyboardButton("❤️ Избранное", callback_data="favs")],
    [InlineKeyboardButton("🌊 Моя волна", callback_data="wave")],
])

ADMIN_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("📊 Статистика", callback_data="adm_stats")],
    [InlineKeyboardButton("📣 Рассылка",   callback_data="adm_broadcast")],
])


async def _show_search_results(target, ctx, page=0):
    items = ctx.user_data.get("res", [])
    query = ctx.user_data.get("query", "")
    total = len(items)

    if not items:
        await _ed(target, "<b>🔍 Ничего не найдено</b>",
                  InlineKeyboardMarkup([
                      [InlineKeyboardButton("🔎 Поиск", callback_data="search")],
                      [InlineKeyboardButton("🏠", callback_data="home")]]))
        return

    pages = (total - 1) // SEARCH_PER_PAGE + 1
    page  = max(0, min(page, pages - 1))
    ctx.user_data["spage"] = page

    s = page * SEARCH_PER_PAGE
    chunk = items[s:s + SEARCH_PER_PAGE]

    text = f"<b>🎶 {query} — {total} треков</b>"
    b = []
    for i, tr in enumerate(chunk):
        label = _cut(f"{tr['artist']} — {tr['title']}")
        b.append([InlineKeyboardButton(label, callback_data=f"sr_{s + i}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("🔙", callback_data="sprev"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("🔜", callback_data="snext"))
    b.append(nav)

    await _ed(target, text, InlineKeyboardMarkup(b))


async def _show_favs(target, uid, page=0):
    items = fav_list(uid)
    if not items:
        await _ed(target, "<b>❤️ Избранное пусто</b>",
                  InlineKeyboardMarkup([[InlineKeyboardButton("🏠", callback_data="home")]]))
        return
    pages = (len(items) - 1) // SEARCH_PER_PAGE + 1
    page  = max(0, min(page, pages - 1))
    s = page * SEARCH_PER_PAGE
    chunk = items[s:s + SEARCH_PER_PAGE]
    text = f"<b>❤️ Избранное — {len(items)} треков</b>"
    b = []
    for i, tr in enumerate(chunk):
        b.append([InlineKeyboardButton(
            _cut(f"{tr['artist']} — {tr['title']}"), callback_data=f"ft_{s + i}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("🔙", callback_data=f"fp_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1: nav.append(InlineKeyboardButton("🔜", callback_data=f"fp_{page+1}"))
    b.append(nav)
    b.append([InlineKeyboardButton("🏠", callback_data="home")])
    await _ed(target, text, InlineKeyboardMarkup(b))


async def _show_wave(target, tr, uid, ctx):
    vid = tr["id"]
    star = "💔" if fav_ok(uid, vid) else "❤️"
    idx   = ctx.user_data.get("wi", 0)
    total = len(ctx.user_data.get("wave", []))
    dur   = f"  •  {tr['dur']}" if tr.get("dur") else ""
    text = (f"<b>🌊 Моя волна  {idx+1}/{total}</b>\n\n"
            f"<b>{tr['title']}</b>\n"
            f"<blockquote>{tr['artist']}{dur}</blockquote>")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏮", callback_data="wp"),
         InlineKeyboardButton("📥", callback_data=f"wd_{vid}"),
         InlineKeyboardButton(star, callback_data=f"wf_{vid}"),
         InlineKeyboardButton("⏭", callback_data="wn")],
        [InlineKeyboardButton("🏠", callback_data="home")],
    ])
    await _ed(target, text, kb)

# ═══════════════════════════════════════════════════
#  АНИМАЦИЯ ЗАГРУЗКИ + СКАЧИВАНИЕ
# ═══════════════════════════════════════════════════

async def _do_dl(q, vid, tr, uid, ctx, wave=False):
    msg = q.message
    chat_id = msg.chat_id
    msg_id  = msg.message_id

    stop_anim = asyncio.Event()

    async def _animate():
        dots = ["", ".", "..", "..."]
        i = 0
        while not stop_anim.is_set():
            text = f"<b>⏳ Скачиваю{dots[i % 4]}</b>"
            try:
                await ctx.bot.edit_message_text(
                    text, chat_id=chat_id, message_id=msg_id,
                    parse_mode="HTML", reply_markup=None)
            except: pass
            i += 1
            try:
                await asyncio.wait_for(stop_anim.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    anim_task = asyncio.create_task(_animate())

    title  = tr.get("title", "")
    artist = tr.get("artist", "")
    path = await asyncio.to_thread(yt_dl, vid, title, artist)

    stop_anim.set()
    await anim_task

    if path:
        try:
            is_fav = fav_ok(uid, vid)
            heart = "💔" if is_fav else "❤️"

            after_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎", callback_data="search"),
                 InlineKeyboardButton(heart, callback_data=f"af_{vid}")],
            ])

            try:
                await ctx.bot.edit_message_text(
                    f"<b>✅ {artist} — {title}</b>",
                    chat_id=chat_id, message_id=msg_id,
                    parse_mode="HTML", reply_markup=None)
            except: pass

            with open(path, "rb") as f:
                sent = await msg.chat.send_audio(
                    audio=f, title=title, performer=artist,
                    reply_markup=after_kb)

            users_inc_dl(uid)
            ctx.user_data["last_track_msg"] = sent.message_id
            ctx.user_data["last_track"] = tr

        except Exception as e:
            log.error("send_audio: %s", e)
        finally:
            try: path.unlink()
            except: pass
    else:
        try:
            await ctx.bot.edit_message_text(
                "<b>❌ Не удалось скачать</b>",
                chat_id=chat_id, message_id=msg_id,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Поиск", callback_data="search"),
                     InlineKeyboardButton("🏠", callback_data="home")]]))
        except: pass

# ═══════════════════════════════════════════════════
#  АДМИН — РАССЫЛКА
# ═══════════════════════════════════════════════════

async def _do_broadcast(bot, admin_id: int, msg_to_send):
    """Разослать сообщение (текст / фото / видео) всем пользователям."""
    ids = users_all_ids()
    ok = fail = 0

    status = await bot.send_message(
        admin_id,
        f"⏳ Начинаю рассылку <b>{len(ids)}</b> пользователям...",
        parse_mode="HTML",
    )

    for uid in ids:
        try:
            if msg_to_send.photo:
                await bot.send_photo(
                    uid,
                    photo=msg_to_send.photo[-1].file_id,
                    caption=msg_to_send.caption or "",
                    parse_mode="HTML",
                )
            elif msg_to_send.video:
                await bot.send_video(
                    uid,
                    video=msg_to_send.video.file_id,
                    caption=msg_to_send.caption or "",
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    uid,
                    text=msg_to_send.text or msg_to_send.caption or "",
                    parse_mode="HTML",
                )
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)

    await bot.edit_message_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"👍 Доставлено: <b>{ok}</b>\n"
        f"❌ Не доставлено: <b>{fail}</b>",
        chat_id=admin_id,
        message_id=status.message_id,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="adm_back")]
        ]),
    )

# ═══════════════════════════════════════════════════
#  ОБРАБОТЧИКИ
# ═══════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id

    if not await is_subscribed(ctx.bot, uid):
        try: await update.message.delete()
        except: pass
        await _send_sub_required(ctx.bot, chat_id)
        return

    old = ctx.user_data.get("mid")
    if old:
        try: await ctx.bot.delete_message(chat_id, old)
        except: pass

    ctx.user_data.clear()
    users_register(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    msg = await update.message.reply_text(MENU_TEXT, reply_markup=MENU_KB, parse_mode="HTML")
    ctx.user_data["mid"] = msg.message_id

    try: await update.message.delete()
    except: pass


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /admin — только для администратора."""
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        try: await update.message.delete()
        except: pass
        return

    try: await update.message.delete()
    except: pass

    await update.effective_chat.send_message(
        "👑 <b>Панель администратора</b>",
        parse_mode="HTML",
        reply_markup=ADMIN_KB,
    )


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Текстовый ввод — поиск или ожидание рассылки."""
    uid = update.effective_user.id

    # Ожидаем текст для рассылки (только админ)
    if ctx.user_data.get("state") == "broadcast_wait" and uid == ADMIN_ID:
        ctx.user_data["state"] = None
        msg = update.message
        try: await msg.delete()
        except: pass
        await _do_broadcast(ctx.bot, uid, msg)
        return

    if not await is_subscribed(ctx.bot, uid):
        try: await update.message.delete()
        except: pass
        await _send_sub_required(ctx.bot, update.effective_chat.id)
        return

    if ctx.user_data.get("state") != "sinput":
        try: await update.message.delete()
        except: pass
        return

    query = update.message.text.strip()
    ctx.user_data["state"] = None
    ctx.user_data["query"] = query

    try: await update.message.delete()
    except: pass

    tgt = (ctx.bot, update.effective_chat.id, ctx.user_data.get("mid"))
    await _ed(tgt, f"<b>🔍{query}...</b>")

    users_inc_search(uid)
    items = await asyncio.to_thread(yt_search, query, SEARCH_LIMIT)
    ctx.user_data["res"] = items
    ctx.user_data["spage"] = 0

    await _show_search_results(tgt, ctx, 0)


async def on_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Фото/видео — только для рассылки от админа."""
    uid = update.effective_user.id
    if uid != ADMIN_ID or ctx.user_data.get("state") != "broadcast_wait":
        return

    ctx.user_data["state"] = None
    msg = update.message
    try: await msg.delete()
    except: pass
    await _do_broadcast(ctx.bot, uid, msg)


async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q  = update.callback_query
    await q.answer()
    d   = q.data
    uid = q.from_user.id
    ctx.user_data["mid"] = q.message.message_id

    # ── Проверка подписки ──
    if d == "check_sub":
        if await is_subscribed(ctx.bot, uid):
            ctx.user_data.clear()
            await q.message.edit_text(MENU_TEXT, reply_markup=MENU_KB, parse_mode="HTML")
            ctx.user_data["mid"] = q.message.message_id
        else:
            await q.answer("❌ Вы ещё не подписались на канал!", show_alert=True)
        return

    # ── Админ-панель ──
    if d == "adm_back":
        if uid != ADMIN_ID: return
        await q.message.edit_text("👑 <b>Панель администратора</b>",
                                  parse_mode="HTML", reply_markup=ADMIN_KB)
        return

    if d == "adm_stats":
        if uid != ADMIN_ID: return
        s = users_stats()
        text = (
            "📊 <b>Статистика</b>\n\n"
            f"👥 Пользователей: <b>{s['total']}</b>\n"
            f"🔍 Поисков: <b>{s['searches']}</b>\n"
            f"📥 Скачиваний: <b>{s['downloads']}</b>"
        )
        await q.message.edit_text(text, parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup([
                                      [InlineKeyboardButton("◀️ Назад", callback_data="adm_back")]
                                  ]))
        return

    if d == "adm_broadcast":
        if uid != ADMIN_ID: return
        ctx.user_data["state"] = "broadcast_wait"
        await q.message.edit_text(
            "📣 <b>Рассылка</b>\n\n"
            "Отправь сообщение для рассылки.\n"
            "Поддерживается: текст, фото с подписью, видео с подписью.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="adm_cancel_bc")]
            ]),
        )
        return

    if d == "adm_cancel_bc":
        if uid != ADMIN_ID: return
        ctx.user_data.pop("state", None)
        await q.message.edit_text("👑 <b>Панель администратора</b>",
                                  parse_mode="HTML", reply_markup=ADMIN_KB)
        return

    # Проверка подписки для всех остальных действий
    if not await is_subscribed(ctx.bot, uid):
        await _send_sub_required(ctx.bot, q.message.chat_id, q.message.message_id)
        return

    # ── Меню ──
    if d == "home":
        ctx.user_data.pop("state", None)
        await _ed(q, MENU_TEXT, MENU_KB)

    elif d == "noop":
        pass

    # ── Поиск: ввод ──
    elif d == "search":
        ctx.user_data["state"] = "sinput"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠", callback_data="home")]])
        if q.message.audio or q.message.voice:
            sent = await q.message.chat.send_message(
                "<b>🔍 Название трека или исполнитель:</b>",
                parse_mode="HTML", reply_markup=kb,
            )
            ctx.user_data["mid"] = sent.message_id
        else:
            await _ed(q, "<b>🔍 Название трека или исполнитель:</b>", kb)

    # ── Поиск: навигация ──
    elif d == "snext":
        page = ctx.user_data.get("spage", 0) + 1
        await _show_search_results(q, ctx, page)

    elif d == "sprev":
        page = ctx.user_data.get("spage", 0) - 1
        await _show_search_results(q, ctx, page)

    # ── Поиск: выбор трека ──
    elif d.startswith("sr_"):
        i = int(d[3:])
        res = ctx.user_data.get("res", [])
        if i < len(res):
            ctx.user_data["cur"] = res[i]
            await _do_dl(q, res[i]["id"], res[i], uid, ctx)

    # ── Кнопка ❤️ под треком ──
    elif d.startswith("af_"):
        vid = d[3:]
        tr = ctx.user_data.get("last_track") or ctx.user_data.get("cur")
        if tr:
            if fav_ok(uid, vid):
                fav_rm(uid, vid); heart = "❤️"
            else:
                fav_add(uid, tr); heart = "💔"
            try:
                await q.message.edit_reply_markup(
                    InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔎", callback_data="search"),
                         InlineKeyboardButton(heart, callback_data=f"af_{vid}")],
                    ]))
            except: pass

    # ── Избранное ──
    elif d == "favs":
        await _show_favs(q, uid)

    elif d.startswith("fp_"):
        await _show_favs(q, uid, int(d[3:]))

    elif d.startswith("ft_"):
        i = int(d[3:])
        fl = fav_list(uid)
        if i < len(fl):
            ctx.user_data["cur"] = fl[i]
            await _do_dl(q, fl[i]["id"], fl[i], uid, ctx)

    # ── Волна ──
    elif d == "wave":
        await _ed(q, "<b>🌊 Подбираю треки...</b>")
        w = await asyncio.to_thread(yt_wave, uid)
        if not w:
            await _ed(q, "<b>🌊 Не удалось подобрать</b>",
                      InlineKeyboardMarkup([[InlineKeyboardButton("🏠", callback_data="home")]]))
            return
        ctx.user_data["wave"] = w
        ctx.user_data["wi"] = 0
        await _show_wave(q, w[0], uid, ctx)

    elif d == "wn":
        w = ctx.user_data.get("wave", [])
        i = ctx.user_data.get("wi", 0) + 1
        if i >= len(w):
            more = await asyncio.to_thread(yt_wave, uid)
            w.extend(more)
            ctx.user_data["wave"] = w
        if i < len(w):
            ctx.user_data["wi"] = i
            await _show_wave(q, w[i], uid, ctx)
        else:
            await _ed(q, "<b>🌊 Треки закончились</b>",
                      InlineKeyboardMarkup([[InlineKeyboardButton("🏠", callback_data="home")]]))

    elif d == "wp":
        w = ctx.user_data.get("wave", [])
        i = max(0, ctx.user_data.get("wi", 0) - 1)
        ctx.user_data["wi"] = i
        if w: await _show_wave(q, w[i], uid, ctx)

    elif d.startswith("wd_"):
        vid = d[3:]
        w = ctx.user_data.get("wave", [])
        tr = next((t for t in w if t["id"] == vid), {})
        ctx.user_data["cur"] = tr
        await _do_dl(q, vid, tr, uid, ctx, wave=True)

    elif d.startswith("wf_"):
        vid = d[3:]
        w = ctx.user_data.get("wave", [])
        tr = next((t for t in w if t["id"] == vid), None)
        if tr:
            fav_rm(uid, vid) if fav_ok(uid, vid) else fav_add(uid, tr)
            await _show_wave(q, tr, uid, ctx)

# ═══════════════════════════════════════════════════
#  ЗАПУСК
# ═══════════════════════════════════════════════════

async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "🎶 muss music"),
        BotCommand("admin", "👑 панель администратора"),
    ])


def main():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        log.info("✅ ffmpeg")
    except:
        log.error("❌ ffmpeg НЕ найден!")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, on_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("🎵 Бот запущен")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()