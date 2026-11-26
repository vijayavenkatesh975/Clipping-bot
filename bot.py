"""
Auto-Clipper Telegram Bot (python-telegram-bot v21+ Async)
Handles user commands, job queuing, interactive buttons, live progress message editing,
and instant streaming video delivery.
"""
import asyncio
import html
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, Any

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.request import HTTPXRequest

from config import (
    TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, MAX_JOB_MINUTES,
    DEFAULT_CLIPS, DEFAULT_LAYOUT, DEFAULT_FIT, DEFAULT_LENGTH, DEFAULT_SUBS,
    is_user_allowed, TELEGRAM_API_BASE, WORK_DIR
)
from pipeline import probe_video, run_pipeline, re_render_clips
from estimator import estimate_pipeline_time

# User preferences stored in-memory
USER_SETTINGS: Dict[int, Dict[str, Any]] = {}
USER_LAST_JOB: Dict[int, Dict[str, Any]] = {}

# Active Job Queue
JOB_QUEUE: asyncio.Queue = asyncio.Queue()
CURRENT_JOB = None
CANCEL_EVENT = asyncio.Event()


def get_user_settings(user_id: int):
    if user_id not in USER_SETTINGS:
        USER_SETTINGS[user_id] = {
            "layout": DEFAULT_LAYOUT,
            "fit": DEFAULT_FIT,
            "length": DEFAULT_LENGTH,
            "clips": DEFAULT_CLIPS,
            "subs": DEFAULT_SUBS,
            "manual_facecam": None
        }
    return USER_SETTINGS[user_id]


def format_timestamp(seconds: float):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def get_layout_display(layout: str) -> str:
    mapping = {
        "top": "👑 Facecam Top (Default)",
        "topleft": "↖️ Top-Left Corner (PIP)",
        "topright": "↗️ Top-Right Corner (PIP)"
    }
    return mapping.get(layout, layout.capitalize())


def get_clips_keyboard(current_layout: str):
    return [
        [
            InlineKeyboardButton("3 Clips", callback_data="clips_3"),
            InlineKeyboardButton("5 Clips", callback_data="clips_5"),
            InlineKeyboardButton("8 Clips", callback_data="clips_8")
        ],
        [
            InlineKeyboardButton("10 Clips", callback_data="clips_10"),
            InlineKeyboardButton("⚡ Auto (Best Moments)", callback_data="clips_auto")
        ],
        [
            InlineKeyboardButton(f"🎭 Layout: {get_layout_display(current_layout)} ▾", callback_data="prompt_layout")
        ]
    ]


# ---------------------------------------------------------------- Command Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔ Access denied. You are not on the authorized user list.")
        return

    welcome_text = (
        "🎬 <b>Welcome to Auto-Clipper AI Bot!</b>\n\n"
        "Send me any YouTube video, livestream VOD, or upload a video file. "
        "I'll automatically find the funniest, loudest, and most epic moments, "
        "and send you <b>9:16 vertical clips</b> ready for Instagram Reels & YouTube Shorts!\n\n"
        "⚡ <b>Commands:</b>\n"
        "• <code>/layout [top|topleft|topright]</code> - Set streamer facecam layout\n"
        "• <code>/facecam [x,y,w,h]</code> - Set custom manual facecam box\n"
        "• <code>/fit [blur|crop]</code> - Set normal video padding\n"
        "• <code>/length [15-30|20-45|30-58]</code> - Set clip length bounds (all < 1 min)\n"
        "• <code>/status</code> - Check current processing queue\n"
        "• <code>/cancel</code> - Cancel active clipping job\n\n"
        "👉 <i>Send a video link now to get started!</i>"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)


async def layout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id): return
    args = context.args
    settings = get_user_settings(user_id)
    if args and args[0].lower() in ("top", "topleft", "topright"):
        settings["layout"] = args[0].lower()
        await update.message.reply_text(f"✅ Streamer layout set to: <b>{get_layout_display(settings['layout'])}</b>", parse_mode="HTML")
    else:
        keyboard = [
            [InlineKeyboardButton("👑 Facecam Top (Full Width)", callback_data="set_layout_top")],
            [InlineKeyboardButton("↗️ Top-Right Overlay (PIP)", callback_data="set_layout_topright")],
            [InlineKeyboardButton("↖️ Top-Left Overlay (PIP)", callback_data="set_layout_topleft")]
        ]
        await update.message.reply_text("Choose Streamer Facecam Layout:", reply_markup=InlineKeyboardMarkup(keyboard))


