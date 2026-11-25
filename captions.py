"""
Karaoke Subtitle Generation (ASS format) with Active Word Highlight
Optimized for YouTube Shorts & Instagram Reels:
- Appears ONLY while commentary is actively spoken; disappears during silence or gameplay action.
- Positioned to prevent obstructing gameplay, crosshairs, or streamer facecams.
- Strictly disabled for no-commentary and pure gameplay videos.
"""
import os
import re

ASS_HEADER_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,54,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3.5,1.5,2,50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(t):
    """Formats seconds into ASS timestamp hh:mm:ss.cc"""
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def calculate_wpm(words, duration):
    """Calculates words per minute within a duration."""
    if not words or duration <= 0:
        return 0.0
    return (len(words) / duration) * 60.0


def clean_word(txt):
    """Sanitizes words for ASS subtitles."""
    clean = re.sub(r'[\{\}\\]', '', txt).strip().upper()
    return clean


def segment_into_phrases(words, max_pause=0.45, max_words=3):
    """
    Groups words into short, natural speech bursts.
    Splits immediately whenever there is a speech pause (> max_pause),
    ensuring subtitles never linger across silence or gameplay.
    """
    if not words:
        return []

    phrases = []
    current_phrase = []

    for idx, w in enumerate(words):
        if not current_phrase:
            current_phrase.append(w)
            continue

        prev_w = current_phrase[-1]
        pause = w[0] - prev_w[1]

        # Break phrase on pause, length, or punctuation
        has_break_punct = bool(re.search(r'[.!?]$', prev_w[2]))
        if pause > max_pause or len(current_phrase) >= max_words or has_break_punct:
            phrases.append(current_phrase)
            current_phrase = [w]
        else:
            current_phrase.append(w)

    if current_phrase:
        phrases.append(current_phrase)

    return phrases


def make_ass(words, start, end, out_path, layout="top", is_commentary=True, min_wpm=20.0):
    """
    Creates an ASS subtitle file with animated yellow karaoke highlighting.
    
    Rules:
    - If is_commentary is False: returns False immediately (no subtitles for no-commentary videos).
    - If speech is sparse (WPM < min_wpm or words < 6): returns False (skip in-game one-offs/music).
    - Subtitles appear ONLY when speech is actively occurring, clearing the screen during pauses.
    - Placed safely so it does not block the gameplay area.
    """
    # 1. No commentary -> No subtitles
    if not is_commentary:
        print("[captions] Video is no-commentary / pure gameplay. Subtitles disabled.")
        return False

    dur = end - start
    # Filter words strictly within this clip
    ws = [w for w in words if w[0] >= (start - 0.15) and w[1] <= (end + 0.35)]
    if len(ws) < 6:
        print(f"[captions] Insufficient speech words ({len(ws)} < 6). Skipping subtitles.")
        return False

    wpm = calculate_wpm(ws, dur)
    if wpm < min_wpm:
        print(f"[captions] Speech rate {wpm:.1f} WPM is below threshold ({min_wpm}). Skipping subtitles.")
        return False

    # 2. Position subtitles safely away from the gameplay center
    # For 'top' layout (facecam 0-640 top, gameplay 640-1920):
    # MarginV=320 places text at Y=1600 (lower third of gameplay, well below crosshair/player at 1280)
    # For 'pad' / 'center' layout (16:9 centered at Y=656..1264):
    # MarginV=520 places text at Y=1400 (directly inside the bottom dark letterbox space, NOT covering video!)
    if layout == "top":
        margin_v = 320
    elif layout in ("topleft", "topright"):
        margin_v = 320
    elif layout in ("pad", "center", "solid"):
        margin_v = 520
    else:
        margin_v = 320

    header = ASS_HEADER_TEMPLATE.format(margin_v=margin_v)
    lines = [header]

    # 3. Group words into natural spoken phrases by silence
    phrases = segment_into_phrases(ws, max_pause=0.45, max_words=3)

    dialogue_count = 0
    for p in phrases:
        p_start_abs = p[0][0]
        p_end_abs = p[-1][1]

        # Convert to clip-relative time
        p_t0 = max(0.0, p_start_abs - start)
        p_t1 = min(dur, max(p_t0 + 0.2, p_end_abs - start + 0.15))

        for j, curr in enumerate(p):
            t_word_start = max(0.0, curr[0] - start)
            
            # End time for this word's highlight
            if j + 1 < len(p):
                # Highlight until next word starts, but no longer than word end + 0.2s
                t_word_end = min(p[j + 1][0] - start, curr[1] - start + 0.2)
            else:
                # Last word in phrase ends with the phrase
                t_word_end = p_t1

            t_word_start = max(0.0, t_word_start)
            t_word_end = max(t_word_start + 0.1, t_word_end)

            # Build karaoke highlighted text
            parts = []
            for k, w_obj in enumerate(p):
                w_text = clean_word(w_obj[2])
                if not w_text:
                    continue
                if k == j:
                    # Highlight current word in vibrant yellow (&H00FFFF& in BGR) with slight scale
                    parts.append("{\\c&H00FFFF&\\fscx106\\fscy106}" + w_text + "{\\rDefault}")
                else:
                    # Surrounding words in phrase remain in crisp white (&HFFFFFF&)
                    parts.append("{\\c&HFFFFFF&}" + w_text + "{\\rDefault}")

            if parts:
                phrase_text = " ".join(parts)
                lines.append(f"Dialogue: 0,{ass_time(t_word_start)},{ass_time(t_word_end)},Default,,0,0,0,,{phrase_text}\n")
                dialogue_count += 1

    if dialogue_count == 0:
        return False

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    print(f"[captions] Generated clean karaoke subtitles ({dialogue_count} cue lines).")
    return True
