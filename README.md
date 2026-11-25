# Auto-Clipper Telegram Bot 🎬⚡

An automated, 100% free and unlimited video clipping system that converts any YouTube livestream VOD, Twitch VOD, or gameplay video into ready-to-post **9:16 vertical clips (1080x1920)** for **Instagram Reels**, **YouTube Shorts**, and **TikTok**.

---

## ✨ Features

- **Candidate-First Ultra-Fast Pipeline**: Never downloads or transcribes full multi-hour videos. Downloads low-bitrate audio in seconds, scans loudness & transient action peaks with NumPy in milliseconds, transcribes only candidate moments, and downloads only winning segments.
- **Strict Under 1-Minute Guarantee**: Every clip is hard-capped at $\le$ 58 seconds to 100% qualify for YouTube Shorts and Instagram Reels.
- **Smart Silence-Aware Subtitles**:
  - Subtitles appear **only** while commentary is actively spoken.
  - Automatically clears off the screen during speech pauses ($> 0.45\text{s}$) to avoid blocking gameplay.
  - Subtitles are safely positioned in the lower-third, away from crosshairs and action centers.
  - 100% disabled automatically for no-commentary videos.
- **Streamer vs Normal Video Auto-Detection**:
  - **Streamer Mode**: Automatically detects facecam overlays using OpenCV YuNet DNN face detection. Positions facecam full-width on top (1080x640) and gameplay below (1080x1280), or PIP corner overlays (`topleft`, `topright`).
  - **Normal / No-Commentary Mode**: Clean centered 16:9 video in 9:16 frame with solid cinematic dark background (no dizzying blurred video).
  - **Already Vertical (9:16)**: Preserves existing vertical source videos untouched.
- **Unique Tap-to-Copy Instagram Captions**:
  - Each clip is accompanied by a uniquely generated, viral-ready caption with custom hook titles, audience engagement questions, and trending hashtags.
  - Monospace formatting allows 1-tap copy directly into Instagram Reels or YouTube Shorts.
- **24/7 Cloud Execution via GitHub Actions**:
  - Runs continuous 5-hour sessions with automatic self-handover and hourly cron backup.

---

## 🚀 Running 24/7 on GitHub Actions

This repository includes a pre-configured GitHub Actions workflow (`.github/workflows/bot.yml`) that runs the bot in the cloud 24/7 for free.

### 1. Configure Repository Secrets (Recommended)
1. Go to your GitHub repository -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Click **New repository secret**:
   - `TELEGRAM_BOT_TOKEN`: Your Telegram Bot API token from `@BotFather`.
   - `ALLOWED_USER_IDS`: Your Telegram numeric User ID from `@userinfobot`.

### 2. Enable & Run the Workflow
1. Go to the **Actions** tab in this GitHub repository.
2. Select **24/7 Telegram Clipper Bot**.
3. Click **Run workflow** -> **Run workflow**.
4. The workflow will start, install FFmpeg & Python dependencies, and run your bot continuously with automated self-handover.

---

## 💻 Local Setup & Execution

### 1. Requirements
- Python 3.10+
- FFmpeg installed and available on `PATH`

### 2. Quick Start
```bash
# Clone the repository
git clone https://github.com/vijayavenkatesh975/Clipping-bot.git
cd Clipping-bot

# Install dependencies
pip install -r requirements.txt

# Configure .env
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN and ALLOWED_USER_IDS

# Launch Bot
# Windows:
.\run.bat
# Linux/macOS:
python bot.py
```

---

## 🤖 Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` or `/help` | Welcome message and instructions |
| `/layout` | Choose streamer layout: `top` (default), `topleft`, `topright` |
| `/facecam` | Set custom manual facecam coordinates: `/facecam x,y,w,h` |
| `/fit` | Choose normal video fit: `pad` (default solid dark BG), `blur`, `crop` |
| `/length` | Target clip duration: `15-30` (Punchy), `20-45` (Standard Shorts), `30-58` (Max Shorts) |
| `/status` | View current processing queue |
| `/cancel` | Cancel active processing job |

---

## 📂 Project Structure

```
.
├── .github/workflows/
│   └── bot.yml        # 24/7 GitHub Actions automated runner
├── bot.py             # Telegram async bot handlers, job queue, and progress UI
├── pipeline.py        # Core candidate-first clipping pipeline
├── detect.py          # OpenCV YuNet face detection & streamer/normal classifier
├── layouts.py         # FFmpeg filter graphs (top, topleft, topright, pad, blur, crop)
├── captions.py        # Silence-aware animated karaoke ASS subtitles
├── social.py          # Unique Instagram & Shorts caption generator
├── estimator.py       # Dynamic ETA estimator with moving averages
├── config.py          # Settings and environment loader
├── models/            # OpenCV YuNet DNN face detection ONNX model
├── tests/             # Automated test suite
├── .env.example       # Template configuration
├── requirements.txt   # Python dependencies
└── README.md
```
