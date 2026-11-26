# Auto-Clipper Telegram Bot 🎬⚡

An automated, 100% free and unlimited video clipping system that converts any YouTube livestream VOD, Twitch VOD, or gameplay video into ready-to-post **9:16 vertical clips (1080x1920)** for **Instagram Reels**, **YouTube Shorts**, and **TikTok**.

Can run **locally on Windows/Linux** or **24/7 in the cloud via GitHub Actions**.

---

## 🚀 Features

- **Candidate-First Ultra-Fast Pipeline**: Never downloads or transcribes full multi-hour videos. Downloads low-bitrate audio in seconds, scans loudness & transient action peaks with NumPy in milliseconds, transcribes only candidate moments, and downloads only winning segments.
- **Auto-Detection (Streamer vs Normal Video)**:
  - **Streamer Mode**: Automatically detects facecam overlays using OpenCV YuNet DNN face detection. Positions facecam full-width on top (1080x640) and gameplay below (1080x1280), or corner PIP (`topleft`, `topright`).
  - **Normal / No-Commentary Mode**: Detects gameplay/cinematic videos. Centers the 16:9 video in 1080x1920 with a **clean, solid cinematic dark background** (no motion-blurred video).
  - **Strict Under-1-Minute Clips**: All clips are hard-capped at $\le$ 58 seconds to guarantee 100% compliance with Shorts & Reels algorithms.
- **Unique Instagram & Shorts Captions (Tap-to-Copy)**:
  - Every clip includes a unique, engaging viral caption with hooks, audience interaction questions, and curated hashtags.
  - Enclosed in tap-to-copy formatting for 1-tap pasting into Instagram and YouTube.
- **No-Subtitles Mode**:
  - Subtitles are disabled by default for clean gameplay and cinematic viewing.
- **24/7 Cloud Execution (GitHub Actions)**:
  - Automated workflow runs the bot continuously 24/7 on GitHub Actions runners with scheduled handovers and zero cost.

---

## 📂 Project Structure

```
.
├── .github/workflows/
│   └── bot.yml        # 24/7 GitHub Actions continuous runner
├── bot.py             # Telegram async bot handlers, job queue, and progress UI
├── pipeline.py        # Core candidate-first clipping pipeline (CLI & Bot engine)
├── detect.py          # OpenCV YuNet face detection & streamer/normal classifier
├── layouts.py         # FFmpeg filter graphs (top, topleft, topright, pad, blur, crop)
├── captions.py        # Animated karaoke ASS subtitles (with silence-clearing)
├── social.py          # Unique Instagram & Shorts caption generator
├── estimator.py       # Dynamic job ETA estimator with moving averages
├── config.py          # Settings and environment loader
├── models/            # Local OpenCV YuNet DNN face detection model
├── tests/             # Automated test suite
├── .env.example       # Template configuration
├── requirements.txt   # Python dependencies
├── run.bat            # 1-Click Windows launcher
└── README.md
```

---

## ☁️ Running 24/7 on GitHub Actions

1. Fork or push this repository to your GitHub account: `https://github.com/vijayavenkatesh975/Clipping-bot`.
2. Add your GitHub Repository Secrets (**Settings > Secrets and variables > Actions > New repository secret**):
   - `TELEGRAM_BOT_TOKEN`: Your Telegram Bot API token from `@BotFather`.
   - `ALLOWED_USER_IDS`: Your numeric Telegram User ID from `@userinfobot`.
3. Go to the **Actions** tab in GitHub, select **24/7 Telegram Clipper Bot**, and click **Run workflow**.
4. The workflow will run the bot continuously 24/7, with scheduled handovers every 4 hours!

---

## 💻 Running Locally

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

## ⚖️ Legal & Compliance Note
Only download, clip, and publish content that you own or have explicit permission/licenses to use.
