import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QRect, Qt, QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from runtime.helper import EventRecorder, run_visual
from runtime.tests.video_fixture import make_video


@unittest.skipUnless(QApplication is not None, 'Requires native Qt video playback')
class HelperVideoTests(unittest.TestCase):
    def test_local_video_decodes_controls_pause_and_mode_switches_restore_drafts(self):
        if os.environ.get('DSH_VIDEO_INTEGRATION_CHILD') != '1':
            result = subprocess.run(
                [sys.executable, '-m', 'unittest',
                 'runtime.tests.test_helper_video.HelperVideoTests.test_local_video_decodes_controls_pause_and_mode_switches_restore_drafts'],
                env={**os.environ, 'DSH_VIDEO_INTEGRATION_CHILD': '1'}, capture_output=True, text=True, timeout=25,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        original_exec = QApplication.exec
        finished = threading.Event()
        errors, decoded = [], []

        class WaitingInput:
            def __iter__(self):
                finished.wait(20)
                return iter(())

        def scripted_exec(app):
            font = Path(os.environ.get('WINDIR', '')) / 'Fonts/msyh.ttc'
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
            window = next(w for w in app.topLevelWidgets() if hasattr(w, 'model'))
            mode = window.video_watcher

            def finish(error=None):
                if error is not None:
                    errors.append(error)
                mode.dispose()
                window.xiangqi_mode.dispose()
                finished.set()
                app.quit()

            def eventually(predicate, callback, start=None):
                start = time.monotonic() if start is None else start
                try:
                    if predicate():
                        callback()
                    elif time.monotonic() - start > 8:
                        raise AssertionError('Video did not reach expected state: ' + mode.player.errorString())
                    else:
                        QTimer.singleShot(30, lambda: eventually(predicate, callback, start))
                except BaseException as error:
                    finish(error)

            def scenario():
                try:
                    window._screen_geometry_at = lambda _x, _y: QRect(0, 0, 1920, 1040)
                    window._move_to_pet(850, 450)
                    window.task_input.setPlainText('视频模式保留的草稿')
                    attachment = Path(directory) / 'attachment.txt'
                    attachment.write_text('保留附件', encoding='utf-8')
                    window.task_files = [str(attachment)]
                    window._refresh_task_files()
                    window.novel_reader.apply(dict(id='video-test-book', enabled=True, hasBook=True,
                                                   title='测试阅读', content='仅供测试', page=0, totalPages=1))
                    window.video_button.click()
                    self.assertTrue(window.watching_video)
                    self.assertFalse(window._bubble_visible())
                    self.assertFalse(window.novel_reader.dialog.isVisible())
                    self.assertFalse(window.novel_reader.active())
                    self.assertFalse(window.task_input.isVisible())
                    self.assertFalse(window.video_button.isVisible())
                    self.assertFalse(window.chess_button.isVisible())
                    self.assertTrue(mode.dialog.isVisible())
                    self.assertTrue(QRect(0, 0, 1920, 1040).contains(mode.dialog.geometry()))
                    mode.video.videoSink().videoFrameChanged.connect(lambda frame: decoded.append(True) if frame.isValid() else None)
                    video = make_video(Path(directory) / 'pet-video.avi')
                    self.assertTrue(mode.load(str(video)))
                    eventually(lambda: decoded and mode.player.duration() > 0 and mode.playing, after_decode)
                except BaseException as error:
                    finish(error)

            def after_decode():
                self.assertEqual(mode.player.error(), QMediaPlayer.Error.NoError)
                self.assertFalse(mode.video.image.isNull(), 'the decoded frame must reach the displayed surface')
                self.assertNotEqual(mode.video.image.pixelColor(0, 0).name(), '#101820')
                self.assertGreater(mode.player.duration(), 7000)
                self.assertTrue(mode.seek.isEnabled())
                self.assertEqual((window.pet_x, window.pet_y), (850, 450))
                mode.volume.setValue(60)
                self.assertAlmostEqual(mode.audio.volume(), 0.6, places=3)
                mode.mute_button.click()
                self.assertTrue(mode.audio.isMuted())
                QTest.keyClick(mode.dialog, Qt.Key.Key_Space)
                eventually(lambda: not mode.playing, after_pause)

            def after_pause():
                self.assertEqual(mode.player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
                QTest.keyClick(mode.dialog, Qt.Key.Key_Right)
                self.assertGreaterEqual(mode.player.position(), 5000)
                QTest.keyClick(mode.dialog, Qt.Key.Key_Left)
                self.assertLess(mode.player.position(), 1000)
                mode.seek.setValue(2000)
                mode.seek.sliderReleased.emit()
                self.assertEqual(mode.player.position(), 2000)
                QTest.keyClick(mode.dialog, Qt.Key.Key_Space)
                eventually(lambda: mode.playing, after_resume)

            def after_resume():
                if os.environ.get('DSH_VIDEO_PREVIEW'):
                    mode.dialog.grab().save(os.environ['DSH_VIDEO_PREVIEW'])
                    window.grab().save(os.environ['DSH_VIDEO_PREVIEW'].replace('.png', '-pet.png'))
                mode.close_button.click()
                self.assertFalse(window.watching_video)
                self.assertFalse(mode.playing)
                self.assertTrue(window._bubble_visible())
                self.assertTrue(window.task_input.isVisible())
                self.assertEqual(window.task_input.toPlainText(), '视频模式保留的草稿')
                self.assertEqual(len(window.task_files), 1)
                self.assertTrue(window.novel_reader.dialog.isVisible())
                mode.enter()
                self.assertFalse(mode.playing, 'reopening must keep playback paused')
                self.assertEqual(mode.path.name, 'pet-video.avi')
                window.xiangqi_mode.enter()
                self.assertFalse(window.watching_video)
                self.assertTrue(window.chess_mode)
                mode.enter()
                self.assertFalse(window.chess_mode)
                self.assertTrue(window.watching_video)
                window.novel_reader.open_dialog()
                self.assertFalse(window.watching_video)
                self.assertFalse(mode.playing)
                self.assertTrue(window.novel_reader.dialog.isVisible())
                source = mode.player.source()
                self.assertFalse(mode.load(str(Path(directory) / 'missing.mp4')))
                self.assertEqual(mode.player.source(), source)
                bad = Path(directory) / 'bad.mp4'
                bad.write_bytes(b'not a video')
                self.assertTrue(mode.load(str(bad)))
                eventually(lambda: mode.player.error() != QMediaPlayer.Error.NoError, after_error)

            def after_error():
                self.assertIn('播放失败', mode.status.text())
                QTest.keyClick(mode.dialog, Qt.Key.Key_Escape)
                self.assertFalse(window.watching_video)
                self.assertTrue(window._bubble_visible())
                finish()

            QTimer.singleShot(0, scenario)
            return original_exec()

        with TemporaryDirectory() as directory, patch.dict(os.environ, {
            'QT_QPA_PLATFORM': 'offscreen', 'QT_MEDIA_BACKEND': 'ffmpeg',
            'QT_FFMPEG_DECODING_HW_DEVICE_TYPES': '',
            'DSH_DAFEIYU_LAYOUT_PATH': str(Path(directory) / 'layout.json'),
        }), patch.object(QApplication, 'exec', scripted_exec), patch.object(sys, 'stdin', WaitingInput()):
            self.assertEqual(run_visual(EventRecorder(None)), 0)
        if errors:
            raise errors[0]


if __name__ == '__main__':
    unittest.main()
