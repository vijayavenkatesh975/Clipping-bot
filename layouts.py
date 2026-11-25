"""
FFmpeg Layout Filter Graphs and Rendering Engine
Supports:
  - Streamer Modes: top (1080x640 facecam top + 1080x1280 gameplay bottom), topleft, topright
  - Normal Modes: blur (blurred background), crop (center crop), as-is (vertical source)
"""
import os
import shutil
import subprocess

_NVENC_AVAILABLE = None


def check_nvenc_support():
    """Dynamically tests if NVENC hardware encoder works on this system."""
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE

    try:
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=30",
            "-c:v", "h264_nvenc", "-f", "null", "-"
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _NVENC_AVAILABLE = (res.returncode == 0)
    except Exception:
        _NVENC_AVAILABLE = False

    return _NVENC_AVAILABLE


def get_video_encoder():
    """Returns optimal video encoder settings."""
    if check_nvenc_support():
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "24"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]


def build_filter_complex(layout, face_box, is_vertical=False, ass_name=None):
    """
    Constructs the FFmpeg -filter_complex graph.
    `face_box` is (x, y, w, h) as fractions (0.0 to 1.0).
    """
    has_sub = bool(ass_name)

    # 1. If source is already vertical (9:16)
    if is_vertical or layout == "as-is":
        fc = "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(1080-iw)/2:(1920-ih)/2"
        if has_sub:
            fc += f",subtitles={ass_name}"
        fc += "[outv]"
        return fc

    # 2. Normal Mode: Clean Solid/Dark Background (Centered, NO blurred video)
    if layout in ("pad", "center", "solid"):
        fc = "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(1080-iw)/2:(1920-ih)/2:color=black"
        if has_sub:
            fc += f",subtitles={ass_name}"
        fc += "[outv]"
        return fc

    # 3. Normal Mode: Blur Background (optional legacy)
    if layout == "blur":
        fc = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:4,scale=1080:1920[blurred];"
            "[fg]scale=1080:-2[scaled];"
            "[blurred][scaled]overlay=(W-w)/2:(H-h)/2"
        )
        if has_sub:
            fc += f",subtitles={ass_name}"
        fc += "[outv]"
        return fc

    # 4. Normal Mode: Center Crop (Crop 16:9 into 9:16 center)
    if layout == "crop":
        fc = "[0:v]crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920"
        if has_sub:
            fc += f",subtitles={ass_name}"
        fc += "[outv]"
        return fc

    # 5. Streamer Modes with Facecam (face_box = fx, fy, fw, fh)
    fx, fy, fw, fh = face_box

    if layout == "top":
        # Top 1080x640 (Facecam) + Bottom 1080x1280 (Gameplay)
        fc = (
            "[0:v]split=2[a][b];"
            f"[a]crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},"
            "scale=1080:640:force_original_aspect_ratio=increase,crop=1080:640[face];"
            "[b]scale=-2:1280,crop=1080:1280[game];"
            "[face][game]vstack=inputs=2"
        )
        if has_sub:
            fc += f",subtitles={ass_name}"
        fc += "[outv]"
        return fc

    elif layout == "topleft":
        # Full 1080x1920 gameplay with facecam overlay in top-left
        fc = (
            "[0:v]split=3[bg_in][fg_in][face_in];"
            "[bg_in]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:4,scale=1080:1920[bg_blur];"
            "[fg_in]scale=1080:-2[fg_game];"
            "[bg_blur][fg_game]overlay=(W-w)/2:(H-h)/2[game_full];"
            f"[face_in]crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},"
            "scale=360:214:force_original_aspect_ratio=increase,crop=360:214,"
            "drawbox=x=0:y=0:w=360:h=214:color=white@0.9:t=4[face_pip];"
            "[game_full][face_pip]overlay=36:60"
        )
        if has_sub:
            fc += f",subtitles={ass_name}"
        fc += "[outv]"
        return fc

    elif layout == "topright":
        # Full 1080x1920 gameplay with facecam overlay in top-right
        fc = (
            "[0:v]split=3[bg_in][fg_in][face_in];"
            "[bg_in]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:4,scale=1080:1920[bg_blur];"
            "[fg_in]scale=1080:-2[fg_game];"
            "[bg_blur][fg_game]overlay=(W-w)/2:(H-h)/2[game_full];"
            f"[face_in]crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},"
            "scale=360:214:force_original_aspect_ratio=increase,crop=360:214,"
            "drawbox=x=0:y=0:w=360:h=214:color=white@0.9:t=4[face_pip];"
            "[game_full][face_pip]overlay=W-w-36:60"
        )
        if has_sub:
            fc += f",subtitles={ass_name}"
        fc += "[outv]"
        return fc

    # Fallback to clean solid centered background
    fc = "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(1080-iw)/2:(1920-ih)/2:color=black"
    if has_sub:
        fc += f",subtitles={ass_name}"
    fc += "[outv]"
    return fc


def render_clip(video_path, start, end, out_path, layout="top", face_box=(0, 0, 0, 0),
                is_vertical=False, ass_path=None):
    """
    Renders a vertical 1080x1920 clip from video_path.
    """
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    out_name = os.path.basename(out_path)

    ass_name = None
    if ass_path and os.path.exists(ass_path):
        ass_name = os.path.basename(ass_path)
        # Copy or ensure ass is in working dir for relative FFmpeg subtitles filter
        work_ass = os.path.join(out_dir, ass_name)
        if os.path.abspath(ass_path) != os.path.abspath(work_ass):
            shutil.copy2(ass_path, work_ass)

    fc = build_filter_complex(layout, face_box, is_vertical=is_vertical, ass_name=ass_name)
    v_enc = get_video_encoder()
    dur = max(0.5, end - start)

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.2f}",
        "-t", f"{dur:.2f}",
        "-i", video_path,
        "-filter_complex", fc,
        "-map", "[outv]",
        "-map", "0:a?",
    ] + v_enc + [
        "-maxrate", "4M",
        "-bufsize", "8M",
        "-c:a", "aac",
        "-b:a", "160k",
        "-movflags", "+faststart",
        out_name
    ]

    print(f"[render] Rendering {out_name} ({dur:.1f}s) layout={layout}...")
    res = subprocess.run(cmd, cwd=out_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed:\n{res.stderr[-400:]}")

    return out_path
