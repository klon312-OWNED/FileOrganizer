"""Тесты v1.11.0: уведомления, настройки окна, видео, экспорт."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestSortNotifyBatcher(unittest.TestCase):
    def test_batches_multiple_files(self):
        from organizer.notify import SortNotifyBatcher

        shown: list[tuple[str, str]] = []

        def fake_show(title, msg):
            shown.append((title, msg))

        batcher = SortNotifyBatcher(debounce_sec=0.05)
        with mock.patch("organizer.notify.show_toast", side_effect=fake_show):
            batcher.add("a.txt")
            batcher.add("b.txt")
            batcher.add("c.txt")
            threading.Event().wait(0.15)

        self.assertEqual(len(shown), 1)
        self.assertIn("3", shown[0][1])

    def test_single_file_message(self):
        from organizer.notify import SortNotifyBatcher

        shown: list[str] = []

        batcher = SortNotifyBatcher(debounce_sec=0.05)
        with mock.patch("organizer.notify.show_toast", side_effect=lambda _t, m: shown.append(m)):
            batcher.add("one.pdf")
            threading.Event().wait(0.15)

        self.assertEqual(len(shown), 1)
        self.assertIn("1", shown[0])


class TestWindowSettings(unittest.TestCase):
    def test_preview_zoom_clamped(self):
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"preview_zoom": 5.0, "window_geometry": "800x600+10+20"}),
                encoding="utf-8",
            )
            with mock.patch("organizer.config.SETTINGS_PATH", settings_path):
                s = Settings()
            self.assertEqual(s.preview_zoom, 2.0)
            self.assertEqual(s.window_geometry, "800x600+10+20")


class TestVideoProbe(unittest.TestCase):
    def test_probe_missing_file(self):
        from organizer.video_player import probe_video_failure

        reason = probe_video_failure(Path("/nonexistent/video.mp4"))
        self.assertIn("не найден", reason.lower())

    def test_probe_bad_file(self):
        from organizer.video_player import probe_video_failure

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "fake.mp4"
            bad.write_bytes(b"not a video")
            reason = probe_video_failure(bad)
        self.assertTrue(reason)


class TestPreviewZoomPersistence(unittest.TestCase):
    def test_zoom_callback(self):
        import tkinter as tk
        from organizer.preview_panel import PreviewPanel

        saved: list[float] = []

        root = tk.Tk()
        root.withdraw()
        try:
            panel = PreviewPanel(
                root, width=300, show_meta=False,
                initial_zoom=1.5, on_zoom_change=lambda z: saved.append(z),
            )
            panel._current_path = Path("dummy.png")
            with mock.patch.object(panel, "_refresh_image_zoom"):
                panel._on_zoom("1.25")
            self.assertAlmostEqual(saved[0], 1.25)
            self.assertAlmostEqual(panel._zoom, 1.25)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
