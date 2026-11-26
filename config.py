"""
Configuration and Environment Settings for Auto-Clipper Telegram Bot
"""
import glob
import os
import shutil
import sys
import time
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
WORK_DIR = os.path.join(BASE_DIR, "work")
MODELS_DIR = os.path.join(BASE_DIR, "models")
STATS_FILE = os.path.join(BASE_DIR, "stats.json")

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

# Load .env
ENV_FILE = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE)

# Ensure FFmpeg is available on PATH
if not shutil.which("ffmpeg"):
    winget_pkgs = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.exists(winget_pkgs):
        for root, dirs, files in os.walk(winget_pkgs):
            if "ffmpeg.exe" in files:
                os.environ["PATH"] = root + os.pathsep + os.environ["PATH"]
                break

# Detect Best Python 3.12 interpreter
PY_BIN = sys.executable
uv_py = r"C:\Users\vjven\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\python.exe"
if os.path.exists(uv_py):
    PY_BIN = uv_py

# Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

raw_user_ids = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = []
if raw_user_ids:
    for item in raw_user_ids.split(","):
        item = item.strip()
        if item.isdigit():
            ALLOWED_USER_IDS.append(int(item))

MAX_JOB_MINUTES = int(os.getenv("MAX_JOB_MINUTES", "10"))
DEFAULT_CLIPS = int(os.getenv("DEFAULT_CLIPS", "5"))
DEFAULT_LAYOUT = os.getenv("DEFAULT_LAYOUT", "top").lower()
DEFAULT_FIT = os.getenv("DEFAULT_FIT", "pad").lower()
DEFAULT_LENGTH = os.getenv("DEFAULT_LENGTH", "20-45")
DEFAULT_SUBS = os.getenv("DEFAULT_SUBS", "false").lower() in ("true", "1", "yes")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

YTDLP_COOKIES_BROWSER = os.getenv("YTDLP_COOKIES_BROWSER", "").strip()
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()
YTDLP_COOKIES_TEXT = os.getenv("YTDLP_COOKIES_TEXT", "").strip()

if YTDLP_COOKIES_TEXT and not (YTDLP_COOKIES_FILE and os.path.exists(YTDLP_COOKIES_FILE)):
    auto_cookies = os.path.join(CACHE_DIR, "cookies.txt")
    try:
        with open(auto_cookies, "w", encoding="utf-8") as f:
            f.write(YTDLP_COOKIES_TEXT)
        YTDLP_COOKIES_FILE = auto_cookies
    except Exception as ex:
        print(f"[config] Failed to write auto cookies: {ex}")
TELEGRAM_API_BASE = os.getenv("TELEGRAM_API_BASE", "").strip()


def is_user_allowed(user_id: int) -> bool:
    """Return True if user_id is permitted. If ALLOWED_USER_IDS is empty, allow for setup."""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def cleanup_old_cache(days=7):
    """Deletes cached items older than `days` days."""
    now = time.time()
    cutoff = now - (days * 86400)
    for root, dirs, files in os.walk(CACHE_DIR):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
            except Exception:
                pass


def clean_work_dir():
    """Removes temporary job files from work directory."""
    for item in glob.glob(os.path.join(WORK_DIR, "*")):
        try:
            if os.path.isdir(item):
                shutil.rmtree(item, ignore_errors=True)
            else:
                os.remove(item)
        except Exception:
            pass