async def facecam_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id): return
    args = context.args
    settings = get_user_settings(user_id)
    if args:
        try:
            parts = [float(p.strip()) for p in args[0].split(",")]
            if len(parts) == 4 and all(0.0 <= p <= 1.0 for p in parts):
                settings["manual_facecam"] = tuple(parts)
                await update.message.reply_text(f"✅ Manual facecam crop set to: <code>{parts}</code>", parse_mode="HTML")
                return
        except Exception:
            pass
    await update.message.reply_text("⚠️ Usage: <code>/facecam x,y,w,h</code> (fractions 0.0 to 1.0, e.g. <code>/facecam 0.02,0.45,0.16,0.17</code>)", parse_mode="HTML")


async def fit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id): return
    args = context.args
    settings = get_user_settings(user_id)
    if args and args[0].lower() in ("pad", "center", "blur", "crop"):
        settings["fit"] = args[0].lower()
        await update.message.reply_text(f"✅ Normal video fit set to: <b>{settings['fit']}</b>", parse_mode="HTML")
    else:
        keyboard = [
            [InlineKeyboardButton("Clean Centered (Solid Black BG - Recommended)", callback_data="set_fit_pad")],
            [InlineKeyboardButton("Blurred Background (Fit 9:16)", callback_data="set_fit_blur")],
            [InlineKeyboardButton("Center Crop (Fill 9:16)", callback_data="set_fit_crop")]
        ]
        await update.message.reply_text("Choose Normal Video Fit Style:", reply_markup=InlineKeyboardMarkup(keyboard))


async def length_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id): return
    args = context.args
    settings = get_user_settings(user_id)
    if args and args[0] in ("15-30", "20-45", "30-58"):
        settings["length"] = args[0]
        await update.message.reply_text(f"✅ Clip duration set to: <b>{settings['length']}s (under 1 min)</b>", parse_mode="HTML")
    else:
        keyboard = [
            [InlineKeyboardButton("⚡ Punchy (15-30s)", callback_data="set_len_15-30")],
            [InlineKeyboardButton("🔥 Standard Shorts (20-45s)", callback_data="set_len_20-45")],
            [InlineKeyboardButton("🎬 Full Shorts (30-58s max)", callback_data="set_len_30-58")]
        ]
        await update.message.reply_text("Choose Target Clip Duration (All strictly within 1 min):", reply_markup=InlineKeyboardMarkup(keyboard))


async def subs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id): return
    args = context.args
    settings = get_user_settings(user_id)
    if args and args[0].lower() in ("on", "true", "enable", "yes"):
        settings["subs"] = True
        await update.message.reply_text("✅ Subtitles enabled for commentary clips.")
    elif args and args[0].lower() in ("off", "false", "disable", "no"):
        settings["subs"] = False
        await update.message.reply_text("✅ Subtitles disabled (Clean video).")
    else:
        current_status = "Enabled" if settings.get("subs", False) else "Disabled (Default - Clean Video)"
        keyboard = [
            [InlineKeyboardButton("🚫 Disable Subtitles (Clean Video)", callback_data="set_subs_off")],
            [InlineKeyboardButton("📝 Enable Subtitles (Commentary only)", callback_data="set_subs_on")]
        ]
        await update.message.reply_text(f"Subtitles are currently: <b>{current_status}</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id): return
    if CURRENT_JOB:
        await update.message.reply_text(f"⏳ <b>Job in Progress:</b>\n{CURRENT_JOB.get('title')}", parse_mode="HTML")
    else:
        qsize = JOB_QUEUE.qsize()
        await update.message.reply_text(f"🟢 Bot is idle. Queue size: {qsize}")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id): return
    global CURRENT_JOB
    if CURRENT_JOB:
        CANCEL_EVENT.set()
        await update.message.reply_text("🛑 Cancel request sent. Current job will stop.")
    else:
        await update.message.reply_text("No active job to cancel.")


