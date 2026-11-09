"""Exercise the real Qt window when PySide6 is installed for Helper builds."""

import os
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

try:
    from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, Qt, QTimer, QUrl
    from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDragLeaveEvent, QDropEvent
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from runtime.helper import DSH_GO_DOWNLOAD_URL, EventRecorder, run_visual


@unittest.skipUnless(QApplication is not None, 'Qt integration runs with the Helper build dependencies')
class HelperGeometryTests(unittest.TestCase):
    def test_cards_alerts_and_drag_keep_the_rendered_and_saved_anchor_equal(self) -> None:
        original_exec = QApplication.exec
        finished = threading.Event()
        errors = []

        class WaitingInput:
            def __iter__(self):
                finished.wait(30)
                return iter(())

        def scripted_exec(app):
            window = next(w for w in app.topLevelWidgets() if hasattr(w, 'model'))

            def scenario():
                try:
                    window.micro_timer.stop()
                    window._screen_geometry_at = lambda x, y: QRect(0, 0, 1920, 1040)

                    def message(kind, **fields):
                        window.apply_message({'protocolVersion': 1, 'kind': kind, 'timestamp': 0, **fields})

                    def assert_anchor(expected):
                        self.assertEqual((window.pet_x, window.pet_y), expected)
                        x, y, _, _ = window._pet_rect()
                        self.assertEqual((window.x() + x, window.y() + y), expected)

                    self.assertEqual(window.sound_states, {'SUCCESS', 'ERROR'})
                    self.assertEqual(window.sound_pack, 'original')
                    window._open_task_dialog()
                    window.task_editor.setPlainText('帮我检查任务输入')
                    with patch('runtime.helper.emit_reply') as reply:
                        window.task_send_button.click()
                        request_id = window.pending_task_id
                        reply.assert_called_once_with('submit_task', requestId=request_id, text='帮我检查任务输入', files=[])
                    message('task_result', requestId=request_id, accepted=False, error='目标对话未连接')
                    self.assertEqual(window.task_editor.toPlainText(), '帮我检查任务输入')
                    self.assertTrue(window.task_send_button.isEnabled())
                    with patch('runtime.helper.emit_reply') as reply:
                        window.task_send_button.click()
                        request_id = window.pending_task_id
                        reply.assert_called_once_with('submit_task', requestId=request_id, text='帮我检查任务输入', files=[])
                    message('task_result', requestId=request_id, accepted=True)
                    self.assertIsNone(window.task_dialog)
                    self.assertEqual(window.overlay_message, '任务已发送')
                    alerts = []
                    with patch.object(window, '_notify_alert', side_effect=alerts.append):
                        message('alert', alert='APPROVAL', sessionId='s', toolName='bash')
                        message('alert', alert='SOMETHING_NEW')
                    self.assertEqual(alerts, ['APPROVAL'])
                    message('config', soundStates=['ERROR', 42])
                    self.assertEqual(window.sound_states, {'ERROR'})
                    message('config', soundPack='clean')
                    self.assertEqual(window.sound_pack, 'clean')
                    message('config', soundPack='video')
                    self.assertEqual(window.sound_pack, 'video')
                    message('config', soundPack='../other')
                    self.assertEqual(window.sound_pack, 'video')
                    if sys.platform == 'win32':
                        import winsound

                        with patch.object(winsound, 'PlaySound') as play:
                            window._notify_alert('ERROR')
                            self.assertIn('sounds\\video\\error.wav', play.call_args.args[0].replace('/', '\\'))
                        with TemporaryDirectory() as custom_dir:
                            window.custom_sounds_dir = Path(custom_dir)
                            (window.custom_sounds_dir / 'error.wav').write_bytes(b'RIFF')
                            message('config', soundPack='custom')
                            with patch.object(winsound, 'PlaySound') as play:
                                window._notify_alert('ERROR')
                                self.assertEqual(play.call_args.args[0], str(window.custom_sounds_dir / 'error.wav'))
                            (window.custom_sounds_dir / 'error.wav').unlink()
                            with patch.object(winsound, 'PlaySound') as play:
                                window._notify_alert('ERROR')
                                self.assertIn('sounds\\error.wav', play.call_args.args[0].replace('/', '\\'))
                    message('config', soundEnabled=False, bubbleMode='hidden', scale=1.0, bubbleScale=1.0)
                    for expected in ((200, 30), (1508, 696)):
                        window._move_to_pet(*expected)
                        for mode in ('always', 'custom', 'hidden'):
                            message('config', bubbleMode=mode)
                            message('balance', summary='余额测试')
                            message('tasks', tasks=[{'state': 'WORKING'}] * 3)
                            assert_anchor(expected)
                            message('pulse', state='SUCCESS', ttlMs=2200, resumeState='IDLE')
                            window._begin_drag()
                            window._move_to_pet(*expected)
                            message('tasks', tasks=[])
                            message('balance', summary='')
                            window._finish_drag()
                            for _ in range(10):
                                window._tick()
                            assert_anchor(expected)
                        window.grab()  # Painting must use the same rectangle as hit testing.
                    with patch.object(QDesktopServices, 'openUrl', return_value=False), patch('sys.stderr'):
                        window._open_client()
                    self.assertEqual(window.overlay_message, '无法打开 DSH')
                    with patch.object(QDesktopServices, 'openUrl', return_value=True) as open_url:
                        window._open_dsh_go_download()
                    open_url.assert_called_once()
                    self.assertEqual(open_url.call_args.args[0].toString(), DSH_GO_DOWNLOAD_URL)
                    window._move_to_pet(500, 500)
                    message('config', bubbleMode='always')
                    message('pulse', state='SUCCESS', ttlMs=2200, resumeState='IDLE')
                    message('config', bubbleMode='hidden')

                    window.voice_mode = 'call'
                    window.voice_started_ms = window._now_ms()
                    window._sync_bubble_size()
                    self.assertFalse(window.call_transcript.isHidden())
                    self.assertGreater(window.call_transcript.height(), 80)
                    composer_x, composer_y, composer_width, composer_height = window._composer_rect()
                    self.assertLess(window.call_transcript.geometry().bottom(), composer_y)
                    self.assertGreaterEqual(window.task_input.x(), composer_x)
                    self.assertLessEqual(window.task_inline_send.geometry().right(), composer_x + composer_width)
                    self.assertLess(window.task_input.geometry().bottom(), window.task_inline_send.y())
                    window.voice_pending['call-text'] = 'call'
                    with patch.object(window, '_dispatch_voice_tasks'):
                        message('voice_transcript', requestId='call-text', text='帮我看看今天的任务')
                    message('call_message', text='今天还有两项任务，请先完成最重要的一项。')
                    with patch.object(window, '_speak_reply') as speak:
                        message('speak', text='今天还有两项任务。')
                        speak.assert_called_once_with('今天还有两项任务。')
                    visible_text = window.call_transcript.toPlainText()
                    self.assertIn('我：帮我看看今天的任务', visible_text)
                    self.assertIn('大哥：今天还有两项任务', visible_text)
                    window.voice_tasks.clear()
                    window.voice_mode = 'off'
                    window._sync_bubble_size()
                    self.assertTrue(window.call_transcript.isHidden())
                    message('config', bubbleMode='always')
                    for bubble_scale in (0.8, 1.0, 1.2):
                        message('config', bubbleScale=bubble_scale)
                        composer_x, composer_y, composer_width, composer_height = window._composer_rect()
                        self.assertLess(window.task_input.geometry().bottom(), window.task_inline_send.y())
                        self.assertLessEqual(window.task_inline_send.geometry().right(), composer_x + composer_width)
                    message('config', bubbleScale=0.8)
                    long_speech = '请帮我整理今天的任务和明天的安排，' * 22
                    self.assertTrue(window._append_voice_text(long_speech))
                    self.assertEqual(window.task_input.toPlainText(), long_speech)
                    self.assertGreater(window.task_input.height(), round(40 * window.bubble_scale))
                    self.assertTrue(window._append_voice_text('再补充一件事'))
                    self.assertEqual(window.task_input.toPlainText(), long_speech + '\n再补充一件事')
                    window.task_input.clear()
                    dropped_file = Path(directory) / '待处理.txt'
                    dropped_file.write_text('文件内容', encoding='utf-8')
                    mime = QMimeData()
                    mime.setUrls([QUrl.fromLocalFile(str(dropped_file))])
                    enter = QDragEnterEvent(QPoint(40, 40), Qt.DropAction.CopyAction, mime,
                                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                    window.dragEnterEvent(enter)
                    self.assertTrue(enter.isAccepted())
                    self.assertEqual(window.model.active_clip_name, 'file_hover')
                    window.dragLeaveEvent(QDragLeaveEvent())
                    self.assertNotEqual(window.model.active_clip_name, 'file_hover')
                    window.dragEnterEvent(enter)
                    with patch('runtime.helper.emit_reply') as reply:
                        drop = QDropEvent(QPointF(40, 40), Qt.DropAction.CopyAction, mime,
                                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                        window.dropEvent(drop)
                        reply.assert_not_called()
                    self.assertTrue(drop.isAccepted())
                    self.assertEqual([Path(path) for path in window.task_files], [dropped_file])
                    self.assertEqual(window.task_file_button.text(), '1')
                    self.assertEqual(window.task_file_list.item(0).text(), '待处理.txt')
                    self.assertFalse(window.task_file_list.isHidden())
                    self.assertGreater(window.task_file_list.height(), 0)
                    composer_x, composer_y, composer_width, composer_height = window._composer_rect()
                    self.assertGreaterEqual(window.task_file_list.y(), composer_y)
                    self.assertLess(window.task_file_list.geometry().bottom(), window.task_input.y())
                    self.assertLessEqual(window.task_inline_send.geometry().right(), composer_x + composer_width)
                    self.assertEqual(window.voice_record_button.text(), '')
                    self.assertEqual(window.voice_call_button.text(), '')
                    self.assertEqual(window.task_inline_send.text(), '')
                    self.assertFalse(window.voice_record_button.icon().isNull())
                    self.assertFalse(window.voice_call_button.icon().isNull())
                    self.assertFalse(window.task_inline_send.icon().isNull())
                    self.assertEqual(window.model.active_clip_name, 'file_catch')
                    self.assertFalse(window.task_input.acceptDrops())
                    window._clear_task_files()
                    window.model.clear_overlay()
                    window._clear_overlay()
                    window._open_task_dialog()
                    self.assertFalse(window.task_editor.acceptDrops())
                    dialog_enter = QDragEnterEvent(QPoint(40, 40), Qt.DropAction.CopyAction, mime,
                                                  Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                    window.task_dialog.dragEnterEvent(dialog_enter)
                    self.assertTrue(dialog_enter.isAccepted())
                    dialog_drop = QDropEvent(QPointF(40, 40), Qt.DropAction.CopyAction, mime,
                                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                    window.task_dialog.dropEvent(dialog_drop)
                    self.assertEqual([Path(path) for path in window.task_files], [dropped_file])
                    self.assertEqual(window.task_dialog_file_button.text(), '添加文件 (1)')
                    self.assertEqual(window.task_dialog_file_list.item(0).text(), '待处理.txt')
                    self.assertFalse(window.task_dialog_file_list.isHidden())
                    window._remove_task_file(str(dropped_file))
                    self.assertTrue(window.task_dialog_file_list.isHidden())
                    self.assertTrue(window.task_file_list.isHidden())
                    window.task_dialog.reject()
                    window.model.clear_overlay()
                    window._clear_overlay()

                    def after_notification():
                        try:
                            assert_anchor((500, 500))
                        except BaseException as error:
                            errors.append(error)
                        finally:
                            finished.set()
                            app.quit()

                    # Wait beyond the old shake duration to catch stale-origin
                    # restoration after a card resize, rather than just its first tick.
                    QTimer.singleShot(350, after_notification)
                except BaseException as error:
                    errors.append(error)
                    finished.set()
                    app.quit()

            QTimer.singleShot(0, scenario)
            return original_exec()

        with TemporaryDirectory() as directory, patch.dict(os.environ, {
            'QT_QPA_PLATFORM': 'offscreen', 'DSH_DAFEIYU_LAYOUT_PATH': str(Path(directory) / 'layout.json'),
        }), patch.object(QApplication, 'exec', scripted_exec), patch.object(sys, 'stdin', WaitingInput()):
            self.assertEqual(run_visual(EventRecorder(None)), 0)
        if errors:
            raise errors[0]


if __name__ == '__main__':
    unittest.main()
