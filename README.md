# Auto-Clipper Telegram Bot 🎬⚡

An automated, 100% free and unlimited video clipping system that converts any YouTube livestream VOD, Twitch VOD, or gameplay video into ready-to-post **9:16 vertical clips (1080x1920)** for **Instagram Reels**, **YouTube Shorts**, and **TikTok**.

Can run **locally on Windows/Linux** or **24/7 in the cloud via GitHub Actions**.

---

## 🚀 Features

- **Candidate-First Ultra-Fast Pipeline**: Never downloads or transcribes full multi-hour videos. Downloads low-bitrate audio in seconds, scans loudness & transient action peaks with NumPy in milliseconds, transcribes only candidate moments, and downloads only winning segments.
- **Strict 1-Minute Ceiling**: Every clip is hard-capped at $\le$ 58 seconds, fully qualifying as YouTube Shorts and Instagram Reels.
- **Clean Centered 9:16 (Solid Background)**: Normal and no-commentary videos are cleanly centered in 1080x1920 with a sleek solid dark background (no dizzying blurred video).
- **Subtitles Disabled by Default**: Videos are rendered clean without subtitles by default. Can be enabled via `/subs on` for active commentary clips.
- **Auto-Detection (Streamer vs Normal Video)**:
  - **Streamer Mode**: Automatically detects facecam overlays using OpenCV YuNet DNN face detection. Positions facecam full-width on top (1080x640) and gameplay below (1080x1280), or top-left / top-right PIP corner overlays.
  - **Normal Mode**: Detects no-facecam or cinematic gameplay videos. Fits landscape into 1080x1920 with clean centered solid background (`pad`).
  - **Already Vertical (9:16)**: Preserves existing vertical videos without distortion.
- **Tap-to-Copy Instagram & Shorts Captions**: Each clip includes a unique, catchy hook title, engagement question, and curated hashtags ready to copy with a single tap.
- **Telegram Bot Integration (Async v21+)**:
  - Send any link or upload a video file.
  - Interactive buttons for number of clips (3, 5, 8, 10, Auto) and layouts.
  - Accurate time estimation range (e.g., *"About 4 min. Range 3-6 min"*) and single edited live progress message with ASCII progress bar.
  - Finished clips sent directly into Telegram chat.
- **100% Free & Unlimited**: Runs locally or in GitHub Actions using FFmpeg, Faster-Whisper, OpenCV, and yt-dlp. Zero watermarks, zero paid APIs, zero token limits.

---

## 📁 Project Structure

```
tg-clipper-bot/
├── bot.py             # Telegram async bot handlers, job queue, and progress UI
├── pipeline.py        # Core candidate-first clipping pipeline (CLI & Bot engine)
├── detect.py          # OpenCV YuNet face detection & streamer/normal classifier
├── layouts.py         # FFmpeg filter graphs (top, topleft, topright, pad, blur, crop, as-is)
├── captions.py        # Animated karaoke ASS subtitles with silence detection
├── social.py          # Unique Instagram & Shorts caption generator with viral hooks
├── estimator.py       # Dynamic job ETA estimator with moving averages (stats.json)
├── config.py          # Settings and environment loader
├── models/            # Local OpenCV YuNet DNN face detection model
├── cache/             # Audio and loudness cache (auto-cleaned after 7 days)
├── work/              # Active rendering workspace
├── tests/             # Automated test suite
├── .github/workflows/ # 24/7 continuous GitHub Actions runner
├── .env.example       # Example configuration file
├── run.bat            # 1-Click Windows launcher
└── requirements.txt   # Python dependencies
```

---

## 🌐 Running 24/7 on GitHub Actions

This repository includes a continuous GitHub Actions workflow (`.github/workflows/bot.yml`) that runs the bot **24/7 in the cloud for free**:

1. Fork or push this repository to your GitHub account.
2. Go to **Settings > Secrets and variables > Actions** in your GitHub repository.
3. Add the following repository secrets:
   - `TELEGRAM_BOT_TOKEN`: Your bot token from `@BotFather`
   - `ALLOWED_USER_IDS`: Your Telegram user ID from `@userinfobot`
4. Go to the **Actions** tab, select **24/7 Telegram Clipper Bot**, and click **Run workflow**.
5. The bot runs continuously and automatically restarts via scheduled heartbeats.

---

## 💻 Running Locally

### 1. Set Up Environment
Copy `.env.example` to `.env` and fill in your bot token:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjkl...
ALLOWED_USER_IDS=123456789
```

### 2. Launch
- **Windows**: Double-click `run.bat`
- **Command Line**:
  ```bash
  python bot.py
  ```

---

## 🤖 Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` or `/help` | Welcome message and instructions |
| `/layout` | Choose streamer layout: `top` (default), `topleft`, `topright` |
| `/facecam` | Set custom manual facecam coordinates: `/facecam x,y,w,h` |
| `/fit` | Choose normal video fit: `pad` (default clean centered solid BG), `blur`, `crop` |
| `/length` | Target clip duration: `15-30` (Punchy), `20-45` (Standard Shorts), `30-58` (Max Shorts) |
| `/subs` | Subtitle toggle: `/subs off` (default clean video) or `/subs on` |
| `/status` | View current processing queue |
| `/cancel` | Cancel active processing job |

---

## Running from CLI

You can also use the clipper engine directly from your terminal:

```bash
# Clip top 5 moments from a streamer VOD:
python pipeline.py "https://www.youtube.com/live/..." --clips 5 --layout top

# Clip a normal no-commentary gameplay video with blurred background:
python pipeline.py "https://www.youtube.com/watch?v=..." --clips 3 --fit blur
```

---

## Known Limits & Considerations

1. **Host PC Requirement**: The machine running the bot must remain powered on and connected to the internet while processing jobs.
2. **Local AI Heuristic**: Moment detection combines audio loudness, transient surges, speech hype keywords, and optional local LLM. While it pinpoints high-energy action, comedic nuance varies; use the "More clips" button to explore additional moments.
3. **Livestreams**: Streams that are currently **LIVE** cannot be processed until the broadcaster ends the stream and YouTube converts it into a VOD.
4. **Telegram Cloud File Limits**: Videos up to 49 MB are uploaded directly. For uploaded input videos, Telegram restricts bot downloads to 20 MB unless using a self-hosted Telegram Bot API server (`TELEGRAM_API_BASE`).

---

## Legal & Compliance Note
Only download, clip, and publish content that you own or have explicit permission/licenses to use.
