#!/usr/bin/env python3
"""
Self-install and Bootstrap Script for Auto-Clipper Telegram Bot
Installs required Python packages, verifies FFmpeg, and configures environment.
"""
import os
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def check_and_install_dependencies():
    print("[setup] Checking Python dependencies...")
    req_file = os.path.join(BASE_DIR, "requirements.txt")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_file], check=True)
        print("[setup] All Python packages are installed!")
    except Exception as ex:
        print(f"[setup] Note: pip install warning: {ex}")

    # Check FFmpeg
    if not shutil.which("ffmpeg"):
        print("[setup] FFmpeg not found on PATH. Attempting automatic installation...")
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["winget", "install", "-e", "--id", "Gyan.FFmpeg",
                                "--accept-source-agreements", "--accept-package-agreements"], check=True)
            elif sys.platform == "darwin":
                subprocess.run(["brew", "install", "ffmpeg"], check=True)
            else:
                subprocess.run(["sudo", "apt-get", "update", "&&", "sudo", "apt-get", "install", "-y", "ffmpeg"], shell=True, check=True)
        except Exception as ex:
            print(f"[setup] Automatic FFmpeg installation failed: {ex}")

    # Check .env
    env_file = os.path.join(BASE_DIR, ".env")
    env_example = os.path.join(BASE_DIR, ".env.example")
    if not os.path.exists(env_file) and os.path.exists(env_example):
        shutil.copy2(env_example, env_file)
        print("[setup] Created .env from .env.example")

    print("[setup] Setup complete! You can now run: python bot.py")


if __name__ == "__main__":
    check_and_install_dependencies()