# ---------------------------------------------------------------- Message & Flow Handler
async def handle_url_or_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔ Access denied.")
        return

    settings = get_user_settings(user_id)

    url = None
    if update.message.text:
        text = update.message.text.strip()
        if text.startswith("http://") or text.startswith("https://"):
            url = text

    elif update.message.video or update.message.document:
        doc = update.message.video or update.message.document
        if doc.file_size > 20 * 1024 * 1024 and not TELEGRAM_API_BASE:
            await update.message.reply_text(
                "⚠️ This uploaded video is larger than 20 MB (Telegram Cloud limit).\n"
                "Please send a YouTube link or configure a local Bot API server."
            )
            return

        msg_wait = await update.message.reply_text("📥 Downloading uploaded video...")
        file = await doc.get_file()
        local_path = os.path.join(WORK_DIR, f"upload_{doc.file_unique_id}.mp4")
        await file.download_to_drive(local_path)
        url = local_path
        await msg_wait.delete()

    if not url:
        await update.message.reply_text("⚠️ Please send a valid YouTube link (e.g. <code>https://youtube.com/watch?v=...</code>)", parse_mode="HTML")
        return

    # Probe in seconds
    probe_msg = await update.message.reply_text("🔍 Probing video details...")
    try:
        meta = await asyncio.to_thread(probe_video, url)
        await probe_msg.delete()
    except Exception as ex:
        err_msg = html.escape(str(ex))[:1000]
        await probe_msg.edit_text(f"❌ <b>Error:</b> {err_msg}", parse_mode="HTML")
        return

    dur_str = format_timestamp(meta["duration"])
    type_str = "Vertical (9:16)" if meta["is_vertical"] else "Landscape"

    # Store in user context
    context.user_data["pending_job"] = {
        "url": url,
        "meta": meta
    }

    # Ask how many clips
    text_info = (
        f"🎬 <b>{meta['title']}</b>\n"
        f"⏱️ <b>Duration:</b> {dur_str} | 📐 <b>Format:</b> {type_str}\n"
        f"🎭 <b>Current Layout:</b> <b>{get_layout_display(settings['layout'])}</b>\n\n"
        f"How many clips would you like me to create?"
    )
    keyboard = get_clips_keyboard(settings["layout"])
    await update.message.reply_text(text_info, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ---------------------------------------------------------------- Callback Handler
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)

    if data == "prompt_layout":
        layout_kb = [
            [InlineKeyboardButton("👑 Facecam Top (1080x640 Top, Game Below)", callback_data="set_layout_top")],
            [InlineKeyboardButton("↗️ Top-Right Corner (PIP Overlay)", callback_data="set_layout_topright")],
            [InlineKeyboardButton("↖️ Top-Left Corner (PIP Overlay)", callback_data="set_layout_topleft")],
            [InlineKeyboardButton("🔙 Back to Clips Selection", callback_data="back_to_clips")]
        ]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(layout_kb))
        return

    if data == "back_to_clips":
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(get_clips_keyboard(settings["layout"])))
        return

    if data.startswith("set_layout_"):
        settings["layout"] = data.replace("set_layout_", "")
        job_info = context.user_data.get("pending_job")
        if job_info:
            meta = job_info["meta"]
            dur_str = format_timestamp(meta["duration"])
            type_str = "Vertical (9:16)" if meta["is_vertical"] else "Landscape"
            text_info = (
                f"🎬 <b>{meta['title']}</b>\n"
                f"⏱️ <b>Duration:</b> {dur_str} | 📐 <b>Format:</b> {type_str}\n"
                f"🎭 <b>Current Layout:</b> <b>{get_layout_display(settings['layout'])}</b>\n\n"
                f"How many clips would you like me to create?"
            )
            await query.edit_message_text(text_info, reply_markup=InlineKeyboardMarkup(get_clips_keyboard(settings["layout"])), parse_mode="HTML")
        else:
            await query.edit_message_text(f"✅ Streamer layout set to: <b>{get_layout_display(settings['layout'])}</b>", parse_mode="HTML")
        return

    if data == "redo_layout":
        last_job = USER_LAST_JOB.get(user_id)
        if not last_job:
            await query.edit_message_text("⚠️ No recent job found to re-render. Please send a new video link.")
            return
        redo_kb = [
            [InlineKeyboardButton("👑 Facecam Top (1080x640)", callback_data="redo_to_top")],
            [InlineKeyboardButton("↗️ Top-Right Corner (PIP)", callback_data="redo_to_topright")],
            [InlineKeyboardButton("↖️ Top-Left Corner (PIP)", callback_data="redo_to_topleft")]
        ]
        await query.edit_message_text("Choose new layout for instant re-render:", reply_markup=InlineKeyboardMarkup(redo_kb))
        return

    if data.startswith("redo_to_"):
        new_layout = data.replace("redo_to_", "")
        last_job = USER_LAST_JOB.get(user_id)
        if not last_job:
            await query.edit_message_text("⚠️ Job expired. Please send the link again.")
            return

        vid_id = last_job["vid_id"]
        app = context.application
        chat_id = update.effective_chat.id
        loop = asyncio.get_running_loop()

        await query.edit_message_text(f"🔄 <b>Re-rendering clips with {get_layout_display(new_layout)}...</b>\n<i>Reusing cached downloads (takes ~5-10s)...</i>", parse_mode="HTML")

        dummy_job = {
            "meta": {"title": f"Re-render ({new_layout})"},
            "est_range": "10s",
            "user_id": user_id,
            "chat_id": chat_id
        }

        def on_clip_done(clip_info):
            asyncio.run_coroutine_threadsafe(deliver_clip(app, chat_id, clip_info, dummy_job), loop)

        try:
            res = await asyncio.to_thread(re_render_clips, vid_id, new_layout, on_clip_done)
            await app.bot.send_message(chat_id, f"🎉 <b>Re-render Complete!</b> Delivered with <b>{get_layout_display(new_layout)}</b>.", parse_mode="HTML")
        except Exception as ex:
            await app.bot.send_message(chat_id, f"❌ Re-render failed: {ex}")
        return

    if data == "more_clips":
        await query.edit_message_text("➕ To generate more clips, send the same video link again and choose a higher clip count (e.g. 8 or 10 Clips). It will reuse the cached audio and loudness scan instantly!")
        return

    if data.startswith("set_fit_"):
        settings["fit"] = data.replace("set_fit_", "")
        await query.edit_message_text(f"✅ Normal video fit set to: <b>{settings['fit']}</b>", parse_mode="HTML")
        return

    if data == "set_subs_off":
        settings["subs"] = False
        await query.edit_message_text("✅ Subtitles <b>Disabled</b> (All clips will be clean video without subtitles).", parse_mode="HTML")
        return

    if data == "set_subs_on":
        settings["subs"] = True
        await query.edit_message_text("✅ Subtitles <b>Enabled</b> (Karaoke subtitles for active commentary clips).", parse_mode="HTML")
        return

    if data.startswith("set_len_"):
        settings["length"] = data.replace("set_len_", "")
        await query.edit_message_text(f"✅ Clip duration set to: <b>{settings['length']}s (under 1 min)</b>", parse_mode="HTML")
        return

    if data.startswith("clips_"):
        count_str = data.replace("clips_", "")
        clips_count = 5 if count_str == "auto" else int(count_str)

        job_info = context.user_data.get("pending_job")
        if not job_info:
            await query.edit_message_text("⚠️ Job expired. Please send the link again.")
            return

        meta = job_info["meta"]
        url = job_info["url"]

        # Calculate Time Estimate
        est_sec, range_str, plan = estimate_pipeline_time(meta["duration"], clips_count, max_budget_min=MAX_JOB_MINUTES)
        degrade_note = f"\n💡 <i>{plan['reason']}</i>" if plan["degraded"] else ""

        progress_msg = await query.edit_message_text(
            f"🚀 <b>Queued: {meta['title']}</b>\n\n"
            f"⏱️ <b>Estimated Time:</b> {range_str}{degrade_note}\n\n"
            f"⏳ <i>Position in queue: 1. Starting pipeline now...</i>",
            parse_mode="HTML"
        )

        job_item = {
            "user_id": user_id,
            "url": url,
            "clips_count": clips_count,
            "layout": settings["layout"],
            "fit": settings["fit"],
            "length": settings["length"],
            "subs": settings.get("subs", DEFAULT_SUBS),
            "manual_facecam": settings.get("manual_facecam"),
            "meta": meta,
            "msg_id": progress_msg.message_id,
            "chat_id": update.effective_chat.id,
            "est_range": range_str
        }

        await JOB_QUEUE.put(job_item)


