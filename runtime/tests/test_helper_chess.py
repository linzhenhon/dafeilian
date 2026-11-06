import os
import sys
import subprocess
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

try:
    from PySide6.QtCore import QRect, Qt, QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from runtime.helper import EventRecorder, run_visual
from runtime.xiangqi import BLACK, RED, initial_board, legal_moves


@unittest.skipUnless(QApplication is not None, 'Requires native Qt')
class HelperChessTests(unittest.TestCase):
    def test_chess_replaces_card_plays_locally_and_restores_draft(self):
        # Each full Helper owns a QApplication; isolate it from the other UI tests.
        if os.environ.get('DSH_CHESS_INTEGRATION_CHILD') != '1':
            result = subprocess.run(
                [sys.executable, '-m', 'unittest',
                 'runtime.tests.test_helper_chess.HelperChessTests.test_chess_replaces_card_plays_locally_and_restores_draft'],
                env={**os.environ, 'DSH_CHESS_INTEGRATION_CHILD': '1'},
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        original_exec = QApplication.exec
        finished = threading.Event()
        errors = []

        class WaitingInput:
            def __iter__(self):
                finished.wait(15)
                return iter(())

        def scripted_exec(app):
            font = Path(os.environ.get('WINDIR', '')) / 'Fonts/msyh.ttc'
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
            window = next(w for w in app.topLevelWidgets() if hasattr(w, 'model'))
            mode = window.xiangqi_mode

            def finish(error=None):
                if error is not None:
                    errors.append(error)
                mode.dispose()
                finished.set()
                app.quit()

            def scenario():
                try:
                    window.micro_timer.stop()
                    window._screen_geometry_at = lambda _x, _y: QRect(0, 0, 1920, 1040)
                    window._move_to_pet(600, 500)
                    window.task_input.setPlainText('还没有发送的任务')
                    attachment = Path(directory) / '保留附件.txt'
                    attachment.write_text('未发送的附件', encoding='utf-8')
                    window.task_files = [str(attachment)]
                    window._refresh_task_files()
                    window.novel_reader.apply(dict(id='test-book', enabled=True, hasBook=True,
                                                   title='阅读测试', content='本地测试文本', page=0, totalPages=1))
                    window.apply_message({'kind': 'market', 'enabled': True, 'status': 'connecting'})
                    self.assertTrue(window._bubble_visible())
                    self.assertTrue(window.chess_button.isVisible())
                    if os.environ.get('DSH_CHESS_PREVIEW'):
                        window.grab().save(os.environ['DSH_CHESS_PREVIEW'].replace('.png', '-card.png'))
                    window.chess_button.click()
                    self.assertTrue(window.chess_mode)
                    self.assertFalse(window._bubble_visible())
                    self.assertTrue(mode.dialog.isVisible())
                    self.assertFalse(window.novel_reader.dialog.isVisible())
                    self.assertFalse(window.novel_reader.active())
                    for control in (window.task_input, window.task_inline_send, window.task_file_button,
                                    window.voice_record_button, window.voice_call_button, window.chess_button):
                        self.assertFalse(control.isVisible())
                    self.assertEqual((window.pet_x, window.pet_y), (600, 500))
                    self.assertEqual(window.task_input.toPlainText(), '还没有发送的任务')
                    self.assertEqual(window.task_files, [str(attachment)])
                    self.assertTrue(QRect(0, 0, 1920, 1040).contains(mode.dialog.geometry()))
                    if os.environ.get('DSH_CHESS_PREVIEW'):
                        mode.dialog.grab().save(os.environ['DSH_CHESS_PREVIEW'])
                        window.grab().save(os.environ['DSH_CHESS_PREVIEW'].replace('.png', '-pet.png'))
                    for square in (54, 45):
                        QTest.mouseClick(mode.board_widget, Qt.MouseButton.LeftButton,
                                         pos=mode.board_widget.square_center(square).toPoint())
                    self.assertTrue(mode.busy)
                    self.assertEqual(mode.game.turn, BLACK)
                    self.assertEqual(len(mode.game.history), 1)
                    self.event_loop_alive = False
                    QTimer.singleShot(0, lambda: setattr(self, 'event_loop_alive', True))
                    QTimer.singleShot(50, after_opponent)
                except BaseException as error:
                    finish(error)

            checks = 0

            def after_opponent():
                nonlocal checks
                checks += 1
                if mode.busy and checks < 100:
                    QTimer.singleShot(50, after_opponent)
                    return
                try:
                    self.assertTrue(self.event_loop_alive, 'AI must not block the UI thread')
                    self.assertFalse(mode.busy)
                    self.assertEqual(mode.game.turn, RED)
                    self.assertEqual(len(mode.game.history), 2)
                    self.assertIn(mode.game.last_move, legal_moves(mode.game.history[-1][0], BLACK))
                    saved = mode.game.board
                    mode.close_button.click()
                    self.assertFalse(window.chess_mode)
                    self.assertTrue(window._bubble_visible())
                    self.assertTrue(window.task_input.isVisible())
                    self.assertTrue(window.task_file_list.isVisible())
                    self.assertTrue(window.novel_reader.dialog.isVisible())
                    self.assertEqual(window.task_input.toPlainText(), '还没有发送的任务')
                    self.assertEqual((window.pet_x, window.pet_y), (600, 500))
                    mode.enter()
                    self.assertEqual(mode.game.board, saved)
                    mode.undo_button.click()
                    self.assertEqual(mode.game.board, initial_board())
                    mode.select(54)
                    mode.select(45)
                    self.assertTrue(mode.busy)
                    mode.leave()
                    self.assertFalse(mode.busy)
                    self.assertFalse(mode.timer.isActive())
                    mode.new_game()
                    QTimer.singleShot(100, after_cancelled)
                except BaseException as error:
                    finish(error)

            def after_cancelled():
                try:
                    self.assertEqual(mode.game.board, initial_board(), 'old searches must not alter a new game')
                    window._screen_geometry_at = lambda _x, _y: QRect(0, 0, 800, 600)
                    window._move_to_pet(350, 250)
                    mode.enter()
                    self.assertTrue(QRect(0, 0, 800, 600).contains(mode.dialog.geometry()))
                    QTest.keyClick(mode.dialog, Qt.Key.Key_Escape)
                    self.assertFalse(window.chess_mode)
                    self.assertTrue(window._bubble_visible())
                    finish()
                except BaseException as error:
                    finish(error)

            QTimer.singleShot(0, scenario)
            QTimer.singleShot(12000, lambda: finish(AssertionError('chess integration timeout')))
            return original_exec()

        with TemporaryDirectory() as directory, patch.dict(os.environ, {
            'QT_QPA_PLATFORM': 'offscreen', 'DSH_DAFEIYU_LAYOUT_PATH': str(Path(directory) / 'layout.json'),
        }), patch.object(QApplication, 'exec', scripted_exec), patch.object(sys, 'stdin', WaitingInput()):
            self.assertEqual(run_visual(EventRecorder(None)), 0)
        if errors:
            raise errors[0]


if __name__ == '__main__':
    unittest.main()
