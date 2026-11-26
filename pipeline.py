"""
Universal Fast Candidate-First Clipping Pipeline
Runs the complete fast pipeline:
  Probe -> Audio Download -> Loudness Scan -> Candidate Transcription -> Ranking ->
  Winning Segments Download -> Facecam Detection -> Render -> Ready
Usable from CLI or imported into Telegram Bot.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import wave
import numpy as np
import requests

from config import (
    BASE_DIR, CACHE_DIR, WORK_DIR, MODELS_DIR,
    PY_BIN, MAX_JOB_MINUTES, DEFAULT_CLIPS, DEFAULT_LAYOUT, DEFAULT_FIT, DEFAULT_LENGTH, DEFAULT_SUBS,
    WHISPER_MODEL, OLLAMA_MODEL, OLLAMA_URL, YTDLP_COOKIES_BROWSER, YTDLP_COOKIES_FILE
)
from captions import make_ass, calculate_wpm
from layouts import render_clip
from detect import detect_facecam
from estimator import estimate_pipeline_time, update_stat
from social import generate_social_caption


def get_video_id(url_or_path):
    """Extracts a unique video ID from URL or filename."""
    m = re.search(r'(?:v=|\/live\/|\/shorts\/|youtu\.be\/)([a-zA-Z0-9_-]{11})', str(url_or_path))
    if m:
        return m.group(1)
    return hashlib.md5(str(url_or_path).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- yt-dlp Utilities
def get_ytdlp_base_cmd(client_profile="android,ios,mweb"):
    """
    Returns base yt-dlp command with mobile client spoofing and cookie configuration.
    Bypasses YouTube datacenter bot checks / sign-in prompts on GitHub Actions and cloud runners.
    """
    cmd = [
        PY_BIN, "-m", "yt_dlp",
        "--extractor-args", f"youtube:player_client={client_profile}",
        "--no-check-certificates"
    ]
    if YTDLP_COOKIES_BROWSER:
        cmd += ["--cookies-from-browser", YTDLP_COOKIES_BROWSER]
    elif YTDLP_COOKIES_FILE and os.path.exists(YTDLP_COOKIES_FILE):
        cmd += ["--cookies", YTDLP_COOKIES_FILE]
    return cmd


# ---------------------------------------------------------------- Step 1: Probe
def probe_video(url_or_path):
    """
    Probes video info in seconds using yt-dlp or ffprobe.
    Returns: dict(title, duration, is_live, width, height, is_vertical, video_id)
    """
    if os.path.exists(url_or_path):
        cmd = [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=width,height", "-of", "json", url_or_path
        ]
        out = subprocess.check_output(cmd, text=True)
        data = json.loads(out)
        dur = float(data.get("format", {}).get("duration", 0))
        st = data.get("streams", [{}])[0]
        w = int(st.get("width", 1920))
        h = int(st.get("height", 1080))
        return {
            "title": os.path.basename(url_or_path),
            "duration": dur,
            "is_live": False,
            "width": w,
            "height": h,
            "is_vertical": (h > w),
            "video_id": get_video_id(url_or_path)
        }

    client_profiles = [
        "android,ios,mweb",
        "ios,web_creator,mweb",
        "android,web"
    ]

    print(f"[probe] Probing metadata for {url_or_path}...")
    proc = None
    for attempt, profile in enumerate(client_profiles, 1):
        cmd = get_ytdlp_base_cmd(profile) + [
            "-J", "--no-playlist",
            "--retries", "3",
            "--retry-sleep", "exp=1:2",
            url_or_path
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        if proc.returncode == 0 and proc.stdout.strip().startswith("{"):
            break
        print(f"[probe] Probe attempt {attempt} with profile ({profile}) failed, retrying...")
        time.sleep(attempt * 2)

    if proc is None or proc.returncode != 0:
        err = proc.stderr if proc else "Unknown error"
        raise RuntimeError(f"Failed to probe video URL:\n{err[-350:]}")

    info = json.loads(proc.stdout)
    is_live = bool(info.get("is_live", False) or info.get("was_live", False) and info.get("duration") is None)
    dur = float(info.get("duration") or 0.0)
    w = int(info.get("width") or 1920)
    h = int(info.get("height") or 1080)

    return {
        "title": info.get("title", "Untitled Video"),
        "duration": dur,
        "is_live": is_live,
        "width": w,
        "height": h,
        "is_vertical": (h > w),
        "video_id": info.get("id") or get_video_id(url_or_path)
    }


# ---------------------------------------------------------------- Step 2: Audio Download
def download_audio(url_or_path, vid_dir):
    """
    Downloads low-bitrate audio only for fast loudness scanning.
    For a 6h stream this is only ~100-200 MB.
    """
    wav_path = os.path.join(vid_dir, "audio.wav")
    if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
        return wav_path

    if os.path.exists(url_or_path):
        subprocess.run(["ffmpeg", "-y", "-i", url_or_path, "-vn", "-ac", "1", "-ar", "16000", wav_path], check=True)
        return wav_path

    out_tmpl = os.path.join(vid_dir, "audio.%(ext)s")
    cmd = get_ytdlp_base_cmd("android,ios,mweb") + [
        "-f", "bestaudio[abr<=64]/worstaudio/bestaudio/best[height<=360]/best",
        "-N", "8",
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "exp=1:5",
        "--no-part",
        "-o", out_tmpl,
        url_or_path
    ]

    print("[audio] Downloading low-bitrate audio track...")
    t0 = time.time()
    success = False
    for attempt in range(1, 4):
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        if res.returncode == 0:
            success = True
            break
        print(f"[audio] Download attempt {attempt} failed, retrying in {attempt * 3}s...\n{res.stderr[-200:]}")
        time.sleep(attempt * 3)

    if not success:
        raise RuntimeError("Failed to download audio from video URL after 3 attempts.")
    t_down = max(0.5, time.time() - t0)

    # Convert to 16kHz mono WAV for Whisper & loudness analysis
    audio_files = [f for f in glob.glob(os.path.join(vid_dir, "audio.*")) if not f.endswith(".wav")]
    if not audio_files:
        raise RuntimeError("Audio download completed but no file was created.")

    src_audio = audio_files[0]
    mb_down = os.path.getsize(src_audio) / (1024 * 1024)
    update_stat("audio_mbps", (mb_down * 8.0) / t_down)

    subprocess.run(["ffmpeg", "-y", "-i", src_audio, "-vn", "-ac", "1", "-ar", "16000", wav_path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return wav_path


# ---------------------------------------------------------------- Step 3: Loudness Scan
def loudness_scan(wav_path):
    """
    Performs full audio energy analysis in milliseconds.
    Returns per-second RMS volume and sudden transient surges.
    """
    vals = []
    with wave.open(wav_path, "rb") as w:
        sr = w.getframerate()
        while True:
            b = w.readframes(sr * 60)
            if not b:
                break
            a = np.frombuffer(b, dtype=np.int16).astype(np.float32)
            n = len(a) // sr
            if n:
                vals.extend(np.sqrt((a[: n * sr].reshape(n, sr) ** 2).mean(axis=1)))

    vals = np.array(vals)
    norm = vals / (vals.max() + 1e-9)

    diffs = np.zeros_like(norm)
    if len(norm) > 1:
        diffs[1:] = np.maximum(0, norm[1:] - norm[:-1])

    return norm, diffs


def select_candidate_windows(energy, transients, count=15, min_dur=25, max_dur=50):
    """
    Finds top candidate action/screaming windows spread across the video.
    Prioritizes dynamic contrast (explosions, screaming, beat drops) over flat monotone noise,
    skips intro countdowns, and avoids clustering.
    """
    window_len = (min_dur + max_dur) // 2
    step = 5
    cands = []

    # For long streams (> 10 min), skip initial 120s of intro screen / countdown
    start_offset = 120 if len(energy) > 600 else 0

    for s in range(start_offset, max(1, len(energy) - window_len), step):
        e = s + window_len
        seg_e = energy[s:e]
        seg_t = transients[s:e]
        e_mean = float(seg_e.mean()) if len(seg_e) else 0.0
        e_max = float(seg_e.max()) if len(seg_e) else 0.0
        t_max = float(seg_t.max()) if len(seg_t) else 0.0
        e_std = float(seg_e.std()) if len(seg_e) else 0.0
        crest = e_max / (e_mean + 0.04)
        t_bursts = float((seg_t > 0.12).sum())

        # Highly rewards sudden explosions, jumpscares, screams, and dynamic swings
        score = (
            e_mean * 1.0 +
            e_max * 1.8 +
            t_max * 3.0 +
            e_std * 3.5 +
            min(3.0, crest * 0.8) +
            min(2.5, t_bursts * 0.3)
        )
        cands.append({"start": float(s), "end": float(e), "score": score})

    cands.sort(key=lambda c: c["score"], reverse=True)

    # Spread selection: enforce minimum distance between candidate starts
    picked = []
    min_dist = max(40, window_len + 5)
    for c in cands:
        if all(abs(c["start"] - p["start"]) >= min_dist for p in picked):
            picked.append(c)
        if len(picked) >= count:
            break

    return sorted(picked, key=lambda c: c["start"])


# ---------------------------------------------------------------- Step 4: Whisper
def transcribe_candidates(wav_path, candidates, model_size="base"):
    """
    Transcribes ONLY the candidate windows with Faster-Whisper.
    Returns:
      segments: list of (start, end, text)
      words: list of (start, end, word)
    """
    from faster_whisper import WhisperModel
    print(f"[whisper] Loading Faster-Whisper '{model_size}' on CPU (int8)...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    with wave.open(wav_path, "rb") as w:
        sr = w.getframerate()
        frames = w.readframes(w.getnframes())
        audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    all_segs = []
    all_words = []

    t0 = time.time()
    for idx, cand in enumerate(candidates, 1):
        s = max(0, int((cand["start"] - 4.0) * sr))
        e = min(len(audio_np), int((cand["end"] + 4.0) * sr))
        slice_audio = audio_np[s:e]
        offset = max(0.0, cand["start"] - 4.0)

        try:
            segs, _ = model.transcribe(slice_audio, word_timestamps=True, vad_filter=True)
            for seg in segs:
                all_segs.append((seg.start + offset, seg.end + offset, seg.text.strip()))
                for w_obj in seg.words or []:
                    all_words.append((w_obj.start + offset, w_obj.end + offset, w_obj.word.strip()))
        except Exception as ex:
            print(f"[whisper] Window #{idx} error: {ex}")

    t_whisper = max(0.5, time.time() - t0)
    total_audio_sec = sum(c["end"] - c["start"] for c in candidates)
    update_stat("whisper_factor", t_whisper / max(1.0, total_audio_sec))

    all_segs.sort(key=lambda s: s[0])
    all_words.sort(key=lambda w: w[0])
    return all_segs, all_words


# ---------------------------------------------------------------- Step 5: Rank & Trim
HYPE_KEYWORDS = [
    "no way", "bro", "yo", "omg", "oh my god", "wtf", "what the", "crazy", "insane",
    "dead", "dying", "scream", "run", "help", "wait", "nah", "let's go", "yooo", "cooked",
    "chill", "holy", "damn", "bruh", "fire", "shit", "fuck", "speed", "ronaldo", "sewy"
]


def hype_score(segments, start, end):
    txt = [t.lower() for s, e, t in segments if start <= s < end]
    if not txt:
        return 0.0
    hits = sum(t.count("!") + t.count("?") + sum(t.count(k) for k in HYPE_KEYWORDS) for t in txt)
    return min(1.5, hits / (2.5 + (end - start) / 6.0))


def snap_boundaries(start, end, words, min_len, max_len):
    """Snaps clip start to hook and end to sentence payoff within min/max bounds."""
    # Strict hard ceiling: no clip exceeds 58 seconds (YouTube Shorts & Reels strict limit)
    max_len = min(float(max_len), 58.0)
    clip_words = [w for w in words if start - 3.0 <= w[0] <= end + 3.0]
    if not clip_words:
        dur = end - start
        if dur < min_len: end = start + min_len
        if dur > max_len: end = start + max_len
        return round(start, 2), round(end, 2)

    # Snap start to closest word start
    start = clip_words[0][0]
    valid_ends = [w[1] for w in clip_words if min_len <= (w[1] - start) <= max_len]
    if valid_ends:
        end = valid_ends[-1]
    else:
        end = min(start + min_len, start + max_len)
    if (end - start) > max_len:
        end = start + max_len
    return round(start, 2), round(end, 2)


def compute_visual_motion(video_path, sample_count=6):
    """
    Computes rapid frame-difference motion score across a video clip using OpenCV.
    Returns motion energy score (higher = fast movement/explosions/cuts).
    """
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames < sample_count:
            cap.release()
            return 1.0
        indices = np.linspace(5, max(6, total_frames - 5), sample_count, dtype=int)
        prev_gray = None
        diffs = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (120, 68))
            if prev_gray is not None:
                diff = float(np.mean(cv2.absdiff(small, prev_gray)))
                diffs.append(diff)
            prev_gray = small
        cap.release()
        return float(np.mean(diffs)) if diffs else 1.0
    except Exception as ex:
        return 1.0


def rank_and_pick(candidates, segments, words, energy, transients, count=5,
                  min_len=20, max_len=55, use_ollama=False):
    """
    Ranks candidate moments using audio energy dynamics, transient bursts,
    speech hype, and crest factor. Trims boundaries cleanly.
    """
    has_speech = bool(words)

    for idx, c in enumerate(candidates, 1):
        s, e = c["start"], c["end"]
        if has_speech:
            s, e = snap_boundaries(s, e, words, min_len, max_len)
        else:
            if e - s < min_len: e = s + min_len
            if e - s > max_len: e = s + max_len
        # Strict hard cap: Every clip is guaranteed under 1 minute (<= 58s)
        if (e - s) > 58.0:
            e = s + 58.0
        c["start"], c["end"] = round(s, 2), round(e, 2)

        seg_e = energy[int(s):int(e)]
        seg_t = transients[int(s):int(e)]
        e_mean = float(seg_e.mean()) if len(seg_e) else 0.0
        e_max = float(seg_e.max()) if len(seg_e) else 0.0
        t_max = float(seg_t.max()) if len(seg_t) else 0.0
        e_std = float(seg_e.std()) if len(seg_e) else 0.0
        crest = e_max / (e_mean + 0.04)
        t_bursts = float((seg_t > 0.12).sum())

        h = hype_score(segments, s, e) if has_speech else 0.0

        # Dynamics + crest factor + speech hype score
        c["final"] = (
            e_mean * 1.0 +
            e_max * 1.6 +
            t_max * 2.8 +
            e_std * 3.0 +
            min(2.5, crest * 0.7) +
            min(2.0, t_bursts * 0.25) +
            (h * 2.0 if has_speech else 0.0)
        )

        # Title & reason generation
        title = f"Epic Moment #{idx:02d}"
        reason = "Intense audio action peak"
        if has_speech:
            c_segs = [t for a, b, t in segments if s <= a < e and len(t) > 2]
            if c_segs:
                title = c_segs[0].strip().strip('"').strip("'")[:45]
                reason = "High energy reaction & banter"
        c["title"] = title
        c["reason"] = reason

    candidates.sort(key=lambda c: c["final"], reverse=True)
    picked = []
    for c in candidates:
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
        if len(picked) >= count:
            break

    return sorted(picked, key=lambda c: c["start"])


# ---------------------------------------------------------------- Step 6: Download Segments
def download_winning_segments(url_or_path, winning_clips, work_dir):
    """
    Downloads ONLY the winning N segments in video (<=1080p).
    Never downloads the full video. Includes automatic retries and network recovery.
    """
    successful_pairs = []
    for idx, c in enumerate(winning_clips, 1):
        s, e = c["start"], c["end"]
        dur = e - s
        out_raw = os.path.join(work_dir, f"raw_clip_{idx:02d}.mp4")

        # Reuse existing segment if already downloaded and valid
        if os.path.exists(out_raw) and os.path.getsize(out_raw) > 50000:
            print(f"[segment] Reusing cached video segment #{idx} ({out_raw})")
            successful_pairs.append((out_raw, c))
            continue

        if os.path.exists(url_or_path):
            # Local video: cut segment directly with FFmpeg
            subprocess.run([
                "ffmpeg", "-y", "-ss", f"{s:.2f}", "-t", f"{dur:.2f}",
                "-i", url_or_path, "-c", "copy", out_raw
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            successful_pairs.append((out_raw, c))
            continue

        # YouTube URL: download exact time range
        sh = int(s // 3600); sm = int((s % 3600) // 60); ss = int(s % 60)
        eh = int(e // 3600); em = int((e % 3600) // 60); es = int(e % 60)
        sec_str = f"*{sh:02d}:{sm:02d}:{ss:02d}-{eh:02d}:{em:02d}:{es:02d}"

        cmd = get_ytdlp_base_cmd("android,ios,mweb") + [
            "-f", "bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]/best",
            "--merge-output-format", "mp4",
            "--no-part",
            "--download-sections", sec_str,
            "--force-keyframes-at-cuts",
            "--retries", "10",
            "--fragment-retries", "10",
            "--retry-sleep", "exp=1:5",
            "-N", "4",
            "-o", out_raw,
            url_or_path
        ]

        success = False
        for attempt in range(1, 4):
            print(f"[segment] Downloading winning clip #{idx} ({sec_str}) [attempt {attempt}/3]...")
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
            if proc.returncode == 0 and os.path.exists(out_raw) and os.path.getsize(out_raw) > 5000:
                success = True
                successful_pairs.append((out_raw, c))
                break
            else:
                err_snippet = proc.stderr[-200:] if proc.stderr else "Unknown error"
                print(f"[segment] Clip #{idx} attempt {attempt} failed, retrying in {attempt * 3}s:\n{err_snippet}")
                time.sleep(attempt * 3)

        if not success:
            print(f"[segment] ⚠️ Warning: Failed to download clip #{idx} after 3 attempts. Skipping this clip.")

    if not successful_pairs:
        raise RuntimeError("Failed to download any video segments from YouTube. Please check network connection.")

    return successful_pairs


# ---------------------------------------------------------------- Full Pipeline Orchestrator
def run_pipeline(url_or_path, clips_count=5, layout="top", fit="blur",
                 length="20-55", manual_facecam=None, enable_subs=DEFAULT_SUBS,
                 on_progress=None, on_clip_ready=None):
    """
    Executes the candidate-first clipping pipeline.
    `on_progress(stage_name, percent, eta_str)`: Callback for live progress UI.
    `on_clip_ready(clip_dict)`: Called immediately as each finished clip is rendered.
    """
    def log_p(stage, pct, eta=""):
        print(f"[{pct}%] {stage} {eta}")
        if on_progress:
            on_progress(stage, pct, eta)

    # Parse length bounds (strictly under 1 minute)
    try:
        min_l, max_l = [int(x) for x in length.split("-")]
    except Exception:
        min_l, max_l = 20, 50
    max_l = min(max_l, 58)
    min_l = min(min_l, max_l - 5)

    # 1. PROBE
    log_p("Probing video metadata...", 5)
    meta = probe_video(url_or_path)
    if meta["is_live"]:
        raise ValueError(f"Livestream '{meta['title']}' is currently LIVE. It must finish first to be clipped as a VOD.")

    vid_id = meta["video_id"]
    vid_cache = os.path.join(CACHE_DIR, vid_id)
    vid_work = os.path.join(WORK_DIR, vid_id)
    os.makedirs(vid_cache, exist_ok=True)
    os.makedirs(vid_work, exist_ok=True)

    # 2. AUDIO DOWNLOAD
    log_p("Downloading audio for fast loudness scan...", 20)
    wav_path = download_audio(url_or_path, vid_cache)

    # 3. LOUDNESS SCAN
    log_p("Scanning loudness profile & action peaks...", 40)
    energy, transients = loudness_scan(wav_path)
    candidates = select_candidate_windows(energy, transients, count=max(12, clips_count * 3),
                                          min_dur=min_l, max_dur=max_l)

    # 4. CANDIDATE TRANSCRIPTION
    log_p(f"Transcribing {len(candidates)} high-action candidate windows...", 55)
    segments, words = transcribe_candidates(wav_path, candidates, model_size=WHISPER_MODEL)

    # 5. RANK & SELECT WINNING CLIPS
    log_p("Ranking moments & snapping hooks...", 70)
    winning = rank_and_pick(candidates, segments, words, energy, transients,
                            count=clips_count, min_len=min_l, max_len=max_l)

    # 6. DOWNLOAD WINNING SEGMENTS ONLY
    log_p(f"Downloading {len(winning)} winning video segments...", 80)
    downloaded_pairs = download_winning_segments(url_or_path, winning, vid_work)
    raw_segments = [p[0] for p in downloaded_pairs]

    # 7. FACECAM / MODE DETECTION
    log_p("Analyzing facecam & visual composition...", 88)
    preview_img = os.path.join(vid_work, "facecam_preview.jpg")
    if manual_facecam and len(manual_facecam) == 4:
        is_streamer = True
        face_box = manual_facecam
        preview_path = None
        print(f"[pipeline] Using manual facecam override: {face_box}")
    else:
        is_streamer, face_box, preview_path = detect_facecam(raw_segments, out_preview_path=preview_img)

    # 7.1 Commentary classification
    total_cand_dur = sum(c["end"] - c["start"] for c in candidates)
    total_words = len(words)
    overall_wpm = (total_words / max(1.0, total_cand_dur)) * 60.0
    is_commentary = is_streamer or (total_words >= 15 and overall_wpm >= 20.0)
    print(f"[pipeline] Classification: {'COMMENTARY' if is_commentary else 'NO-COMMENTARY / PURE GAMEPLAY'} "
          f"(WPM={overall_wpm:.1f}, words={total_words}, streamer={is_streamer})")

    # Determine layout
    is_vertical = meta["is_vertical"]
    if is_vertical:
        final_layout = "as-is"
    elif is_streamer:
        final_layout = layout if layout in ("top", "topleft", "topright") else "top"
    else:
        # Non-streamer / no-comm: Centered 16:9 with clean solid black background (NO blurred video)
        final_layout = "pad" if fit not in ("crop", "blur") else fit

    # 8. RENDER AND DELIVER CLIPS
    log_p("Rendering 9:16 vertical clips...", 92)
    rendered_clips = []

    for idx, (raw_vid, c) in enumerate(downloaded_pairs, 1):
        out_clip = os.path.join(vid_work, f"clip_{idx:02d}.mp4")
        ass_path = os.path.join(vid_work, f"clip_{idx:02d}.ass")

        # Subtitles: disabled by default per user instruction ("no subs needed for the video")
        has_subs = False
        if enable_subs and words and is_commentary:
            has_subs = make_ass(words, c["start"], c["end"], ass_path, layout=final_layout, is_commentary=is_commentary)

        # Render clip
        render_clip(
            video_path=raw_vid,
            start=0.0,  # raw_vid is already cut to start
            end=c["end"] - c["start"],
            out_path=out_clip,
            layout=final_layout,
            face_box=face_box,
            is_vertical=is_vertical,
            ass_path=ass_path if has_subs else None
        )

        social_pack = generate_social_caption(
            clip_idx=idx,
            clip_meta=c,
            is_commentary=is_commentary,
            video_title=meta.get("title", "")
        )

        clip_info = {
            "id": idx,
            "path": out_clip,
            "title": c["title"],
            "reason": c["reason"],
            "start": c["start"],
            "end": c["end"],
            "duration": c["end"] - c["start"],
            "layout": final_layout,
            "face_box": face_box,
            "is_streamer": is_streamer,
            "is_commentary": is_commentary,
            "preview_img": preview_path,
            "insta_hook": social_pack["hook"],
            "insta_caption": social_pack["full_caption"],
            "insta_hashtags": social_pack["hashtags"]
        }
        rendered_clips.append(clip_info)

        # Send immediately when ready!
        if on_clip_ready:
            on_clip_ready(clip_info)

    # Save manifest for instant layout re-renders
    manifest = {
        "vid_id": vid_id,
        "is_streamer": is_streamer,
        "is_commentary": is_commentary,
        "face_box": face_box,
        "layout": final_layout,
        "clips": rendered_clips,
        "meta": meta
    }
    with open(os.path.join(vid_work, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    log_p("All clips generated successfully!", 100)
    return {
        "clips": rendered_clips,
        "is_streamer": is_streamer,
        "is_commentary": is_commentary,
        "face_box": face_box,
        "layout": final_layout,
        "preview_img": preview_path,
        "meta": meta
    }


def re_render_clips(vid_id, new_layout, on_clip_ready=None):
    """
    Instantly re-renders existing downloaded clips using a new layout (top/topleft/topright/blur/crop).
    Reuses existing raw video cuts and ASS subtitles without re-downloading or re-scanning!
    """
    vid_work = os.path.join(WORK_DIR, vid_id)
    manifest_path = os.path.join(vid_work, "manifest.json")
    if not os.path.exists(manifest_path):
        raise ValueError(f"No existing cached clips found for video {vid_id}.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    face_box = tuple(manifest.get("face_box", (0, 0, 0, 0)))
    is_vertical = manifest.get("meta", {}).get("is_vertical", False)
    new_clips = []

    for c in manifest.get("clips", []):
        idx = c["id"]
        raw_vid = os.path.join(vid_work, f"raw_clip_{idx:02d}.mp4")
        if not os.path.exists(raw_vid):
            continue
        out_clip = os.path.join(vid_work, f"clip_{idx:02d}_{new_layout}.mp4")
        ass_path = os.path.join(vid_work, f"clip_{idx:02d}.ass")

        render_clip(
            video_path=raw_vid,
            start=0.0,
            end=c["duration"],
            out_path=out_clip,
            layout=new_layout,
            face_box=face_box,
            is_vertical=is_vertical,
            ass_path=ass_path if os.path.exists(ass_path) else None
        )

        clip_info = dict(c)
        clip_info["path"] = out_clip
        clip_info["layout"] = new_layout
        new_clips.append(clip_info)
        if on_clip_ready:
            on_clip_ready(clip_info)

    manifest["layout"] = new_layout
    manifest["clips"] = new_clips
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main():
    ap = argparse.ArgumentParser(description="Universal Auto-Clipper CLI Engine")
    ap.add_argument("input", help="YouTube URL or local video file")
    ap.add_argument("--clips", type=int, default=DEFAULT_CLIPS, help="Number of clips to generate")
    ap.add_argument("--layout", default=DEFAULT_LAYOUT, choices=["top", "topleft", "topright"])
    ap.add_argument("--fit", default=DEFAULT_FIT, choices=["blur", "crop"])
    ap.add_argument("--length", default=DEFAULT_LENGTH, help="e.g. 20-55")
    a = ap.parse_args()

    t_start = time.time()
    res = run_pipeline(a.input, clips_count=a.clips, layout=a.layout, fit=a.fit, length=a.length)
    elapsed = time.time() - t_start
    print(f"\n===========================================================")
    print(f"  Done in {elapsed:.1f}s! Generated {len(res['clips'])} vertical clips.")
    for c in res["clips"]:
        print(f"  • Clip {c['id']}: {c['title']} ({c['duration']:.1f}s) -> {c['path']}")
    print(f"===========================================================")


if __name__ == "__main__":
    main()
