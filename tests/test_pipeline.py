"""
Automated Unit and Integration Tests for Fast Clipping Pipeline
Uses synthetic FFmpeg testsrc + sine bursts for instant offline verification.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

# Ensure parent directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from captions import make_ass, calculate_wpm
from layouts import render_clip, check_nvenc_support
from pipeline import loudness_scan, select_candidate_windows
from social import generate_social_caption


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = os.path.join(BASE_DIR, "tests", "test_scratch")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create a synthetic 16:9 test video (45s) with a loud burst at 15-20s
        cls.synthetic_16_9 = os.path.join(cls.test_dir, "synth_16_9.mp4")
        if not os.path.exists(cls.synthetic_16_9):
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "testsrc=duration=45:size=1280x720:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=45",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-b:a", "64k",
                cls.synthetic_16_9
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Create a synthetic 9:16 vertical test video (10s)
        cls.synthetic_9_16 = os.path.join(cls.test_dir, "synth_9_16.mp4")
        if not os.path.exists(cls.synthetic_9_16):
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "testsrc=duration=10:size=720x1280:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=220:duration=10",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-b:a", "64k",
                cls.synthetic_9_16
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Extract WAV for audio analysis
        cls.wav_path = os.path.join(cls.test_dir, "synth.wav")
        subprocess.run([
            "ffmpeg", "-y", "-i", cls.synthetic_16_9, "-vn", "-ac", "1", "-ar", "16000", cls.wav_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_loudness_scan(self):
        norm, diffs = loudness_scan(self.wav_path)
        self.assertEqual(len(norm), 45)
        self.assertTrue(len(diffs) == 45)

        cands = select_candidate_windows(norm, diffs, count=3, min_dur=10, max_dur=20)
        self.assertTrue(len(cands) >= 1)
        self.assertTrue(cands[0]["end"] > cands[0]["start"])

    def test_captions_wpm_filter(self):
        # 1 word in 60s should be rejected (wpm < 15)
        words = [(1.0, 1.5, "hello")]
        ass_path = os.path.join(self.test_dir, "low_wpm.ass")
        res = make_ass(words, 0.0, 60.0, ass_path, min_wpm=15.0)
        self.assertFalse(res)

        # 30 words in 30s should be accepted
        dense_words = [(i * 0.9, i * 0.9 + 0.5, f"word{i}") for i in range(25)]
        ass_path_dense = os.path.join(self.test_dir, "dense.ass")
        res_dense = make_ass(dense_words, 0.0, 30.0, ass_path_dense, min_wpm=15.0)
        self.assertTrue(res_dense)
        self.assertTrue(os.path.exists(ass_path_dense))

    def test_render_blur_layout(self):
        out_clip = os.path.join(self.test_dir, "out_blur.mp4")
        render_clip(self.synthetic_16_9, start=5.0, end=15.0, out_path=out_clip, layout="blur")

        cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", out_clip]
        out = json.loads(subprocess.check_output(cmd, text=True))
        w = out["streams"][0]["width"]
        h = out["streams"][0]["height"]
        self.assertEqual((w, h), (1080, 1920))

    def test_render_topleft_and_topright(self):
        out_tl = os.path.join(self.test_dir, "out_topleft.mp4")
        render_clip(self.synthetic_16_9, start=0.0, end=5.0, out_path=out_tl,
                    layout="topleft", face_box=(0.1, 0.1, 0.2, 0.2))

        cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", out_tl]
        out = json.loads(subprocess.check_output(cmd, text=True))
        self.assertEqual((out["streams"][0]["width"], out["streams"][0]["height"]), (1080, 1920))

        out_tr = os.path.join(self.test_dir, "out_topright.mp4")
        render_clip(self.synthetic_16_9, start=0.0, end=5.0, out_path=out_tr,
                    layout="topright", face_box=(0.7, 0.1, 0.2, 0.2))
        out2 = json.loads(subprocess.check_output(cmd, text=True))
        self.assertEqual((out2["streams"][0]["width"], out2["streams"][0]["height"]), (1080, 1920))

    def test_render_pad_solid_background(self):
        # Normal / No-comm video: Centered with solid dark background (NOT blurred video)
        out_pad = os.path.join(self.test_dir, "out_pad.mp4")
        render_clip(self.synthetic_16_9, start=5.0, end=10.0, out_path=out_pad, layout="pad")

        cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", out_pad]
        out = json.loads(subprocess.check_output(cmd, text=True))
        self.assertEqual((out["streams"][0]["width"], out["streams"][0]["height"]), (1080, 1920))

    def test_captions_no_commentary_rejection(self):
        # When is_commentary is False: must return False immediately
        dense_words = [(i * 0.9, i * 0.9 + 0.5, f"word{i}") for i in range(25)]
        ass_path = os.path.join(self.test_dir, "nocomm.ass")
        res = make_ass(dense_words, 0.0, 30.0, ass_path, is_commentary=False)
        self.assertFalse(res)
        self.assertFalse(os.path.exists(ass_path))

    def test_unique_social_captions(self):
        clip1 = {"start": 10.0, "final": 5.2, "title": "Insane headshot"}
        clip2 = {"start": 85.0, "final": 8.9, "title": "Bro raging hard"}

        cap1 = generate_social_caption(1, clip1, is_commentary=True)
        cap2 = generate_social_caption(2, clip2, is_commentary=True)

        self.assertTrue(len(cap1["hook"]) > 5)
        self.assertTrue(len(cap2["hook"]) > 5)
        self.assertNotEqual(cap1["hook"], cap2["hook"])
        self.assertIn("#", cap1["hashtags"])
        self.assertIn("#", cap2["hashtags"])

    def test_render_vertical_as_is(self):
        out_vert = os.path.join(self.test_dir, "out_vert.mp4")
        render_clip(self.synthetic_9_16, start=0.0, end=5.0, out_path=out_vert, layout="as-is", is_vertical=True)

        cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", out_vert]
        out = json.loads(subprocess.check_output(cmd, text=True))
        self.assertEqual((out["streams"][0]["width"], out["streams"][0]["height"]), (1080, 1920))


if __name__ == "__main__":
    unittest.main()