# ---------------------------------------------------------------- Job Queue Worker
async def job_worker(app: Application):
    """Processes jobs one at a time."""
    global CURRENT_JOB
    loop = asyncio.get_running_loop()
    while True:
        try:
            job = await JOB_QUEUE.get()
            CURRENT_JOB = job
            CANCEL_EVENT.clear()
            chat_id = job["chat_id"]
            msg_id = job["msg_id"]
            t_start = time.time()

            async def update_ui(stage_name, percent, eta_str=""):
                # Construct ASCII progress bar
                bar_len = 10
                filled = int(percent / 100.0 * bar_len)
                bar = "█" * filled + "░" * (bar_len - filled)
                text = (
                    f"🎬 <b>Processing:</b> {job['meta']['title']}\n\n"
                    f"[{bar}] <b>{percent}%</b>\n"
                    f"📍 <b>Stage:</b> {stage_name}\n"
                    f"⏱️ <b>Estimate:</b> {job['est_range']}\n"
                    f"<i>(Send /cancel anytime to abort)</i>"
                )
                try:
                    await app.bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
                except Exception:
                    pass

            def on_clip_done(clip_info):
                # Send immediately as video!
                asyncio.run_coroutine_threadsafe(deliver_clip(app, chat_id, clip_info, job), loop)

            try:
                res = await asyncio.to_thread(
                    run_pipeline,
                    url_or_path=job["url"],
                    clips_count=job["clips_count"],
                    layout=job["layout"],
                    fit=job["fit"],
                    length=job["length"],
                    manual_facecam=job.get("manual_facecam"),
                    enable_subs=job.get("subs", DEFAULT_SUBS),
                    on_progress=lambda stage, pct, eta: asyncio.run_coroutine_threadsafe(update_ui(stage, pct, eta), loop),
                    on_clip_ready=on_clip_done
                )

                # Store last job for instant re-rendering
                USER_LAST_JOB[job["user_id"]] = {
                    "vid_id": res["meta"]["video_id"],
                    "res": res,
                    "url": job["url"]
                }

                total_sec = time.time() - t_start
                actual_min = int(round(total_sec / 60.0))

                # Send summary
                mode_str = "Streamer (Facecam Top)" if res["is_streamer"] else "Clean Centered (Solid BG)"
                subs_str = "Enabled" if job.get("subs", DEFAULT_SUBS) and res.get("is_commentary") else "Disabled (No-subs mode)"
                summary = (
                    f"🎉 <b>All {len(res['clips'])} Clips Completed!</b>\n\n"
                    f"⏱️ <b>Actual Time:</b> ~{actual_min} min (Estimate was {job['est_range']})\n"
                    f"🎭 <b>Layout:</b> {mode_str}\n"
                    f"🎙️ <b>Subtitles:</b> {subs_str}\n\n"
                    f"Ready for your next video!"
                )
                summary_buttons = [
                    [InlineKeyboardButton("🔄 Redo (Different Layout)", callback_data="redo_layout")],
                    [InlineKeyboardButton("➕ Generate More Clips", callback_data="more_clips")]
                ]
                await app.bot.send_message(chat_id, summary, reply_markup=InlineKeyboardMarkup(summary_buttons), parse_mode="HTML")

            except Exception as ex:
                err_str = str(ex)
                print(f"[bot] Job processing error: {err_str}")
                safe_err = html.escape(err_str)[:1500]
                try:
                    await app.bot.send_message(chat_id, f"❌ <b>Error processing video:</b>\n<pre>{safe_err}</pre>", parse_mode="HTML")
                except Exception:
                    await app.bot.send_message(chat_id, f"❌ Error processing video:\n{err_str[:1500]}")

            finally:
                CURRENT_JOB = None
                JOB_QUEUE.task_done()

        except Exception as loop_ex:
            print(f"[worker] Unexpected error in worker loop: {loop_ex}")
            await asyncio.sleep(1)


