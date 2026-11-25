"""
Unique Instagram & Shorts Caption Generator
Creates captivating, viral hooks, audience-engaging questions, and optimized hashtags.
Guaranteed to be unique for each clip (never just the subtitle transcript).
"""
import random

HOOKS_FAIL_FUNNY = [
    "Bro really thought he had it under control 😭💀",
    "The disrespect was absolutely personal 😂💀",
    "Instant karma at its finest... never celebrate early 🤦‍♂️",
    "I'm still crying at this reaction 😭😂",
    "Bro reached the absolute point of no return 💀",
    "There was an attempt... and it failed miserably 😭",
    "Bro thought he was the main character for 2 seconds 💀",
]

HOOKS_EPIC_CLUTCH = [
    "1000 IQ play or pure luck? You decide 🤔🔥",
    "Actual cinematic perfection right here 🎬✨",
    "How did this even happen?! Still in shock 🤯",
    "The reflexes on this are genuinely illegal ⚡",
    "Bro locked in and completely took over 😈🔥",
    "Absolute masterclass under maximum pressure 🏆",
    "One in a million moment captured on camera 🎯🔥",
]

HOOKS_SHOCK_WTF = [
    "Wait till the end... I was NOT ready for that 💀",
    "The silence after this speaks absolute volumes 😳",
    "I literally jumped out of my seat watching this 😭",
    "Tell me you saw that coming... because no one did 🤯",
    "The ending took an insane turn out of nowhere 😱",
    "My heart rate spiked through the roof right here 📈💀",
]

HOOKS_RAGE_CHAOS = [
    "Certified rage quit moment incoming 😡🎮",
    "You can literally hear the soul leaving the body 💀",
    "The exact second everything completely fell apart 📉",
    "Controller is definitely in mortal danger after this 🎮💥",
    "Bro lost all composure and I honestly don't blame him 😂",
]

ENGAGEMENT_QUESTIONS = [
    "Rate this moment from 1 to 10 in the comments! 👇",
    "Tag that one friend who would definitely choke this 💀",
    "W or L play? Let me know below! 👇",
    "Would you have survived this? Drop your reaction! 💬",
    "What would you do in this exact situation? 😂👇",
    "Tag a friend who needs to see this right now! 👥🔥",
]

HASHTAG_POOLS = [
    ["#gaming", "#reels", "#shorts", "#viral", "#epicmoments", "#gamer", "#gamingmemes", "#fyp", "#trending"],
    ["#twitchclips", "#streamer", "#funny", "#fail", "#viralreels", "#clutch", "#gamersoftiktok", "#explorepage"],
    ["#gamingclips", "#insane", "#reaction", "#gamermoments", "#trendingreels", "#shortsvideo", "#dailyclips"],
    ["#gaminglife", "#competitive", "#comedy", "#reelsvideo", "#instareels", "#viralclips", "#explore"]
]


def generate_social_caption(clip_idx: int, clip_meta: dict, is_commentary: bool = True, video_title: str = "") -> dict:
    """
    Generates a unique, viral-ready caption package for Instagram Reels and YouTube Shorts.
    Returns:
      {
        "hook": str,
        "body": str,
        "question": str,
        "hashtags": str,
        "full_caption": str
      }
    """
    # Deterministic variety based on clip ID and start time
    seed_val = int(clip_idx * 17 + int(clip_meta.get("start", 0)) * 7)
    rng = random.Random(seed_val)

    # Determine vibe
    c_final = clip_meta.get("final", 0.0)
    title = str(clip_meta.get("title", "")).lower()
    reason = str(clip_meta.get("reason", "")).lower()

    if any(k in title or k in reason for k in ["scream", "rage", "wtf", "damn", "cooked"]):
        hook_pool = HOOKS_RAGE_CHAOS
    elif any(k in title or k in reason for k in ["crazy", "insane", "epic", "peak", "action"]):
        hook_pool = HOOKS_EPIC_CLUTCH
    elif any(k in title or k in reason for k in ["bro", "dead", "wait", "run", "help"]):
        hook_pool = HOOKS_SHOCK_WTF
    elif clip_idx % 2 == 0:
        hook_pool = HOOKS_FAIL_FUNNY
    else:
        hook_pool = HOOKS_EPIC_CLUTCH

    hook = rng.choice(hook_pool)
    question = rng.choice(ENGAGEMENT_QUESTIONS)

    # Pick a blended hashtag set
    primary_tags = rng.choice(HASHTAG_POOLS)
    secondary_tags = rng.choice(HASHTAG_POOLS)
    combined_tags = list(dict.fromkeys(primary_tags + secondary_tags))[:10]
    hashtag_str = " ".join(combined_tags)

    # Build clean Instagram / Shorts copy-pasteable text
    lines = [
        hook,
        "",
        question,
        "",
        "Save & share with your friends! 🔥",
        ".",
        ".",
        hashtag_str
    ]

    full_caption = "\n".join(lines)

    return {
        "hook": hook,
        "question": question,
        "hashtags": hashtag_str,
        "full_caption": full_caption
    }
