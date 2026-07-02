"""Тесты встроенного видеоплеера и интеграции в PreviewPanel."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_test_video(path: Path, *, frames: int = 20, fps: float = 10.0) -> None:
    import cv2
    import numpy as np

    w, h = 96, 64
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
    try:
        for i in range(frames):
            color = (i * 10 % 255, 40, 120)
            frame = np.full((h, w, 3), color, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


class TestVideoPlayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import cv2  # noqa: F401
            from PIL import Image  # noqa: F401
            cls._has_deps = True
        except ImportError:
            cls._has_deps = False

    def setUp(self):
        if not self._has_deps:
            self.skipTest("cv2/PIL not available")
        import tkinter as tk
        from organizer.video_player import VideoPlayer

        self._root = tk.Tk()
        self._root.withdraw()
        self._player = VideoPlayer(self._root)

    def tearDown(self):
        self._player.stop()
        self._root.destroy()

    def test_load_valid_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            vpath = Path(tmp) / "clip.mp4"
            _make_test_video(vpath)
            self.assertTrue(self._player.load(vpath))
            self.assertIsNotNone(self._player._cap)
            self.assertTrue(self._player._cap.isOpened())
            self._player.stop()

    def test_stop_releases_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            vpath = Path(tmp) / "clip.mp4"
            _make_test_video(vpath)
            self.assertTrue(self._player.load(vpath))
            cap = self._player._cap
            self._player.stop()
            self.assertIsNone(self._player._cap)
            self.assertFalse(cap.isOpened())

    def test_load_replaces_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            v1 = Path(tmp) / "a.mp4"
            v2 = Path(tmp) / "b.mp4"
            _make_test_video(v1, frames=10)
            _make_test_video(v2, frames=15)
            self.assertTrue(self._player.load(v1))
            cap1 = self._player._cap
            self.assertTrue(self._player.load(v2))
            self.assertFalse(cap1.isOpened())
            self.assertIsNotNone(self._player._cap)
            self.assertTrue(self._player._cap.isOpened())
            self._player.stop()

    def test_load_missing_file(self):
        self.assertFalse(self._player.load(Path("/nonexistent/video.mp4")))

    def test_play_pause_toggle(self):
        with tempfile.TemporaryDirectory() as tmp:
            vpath = Path(tmp) / "clip.mp4"
            _make_test_video(vpath, frames=30)
            self.assertTrue(self._player.load(vpath))
            self._player.play()
            self.assertTrue(self._player._playing)
            self._player.pause()
            self.assertFalse(self._player._playing)
            self._player.stop()

    def test_load_failure_on_bad_codec(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "fake.mp4"
            bad.write_bytes(b"not a video file")
            self.assertFalse(self._player.load(bad))
            self.assertIsNone(self._player._cap)


class TestVideoPlayerUnavailable(unittest.TestCase):
    def test_is_available_false_without_cv2(self):
        import organizer.video_player as vp

        with mock.patch.object(vp, "_HAS_CV2", False):
            self.assertFalse(vp.VideoPlayer.is_available())


class TestPreviewPanelVideo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import cv2  # noqa: F401
            from PIL import Image  # noqa: F401
            cls._has_deps = True
        except ImportError:
            cls._has_deps = False

    def setUp(self):
        if not self._has_deps:
            self.skipTest("cv2/PIL not available")
        import tkinter as tk
        from organizer.preview_panel import PreviewPanel

        self._root = tk.Tk()
        self._root.withdraw()
        self._panel = PreviewPanel(self._root, width=360, show_meta=False)

    def tearDown(self):
        self._panel.clear()
        self._root.destroy()

    def test_show_video_activates_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            vpath = Path(tmp) / "preview.mp4"
            _make_test_video(vpath)
            self._panel.show(vpath)
            self.assertTrue(self._panel._video_mode)
            self.assertIsNotNone(self._panel._video_player._cap)
            self._panel.clear()

    def test_clear_stops_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            vpath = Path(tmp) / "preview.mp4"
            _make_test_video(vpath)
            self._panel.show(vpath)
            cap = self._panel._video_player._cap
            self._panel.clear()
            self.assertFalse(self._panel._video_mode)
            self.assertIsNone(self._panel._video_player._cap)
            if cap is not None:
                self.assertFalse(cap.isOpened())

    def test_file_change_stops_previous_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            v1 = Path(tmp) / "a.mp4"
            v2 = Path(tmp) / "b.mp4"
            _make_test_video(v1)
            _make_test_video(v2)
            self._panel.show(v1)
            cap1 = self._panel._video_player._cap
            self._panel.show(v2)
            if cap1 is not None:
                self.assertFalse(cap1.isOpened())
            self.assertIsNotNone(self._panel._video_player._cap)
            self._panel.clear()

    def test_video_fallback_to_thumbnail(self):
        import organizer.preview_panel as pp

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.mp4"
            bad.write_bytes(b"not video")
            with mock.patch.object(pp.VideoPlayer, "is_available", return_value=True):
                with mock.patch.object(pp.VideoPlayer, "load", return_value=False):
                    self._panel.show(bad)
            self.assertFalse(self._panel._video_mode)


if __name__ == "__main__":
    unittest.main()
