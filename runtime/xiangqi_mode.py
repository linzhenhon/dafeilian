"""Native chess mode: replace the task card with a board beside the pet."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

try:
    from .xiangqi import BLACK, RED, Game, Move, choose_move, in_check, legal_moves
except ImportError:
    from xiangqi import BLACK, RED, Game, Move, choose_move, in_check, legal_moves


class XiangqiMode:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.game = Game()
        self.dialog = None
        self.selected: int | None = None
        self.busy = False
        self.executor = None
        self.future = None
        self.cancel = Event()
        self.timer = None
        self.novel_was_visible = False
        self.task_was_visible = False

    def enter(self) -> None:
        from PySide6.QtCore import Qt

        if self.owner.chess_mode:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if self.owner.watching_video:
            self.owner.video_watcher.leave()
        if self.owner.voice_mode != "off":
            self.owner._stop_voice(finalize=False)
        novel = self.owner.novel_reader.dialog
        self.novel_was_visible = novel is not None and novel.isVisible()
        if self.novel_was_visible:
            novel.hide()
        task = self.owner.task_dialog
        self.task_was_visible = task is not None and task.isVisible()
        if self.task_was_visible:
            task.hide()
        self.owner.chess_mode = True
        self.owner._sync_bubble_size()
        if self.dialog is None:
            self._create_dialog()
        screen = self.owner._screen_geometry_at(self.owner.pet_x, self.owner.pet_y)
        if screen is not None:
            self.dialog.resize(min(430, screen.width() - 32), min(620, screen.height() - 54))
            width, height = self.dialog.width(), self.dialog.height()
            x = self.owner.pet_x - width - 14
            if x < screen.left():
                x = self.owner.pet_x + self.owner._pet_size()[0] + 14
            x = max(screen.left() + 8, min(x, screen.right() - width - 8))
            y = max(screen.top() + 24, min(self.owner.pet_y - 100, screen.bottom() - height - 28))
            self.dialog.move(x, y)
        self.refresh()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        self.board_widget.setFocus(Qt.FocusReason.OtherFocusReason)
        self.start_opponent()

    def leave(self, *_args) -> None:
        if not self.owner.chess_mode:
            return
        self.cancel_search()
        self.dialog.hide()
        self.owner.chess_mode = False
        self.owner._sync_bubble_size()
        if self.novel_was_visible and self.owner.novel_reader.state.get("enabled"):
            self.owner.novel_reader.dialog.show()
        if self.task_was_visible and self.owner.task_dialog is not None:
            self.owner.task_dialog.show()
        self.owner.update()

    def dispose(self) -> None:
        self.cancel_search()
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)
        if self.dialog is not None:
            self.dialog.hide()

    def cancel_search(self) -> None:
        self.cancel.set()
        if self.future is not None:
            self.future.cancel()
        self.future = None
        self.busy = False
        if self.timer is not None:
            self.timer.stop()

    def new_game(self) -> None:
        self.cancel_search()
        self.game, self.selected = Game(), None
        self.refresh()

    def undo(self) -> None:
        self.cancel_search()
        self.game.undo_round()
        self.selected = None
        self.refresh()
        self.start_opponent()

    def select(self, square: int) -> None:
        if self.busy or self.game.turn != RED or self.game.winner is not None:
            return
        if self.game.board[square] > 0:
            self.selected = None if self.selected == square else square
        elif self.selected is not None:
            if self.game.play(Move(self.selected, square)):
                self.selected = None
                self.refresh()
                self.start_opponent()
                return
            self.status.setText("这里不能走，试试绿色提示的位置。")
        self.board_widget.update()

    def start_opponent(self) -> None:
        if not self.owner.chess_mode or self.busy or self.game.turn != BLACK or self.game.winner is not None:
            return
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pet-xiangqi")
        self.cancel = Event()
        self.busy = True
        self.future = self.executor.submit(choose_move, self.game.board, BLACK, cancel=self.cancel)
        self.timer.start(40)
        self.refresh()

    def poll(self) -> None:
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        self.timer.stop()
        self.busy = False
        try:
            move = future.result()
            if move is not None:
                self.game.play(move)
            self.refresh()
        except Exception:
            self.status.setText("小肥蠊这步没想好，可以悔棋或重新开局。")
        self.owner.update()

    def refresh(self) -> None:
        if self.dialog is None:
            return
        if self.game.winner == RED:
            message = f"你赢啦！{self.game.reason}，再来一局？"
        elif self.game.winner == BLACK:
            message = f"小肥蠊赢了 · {self.game.reason}，可以悔棋再试试。"
        elif self.game.winner == 0:
            message = self.game.reason
        elif self.busy:
            message = "小肥蠊正在思考…"
        elif in_check(self.game.board, RED) and self.game.turn == RED:
            message = "将军！请先保护你的帅。"
        else:
            message = "轮到你啦 · 点击红棋，再点绿色位置落子。"
        self.status.setText(message)
        self.undo_button.setEnabled(bool(self.game.history))
        self.round_label.setText(f"你执红先行  ·  小肥蠊执黑  ·  第 {len(self.game.history) // 2 + 1} 回合")
        self.board_widget.update()
        self.owner.update()

    def _create_dialog(self) -> None:
        from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
        from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
        from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

        controller = self

        class Board(QWidget):
            def __init__(self, parent):
                super().__init__(parent)
                self.setMinimumSize(286, 320)
                self.setSizePolicy(self.sizePolicy().Policy.Expanding, self.sizePolicy().Policy.Expanding)
                self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                self.setAccessibleName("中国象棋棋盘，点击红棋后选择绿色落点")
                self.setCursor(Qt.CursorShape.PointingHandCursor)

            def sizeHint(self):
                return QSize(396, 440)

            def grid(self):
                step = min((self.width() - 48) / 8, (self.height() - 48) / 9)
                return (self.width() - 8 * step) / 2, (self.height() - 9 * step) / 2, step

            def square_center(self, square):
                x, y, step = self.grid()
                return QPointF(x + (square % 9) * step, y + (square // 9) * step)

            def mousePressEvent(self, event):
                if event.button() != Qt.MouseButton.LeftButton:
                    return
                x, y, step = self.grid()
                column = round((event.position().x() - x) / step)
                row = round((event.position().y() - y) / step)
                if 0 <= column < 9 and 0 <= row < 10:
                    center = self.square_center(row * 9 + column)
                    if (center - event.position()).manhattanLength() <= step * 0.65:
                        controller.select(row * 9 + column)

            def paintEvent(self, _event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                background = QLinearGradient(0, 0, self.width(), self.height())
                background.setColorAt(0, QColor("#F5E7CB"))
                background.setColorAt(1, QColor("#E9D1A9"))
                painter.setPen(QPen(QColor("#C8AE83"), 1))
                painter.setBrush(background)
                painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 12, 12)
                x, y, step = self.grid()
                painter.setPen(QPen(QColor("#92734E"), 1))
                for row in range(10):
                    painter.drawLine(QPointF(x, y + row * step), QPointF(x + 8 * step, y + row * step))
                for column in range(9):
                    xx = x + column * step
                    if column in (0, 8):
                        painter.drawLine(QPointF(xx, y), QPointF(xx, y + 9 * step))
                    else:
                        painter.drawLine(QPointF(xx, y), QPointF(xx, y + 4 * step))
                        painter.drawLine(QPointF(xx, y + 5 * step), QPointF(xx, y + 9 * step))
                for start in (0, 7):
                    painter.drawLine(self.square_center(start * 9 + 3), self.square_center((start + 2) * 9 + 5))
                    painter.drawLine(self.square_center(start * 9 + 5), self.square_center((start + 2) * 9 + 3))
                font = QFont("Microsoft YaHei UI")
                font.setPixelSize(max(13, round(step * 0.44)))
                painter.setFont(font)
                painter.setPen(QColor("#94714B"))
                for column, text in ((0.7, "楚 河"), (5.1, "汉 界")):
                    painter.drawText(QRectF(x + column * step, y + 4 * step, 2.2 * step, step), Qt.AlignmentFlag.AlignCenter, text)
                last = controller.game.last_move
                if last is not None:
                    painter.setPen(QPen(QColor("#729C85"), 2, Qt.PenStyle.DashLine))
                    painter.drawLine(self.square_center(last.source), self.square_center(last.target))
                labels = {1: ("帅", "将"), 2: ("仕", "士"), 3: ("相", "象"), 4: ("马", "马"),
                          5: ("车", "车"), 6: ("炮", "炮"), 7: ("兵", "卒")}
                for square, piece in enumerate(controller.game.board):
                    if not piece:
                        continue
                    center, radius = self.square_center(square), step * 0.40
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(80, 50, 20, 32))
                    painter.drawEllipse(center + QPointF(0, 2), radius + 1, radius + 1)
                    painter.setBrush(QColor("#FFF7E6"))
                    color = "#AF3D32" if piece > 0 else "#344741"
                    painter.setPen(QPen(QColor(color), 1.6))
                    painter.drawEllipse(center, radius, radius)
                    painter.setPen(QPen(QColor("#DBC49C"), 0.8))
                    painter.drawEllipse(center, radius - 3, radius - 3)
                    painter.setPen(QColor(color))
                    font.setPixelSize(max(13, round(step * 0.52)))
                    font.setWeight(QFont.Weight.DemiBold)
                    painter.setFont(font)
                    painter.drawText(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
                                     Qt.AlignmentFlag.AlignCenter, labels[abs(piece)][0 if piece > 0 else 1])
                    if square == controller.selected or last is not None and square == last.target:
                        painter.setPen(QPen(QColor("#2E806B"), 2.5))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawEllipse(center, radius + 3, radius + 3)
                if controller.selected is not None and not controller.busy:
                    painter.setPen(QPen(QColor("#2E806B"), 2))
                    for move in legal_moves(controller.game.board, RED):
                        if move.source == controller.selected:
                            center = self.square_center(move.target)
                            capture = bool(controller.game.board[move.target])
                            painter.setBrush(Qt.BrushStyle.NoBrush if capture else QColor("#2E806B"))
                            radius = step * 0.44 if capture else step * 0.085
                            painter.drawEllipse(center, radius, radius)
                painter.end()

        self.dialog = QDialog(self.owner, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.dialog.setWindowTitle("小肥蠊 · 下象棋")
        self.dialog.setMinimumSize(330, 470)
        self.dialog.setFont(QFont("Microsoft YaHei UI", 10))
        self.dialog.setStyleSheet(
            "QDialog { background: #FAF7F0; } QLabel { color: #344741; }"
            "QPushButton { background: #FFFDF7; color: #344741; border: 1px solid #D9CDB7;"
            " border-radius: 7px; padding: 8px 12px; } QPushButton:hover { background: #EEE6D7; }"
            "QPushButton:disabled { color: #AAA294; }"
        )
        layout = QVBoxLayout(self.dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        heading = QLabel("与小肥蠊下象棋")
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(heading)
        self.round_label = QLabel()
        self.round_label.setStyleSheet("color: #8C7C64; font-size: 12px;")
        layout.addWidget(self.round_label)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(30)
        self.status.setStyleSheet("color: #2E806B; font-size: 12px;")
        layout.addWidget(self.status)
        self.board_widget = Board(self.dialog)
        layout.addWidget(self.board_widget, 1)
        controls = QHBoxLayout()
        self.new_button = QPushButton("重新开局")
        self.new_button.clicked.connect(self.new_game)
        self.undo_button = QPushButton("悔棋")
        self.undo_button.clicked.connect(self.undo)
        self.close_button = QPushButton("收起棋盘")
        self.close_button.clicked.connect(self.leave)
        for button in (self.new_button, self.undo_button, self.close_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.dialog.finished.connect(self.leave)
        self.timer = QTimer(self.owner)
        self.timer.timeout.connect(self.poll)
        QApplication.instance().aboutToQuit.connect(self.dispose)

    def draw_prop(self, painter, rect) -> None:
        if not self.owner.chess_mode or self.owner.dragging or self.owner.file_drop_hover:
            return
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QColor, QPen

        x, y, width, height = rect
        painter.save()
        painter.translate(x + width * 0.51, y + height * 0.70)
        painter.scale(width / 412, width / 412)
        painter.setBrush(QColor("#E9D1A9"))
        painter.setPen(QPen(QColor("#94714B"), 2))
        painter.drawRoundedRect(QRectF(-62, -18, 124, 48), 5, 5)
        painter.setPen(QPen(QColor("#B39363"), 0.8))
        for column in range(7):
            painter.drawLine(QPointF(-48 + column * 16, -12), QPointF(-48 + column * 16, 24))
        for row in range(4):
            painter.drawLine(QPointF(-48, -12 + row * 12), QPointF(48, -12 + row * 12))
        for cx, cy, color in ((-32, 12, "#AF3D32"), (16, 0, "#344741"), (32, 12, "#344741")):
            painter.setBrush(QColor("#FFF7E6"))
            painter.setPen(QPen(QColor(color), 2))
            painter.drawEllipse(QPointF(cx, cy), 7, 7)
        painter.restore()