async def deliver_clip(app: Application, chat_id: int, clip: dict, job: dict):
    """Uploads finished clip to Telegram chat with rich caption."""
    # Send facecam preview frame on first streamer clip if available
    preview_img = clip.get("preview_img")
    if preview_img and os.path.exists(preview_img) and not job.get("_preview_sent"):
        job["_preview_sent"] = True
        try:
            with open(preview_img, "rb") as pf:
                await app.bot.send_photo(
                    chat_id=chat_id,
                    photo=pf,
                    caption="🎯 <b>Streamer Facecam Detected!</b>\nLayout: Facecam on Top (1080x640) + Gameplay Below.\n<i>(Use /layout or /facecam to customize)</i>",
                    parse_mode="HTML",
                    read_timeout=60.0,
                    write_timeout=60.0
                )
        except Exception as ex:
            print(f"[bot] preview send error: {ex}")

    clean_title = html.escape(str(clip['title']))
    clean_reason = html.escape(str(clip['reason']))
    insta_hook = html.escape(str(clip.get("insta_hook", clean_title)))
    insta_cap = html.escape(str(clip.get("insta_caption", "")))
    dur_sec = int(round(clip.get("duration", 0)))

    caption = (
        f"🔥 <b>Clip {clip['id']}: {insta_hook}</b>\n\n"
        f"⏱️ <b>Timestamp:</b> <code>{format_timestamp(clip['start'])}</code> ({dur_sec}s)\n"
        f"⚡ <b>Action:</b> {clean_reason}\n\n"
        f"📋 <b>Instagram / Shorts Caption (Tap to copy):</b>\n"
        f"<code>{insta_cap}</code>"
    )

    path = clip["path"]
    sent = False
    for attempt in range(1, 3):
        try:
            with open(path, "rb") as vf:
                await app.bot.send_video(
                    chat_id=chat_id,
                    video=vf,
                    caption=caption[:1024],
                    parse_mode="HTML",
                    supports_streaming=True,
                    width=1080,
                    height=1920,
                    read_timeout=180.0,
                    write_timeout=180.0,
                    connect_timeout=30.0
                )
            sent = True
            break
        except Exception as ex:
            print(f"[bot] send_video attempt {attempt} failed ({ex})")
            await asyncio.sleep(2)

    if not sent:
        print("[bot] Sending as document fallback...")
        try:
            with open(path, "rb") as vf:
                await app.bot.send_document(
                    chat_id=chat_id,
                    document=vf,
                    caption=caption[:1024],
                    parse_mode="HTML",
                    read_timeout=180.0,
                    write_timeout=180.0,
                    connect_timeout=30.0
                )
        except Exception as ex:
            print(f"[bot] send_document fallback also failed: {ex}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"[bot] Exception while handling update: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        try:
            err_msg = html.escape(str(context.error))[:500]
            await update.effective_message.reply_text(f"⚠️ <b>An error occurred:</b> {err_msg}", parse_mode="HTML")
        except Exception:
            pass


# ---------------------------------------------------------------- Main Entry Point
def setup_env_interactively():
    print("\n" + "=" * 60)
    print("  🔑 TELEGRAM BOT TOKEN REQUIRED")
    print("=" * 60)
    print("1. Open Telegram on your phone or PC.")
    print("2. Search for @BotFather and send: /newbot")
    print("3. Copy the HTTP API token provided by BotFather.")
    print("4. (Optional) Search for @userinfobot to get your numeric User ID.")
    print("=" * 60)
    token = input("Paste your Telegram Bot Token: ").strip()
    if not token:
        print("No token provided. Exiting.")
        sys.exit(1)

    user_id = input("Paste your Telegram User ID (or press Enter to allow only you on first /start): ").strip()

    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    token_set = False
    uid_set = False
    for line in lines:
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            new_lines.append(f"TELEGRAM_BOT_TOKEN={token}\n")
            token_set = True
        elif line.startswith("ALLOWED_USER_IDS="):
            new_lines.append(f"ALLOWED_USER_IDS={user_id}\n")
            uid_set = True
        else:
            new_lines.append(line)

    if not token_set:
        new_lines.append(f"TELEGRAM_BOT_TOKEN={token}\n")
    if not uid_set:
        new_lines.append(f"ALLOWED_USER_IDS={user_id}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print("✅ Settings saved to .env!\n")
    return token, user_id


def main():
    global TELEGRAM_BOT_TOKEN
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        token, uid = setup_env_interactively()
        TELEGRAM_BOT_TOKEN = token

    print("=" * 60)
    print("  ⚡ Starting Auto-Clipper Telegram Bot (Async v21+)...")
    print("=" * 60)

    req = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=30.0,
        read_timeout=120.0,
        write_timeout=180.0,
        pool_timeout=30.0
    )
    builder = Application.builder().token(TELEGRAM_BOT_TOKEN).request(req)
    if TELEGRAM_API_BASE:
        builder.base_url(TELEGRAM_API_BASE)
    app = builder.build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("layout", layout_command))
    app.add_handler(CommandHandler("facecam", facecam_command))
    app.add_handler(CommandHandler("fit", fit_command))
    app.add_handler(CommandHandler("length", length_command))
    app.add_handler(CommandHandler("subs", subs_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # Callbacks and Messages
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_or_video))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_url_or_video))
    app.add_error_handler(error_handler)

    # Background worker
    async def on_startup(application: Application):
        asyncio.create_task(job_worker(application))

    app.post_init = on_startup
    app.run_polling(bootstrap_retries=-1, timeout=30)


if __name__ == "__main__":
    main()
