import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QFontDatabase, QPainter, QPixmap, QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu, QTextEdit, QWidget
except ImportError:
    QApplication = None

from runtime.novel_reader import NovelReader


@unittest.skipUnless(QApplication is not None, "Requires Qt")
class NovelReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Offscreen Qt does not discover the Windows font collection itself.
        font = os.path.join(os.environ.get('WINDIR', ''), 'Fonts', 'msyh.ttc')
        if os.path.isfile(font):
            QFontDatabase.addApplicationFont(font)

    def setUp(self):
        self.owner = QWidget()
        self.owner.model = SimpleNamespace(base_state="IDLE", pulse_state=None, overlay_clip_name=None)
        self.owner.voice_mode = "off"
        self.owner.voice_pending = {}
        self.owner.dragging = False
        self.owner.file_drop_hover = False
        self.owner._show_overlay = Mock()
        self.send = Mock()
        self.reader = NovelReader(self.owner, self.send)
        self.state = dict(id="book", hasBook=True, enabled=True, autoTurn=True, secondsPerPage=20,
                          title="我的小说", page=0, totalPages=3, content="第一章\n用户导入的故事。")
        self.reader.apply(self.state)

    def tearDown(self):
        self.reader.timer.stop()
        if self.reader.dialog:
            self.reader.dialog.close()
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()

    def test_reading_yields_to_work_voice_drag_and_reactions(self):
        self.assertTrue(self.reader.active())
        self.assertEqual(self.reader.text.toPlainText(), self.state["content"])
        for field, value in (("base_state", "WORKING"), ("pulse_state", "SUCCESS"), ("overlay_clip_name", "head_pat")):
            previous = getattr(self.owner.model, field)
            setattr(self.owner.model, field, value)
            self.assertFalse(self.reader.active())
            setattr(self.owner.model, field, previous)
        self.owner.dragging = True
        self.assertFalse(self.reader.active())
        self.owner.dragging = False
        self.owner.voice_mode = "call"
        self.assertFalse(self.reader.active())
        self.owner.voice_mode = "off"
        self.assertTrue(self.reader.active())
        self.reader.apply({**self.state, "enabled": False})
        self.assertFalse(self.reader.active())
        self.assertFalse(self.reader.dialog.isVisible())

    def test_auto_turn_waits_for_ack_and_pauses_during_work(self):
        self.reader.next_page_at = 0
        self.reader.tick()
        self.send.assert_called_once_with("novel_action", patch={"id": "book", "page": 1})
        self.reader.tick()
        self.assertEqual(self.send.call_count, 1)
        self.reader.apply({**self.state, "page": 1, "content": "第二页"})
        self.owner.model.base_state = "WORKING"
        self.reader.tick()
        self.assertIsNone(self.reader.next_page_at)
        self.owner.model.base_state = "IDLE"
        self.reader.tick()
        self.assertIsNotNone(self.reader.next_page_at)
        self.assertEqual(self.send.call_count, 1)

    def test_menu_import_and_render(self):
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName', return_value=("C:/books/自己的小说.txt", "")):
            self.reader.choose_file()
        self.send.assert_called_once_with("novel_action", importPath="C:/books/自己的小说.txt")
        menu = QMenu(self.owner)
        self.reader.add_menu(menu)
        self.assertEqual(menu.actions()[0].text(), "摸鱼模式（看小说）")
        pixmap = QPixmap(412, 344)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.reader.draw_book(painter, (0, 0, 412, 344), False)
        painter.end()
        self.assertFalse(pixmap.toImage().pixelColor(205, 240).alpha() == 0)
        if os.environ.get('DSH_NOVEL_PREVIEW'):
            self.reader.dialog.grab().save(os.environ['DSH_NOVEL_PREVIEW'])

    def acknowledge(self, page):
        self.reader.apply({**self.state, "page": page, "content": f"第 {page + 1} 页"})

    def wheel(self, angle=0, pixels=0, horizontal=0):
        event = QWheelEvent(QPointF(30, 30), QPointF(30, 30), QPoint(0, pixels), QPoint(horizontal, angle),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(self.reader.text.viewport(), event)

    def test_arrow_and_page_keys_work_with_reader_children_and_respect_boundaries(self):
        QTest.keyClick(self.reader.text, Qt.Key.Key_Up)
        self.send.assert_not_called()
        QTest.keyClick(self.reader.text, Qt.Key.Key_Down)
        self.send.assert_called_once_with("novel_action", patch={"id": "book", "page": 1})
        self.acknowledge(1)
        QTest.keyClick(self.reader.next, Qt.Key.Key_PageDown)
        self.assertEqual(self.send.call_args.kwargs["patch"]["page"], 2)
        self.acknowledge(2)
        self.send.reset_mock()
        QTest.keyClick(self.reader.text, Qt.Key.Key_Down)
        self.send.assert_not_called()
        QTest.keyClick(self.reader.auto, Qt.Key.Key_PageUp)
        self.send.assert_called_once_with("novel_action", patch={"id": "book", "page": 1})
        self.acknowledge(1)
        QTest.keyClick(self.reader.text, Qt.Key.Key_Up)
        self.assertEqual(self.send.call_args.kwargs["patch"]["page"], 0)

    def test_wheel_turns_pages_and_accumulates_smooth_scroll(self):
        self.wheel(angle=-120)
        self.send.assert_called_once_with("novel_action", patch={"id": "book", "page": 1})
        self.acknowledge(1)
        self.wheel(angle=120)
        self.assertEqual(self.send.call_args.kwargs["patch"]["page"], 0)
        self.acknowledge(0)
        self.send.reset_mock()
        self.wheel(angle=-40)
        self.wheel(angle=-40)
        self.send.assert_not_called()
        self.wheel(angle=-40)
        self.send.assert_called_once_with("novel_action", patch={"id": "book", "page": 1})
        self.acknowledge(1)
        self.send.reset_mock()
        self.wheel(pixels=-30)
        self.send.assert_not_called()
        self.wheel(pixels=-30)
        self.send.assert_called_once_with("novel_action", patch={"id": "book", "page": 2})
        self.acknowledge(2)
        self.send.reset_mock()
        self.wheel(angle=-120)
        self.wheel(horizontal=120)
        self.send.assert_not_called()

    def test_rapid_navigation_keeps_latest_target_and_discards_it_for_another_book(self):
        self.reader.turn(1)
        self.reader.turn(1)
        self.send.assert_called_once_with("novel_action", patch={"id": "book", "page": 1})
        self.acknowledge(1)
        self.assertEqual(self.send.call_args.kwargs["patch"]["page"], 2)
        self.assertEqual(self.send.call_count, 2)
        self.acknowledge(2)
        self.reader.turn(-1)
        self.reader.turn(-1)
        self.reader.turn(1)
        self.acknowledge(1)
        self.assertEqual(self.send.call_count, 3, "reversing before the reply should cancel the queued turn")
        self.reader.turn(1)
        self.reader.turn(-1)
        self.send.reset_mock()
        self.reader.apply({**self.state, "id": "another-book"})
        self.assertIsNone(self.reader.queued_page)
        self.assertFalse(self.reader.pending)
        self.send.assert_not_called()

    def test_manual_reading_during_work_and_keys_in_other_windows(self):
        self.owner.model.base_state = "WORKING"
        QTest.keyClick(self.reader.text, Qt.Key.Key_Down)
        self.send.assert_called_once_with("novel_action", patch={"id": "book", "page": 1})
        self.acknowledge(1)
        self.send.reset_mock()
        QTest.keyClick(self.reader.text, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        outside = QTextEdit(self.owner)
        QTest.keyClick(outside, Qt.Key.Key_Down)
        self.send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
