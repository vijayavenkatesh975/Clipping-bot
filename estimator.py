"""
Dynamic Job Time Estimator and Stats Tracking
Maintains moving averages of download, transcription, and rendering speeds.
Provides auto-degradation to strictly adhere to MAX_JOB_MINUTES.
"""
import json
import os
import time

STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.json")

DEFAULT_STATS = {
    "audio_mbps": 12.0,              # Audio download speed in Mbps
    "loudness_scan_factor": 180.0,   # Times faster than real-time (decoding wav/pcm)
    "whisper_factor": 0.04,          # Whisper CPU real-time factor (0.04 = 25x faster than real-time)
    "llm_per_cand_sec": 2.5,         # Ollama seconds per window
    "segment_mbps": 15.0,            # Video segment download speed in Mbps
    "render_speed_factor": 1.3       # FFmpeg render speed factor (1.3x real-time)
}


def load_stats():
    if os.path.exists(STATS_PATH):
        try:
            with open(STATS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                res = DEFAULT_STATS.copy()
                res.update(data)
                return res
        except Exception:
            pass
    return DEFAULT_STATS.copy()


def save_stats(stats):
    try:
        with open(STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception:
        pass


def update_stat(key, measured_val, weight=0.25):
    """Updates a metric using exponential moving average."""
    stats = load_stats()
    old_val = stats.get(key, DEFAULT_STATS.get(key, measured_val))
    stats[key] = round(old_val * (1.0 - weight) + measured_val * weight, 3)
    save_stats(stats)


def estimate_pipeline_time(duration_sec, clips_count=5, max_budget_min=10, has_ollama=False):
    """
    Computes expected processing time and auto-degradation plan.
    Returns:
      est_seconds: float
      range_str: str (e.g. "About 3 min. Range 2-5 min")
      plan: dict with degradation adjustments
    """
    stats = load_stats()
    plan = {
        "candidate_multiplier": 3,
        "whisper_model": "base",
        "use_ollama": has_ollama,
        "degraded": False,
        "reason": ""
    }

    def calc(c_mult, w_model, use_llm):
        t_probe = 2.0
        # Low bitrate audio (~48kbps = 0.048 Mbps)
        audio_mb = (duration_sec * 0.048) / 8.0
        t_audio = max(3.0, (audio_mb * 8.0) / stats["audio_mbps"])

        # Loudness scan
        t_scan = max(1.0, duration_sec / stats["loudness_scan_factor"])

        # Candidate windows (~45s each)
        cand_count = clips_count * c_mult
        whisper_factor = stats["whisper_factor"] if w_model == "base" else (stats["whisper_factor"] * 0.5)
        t_whisper = max(2.0, (cand_count * 45.0) * whisper_factor)

        t_llm = (cand_count * stats["llm_per_cand_sec"]) if use_llm else 0.0

        # Video segment download (~3.5 Mbps for 720p60)
        seg_mb = (clips_count * 45.0 * 3.5) / 8.0
        t_segments = max(4.0, (seg_mb * 8.0) / stats["segment_mbps"])

        # Render
        t_render = max(4.0, (clips_count * 45.0) / stats["render_speed_factor"])

        return t_probe + t_audio + t_scan + t_whisper + t_llm + t_segments + t_render

    budget_sec = max_budget_min * 60.0
    est = calc(plan["candidate_multiplier"], plan["whisper_model"], plan["use_ollama"])

    # Auto-Degradation if exceeding time budget
    if est > budget_sec:
        plan["degraded"] = True
        plan["candidate_multiplier"] = 2
        plan["use_ollama"] = False
        plan["reason"] = f"Budget constraint ({max_budget_min}m): reduced candidate windows to 2x and bypassed LLM."
        est = calc(plan["candidate_multiplier"], plan["whisper_model"], False)

    if est > budget_sec:
        plan["whisper_model"] = "tiny"
        plan["reason"] += " Switched to Whisper 'tiny' for ultra-fast candidate transcription."
        est = calc(plan["candidate_multiplier"], "tiny", False)

    # Format human-friendly range
    est_min = max(1, int(round(est / 60.0)))
    low_min = max(1, int((est * 0.75) // 60))
    high_min = max(low_min + 1, int((est * 1.35) // 60) + 1)
    range_str = f"About {est_min} min. Range {low_min}-{high_min} min"

    return est, range_str, plan
