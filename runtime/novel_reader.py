"""Local novel controls and a drawn reading prop for the native companion."""
from __future__ import annotations

import math
import time
from typing import Any


class NovelReader:
    def __init__(self, owner: Any, send: Any) -> None:
        from PySide6.QtCore import QTimer

        self.owner = owner
        self.send = send
        self.state: dict[str, Any] = {}
        self.dialog = None
        self.next_page_at: float | None = None
        self.pending = False
        self.requested_page: int | None = None
        self.queued_page: int | None = None
        self.wheel_delta = 0.0
        self.wheel_source: str | None = None
        self.wheel_at = 0.0
        self.turn_started = 0.0
        self.timer = QTimer(owner)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def active(self) -> bool:
        return bool(
            self.state.get("enabled") and self.state.get("hasBook")
            and self.owner.model.base_state == "IDLE"
            and self.owner.model.pulse_state is None
            and self.owner.model.overlay_clip_name is None
            and self.owner.voice_mode == "off" and not self.owner.voice_pending
            and not self.owner.dragging and not self.owner.file_drop_hover
        )

    def apply(self, state: dict[str, Any]) -> None:
        previous = self.state
        same_book = previous.get("id") == state.get("id")
        acknowledged = self.requested_page == state.get("page")
        queued_page = self.queued_page if same_book and acknowledged and not state.get("error") else None
        self.state = state
        if not same_book or acknowledged or state.get("error"):
            self.pending = False
            self.requested_page = None
            self.queued_page = None
        if not same_book:
            self.wheel_delta = 0.0
        self.next_page_at = None
        if previous.get("page") != state.get("page") or previous.get("id") != state.get("id"):
            self.turn_started = time.monotonic()
        if state.get("error"):
            self.owner._show_overlay("小说读取失败", str(state["error"]), "ERROR", 5000)
        if self.dialog is not None:
            self.refresh_dialog()
        if state.get("enabled") and state.get("hasBook") and previous.get("id") != state.get("id"):
            self.open_dialog()
        if not state.get("enabled") and self.dialog is not None:
            self.dialog.hide()
        if queued_page is not None and queued_page != state.get("page"):
            self._request_page(queued_page)
        self.owner.update()

    def update(self, **patch: Any) -> None:
        if self.state.get("id"):
            patch["id"] = self.state["id"]
        self.send("novel_action", patch=patch)

    def turn(self, delta: int) -> None:
        total = int(self.state.get("totalPages", 0))
        if not total:
            return
        current = self.queued_page if self.queued_page is not None else self.requested_page
        if current is None:
            current = int(self.state.get("page", 0))
        page = max(0, min(total - 1, current + delta))
        if page == current:
            return
        if self.pending:
            self.queued_page = page
        else:
            self._request_page(page)

    def _request_page(self, page: int) -> None:
        self.pending = True
        self.requested_page = page
        self.update(page=page)

    def handle_input(self, event: Any) -> bool:
        from PySide6.QtCore import QEvent, Qt

        if event.type() == QEvent.Type.KeyPress:
            if event.modifiers() != Qt.KeyboardModifier.NoModifier:
                return False
            direction = {Qt.Key.Key_Up: -1, Qt.Key.Key_PageUp: -1,
                         Qt.Key.Key_Down: 1, Qt.Key.Key_PageDown: 1}.get(event.key())
            if direction is None:
                return False
            self.turn(direction)
        elif event.type() == QEvent.Type.Wheel:
            if event.modifiers() != Qt.KeyboardModifier.NoModifier:
                return False
            source = "pixel" if event.pixelDelta().y() else "angle"
            amount = event.pixelDelta().y() if source == "pixel" else event.angleDelta().y()
            if not amount:
                return False
            now = time.monotonic()
            if (event.phase() == Qt.ScrollPhase.ScrollBegin or self.wheel_source != source
                    or now - self.wheel_at > 0.5 or amount * self.wheel_delta < 0):
                self.wheel_delta = 0.0
            self.wheel_source, self.wheel_at = source, now
            self.wheel_delta += amount
            threshold = 60 if source == "pixel" else 120
            steps = math.trunc(self.wheel_delta / threshold)
            if steps:
                self.wheel_delta -= steps * threshold
                self.turn(-steps)
        else:
            return False
        event.accept()
        return True

    def tick(self) -> None:
        reading = self.active()
        if self.dialog is not None and self.dialog.isVisible():
            if not self.state.get("enabled"):
                label = "阅读模式已关闭"
            elif self.state.get("autoTurn"):
                label = "摸鱼阅读中 · 自动翻页" if reading else "摸鱼阅读中 · 自动翻页已暂停"
            else:
                label = "摸鱼阅读中 · 手动翻页"
            self.mode_label.setText(label)
        if not reading or not self.state.get("autoTurn"):
            self.next_page_at = None
            return
        if self.pending or self.state.get("page", 0) >= self.state.get("totalPages", 0) - 1:
            return
        now = time.monotonic()
        if self.next_page_at is None:
            self.next_page_at = now + self.state.get("secondsPerPage", 20)
        elif now >= self.next_page_at:
            self.next_page_at = None
            self.turn(1)

    def choose_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self.dialog or self.owner, "导入自己的 TXT 小说", "", "TXT 小说 (*.txt)")
        if path:
            self.send("novel_action", importPath=path)

    def add_menu(self, menu: Any) -> None:
        submenu = menu.addMenu("摸鱼模式（看小说）")
        submenu.addAction("导入 TXT 小说…", self.choose_file)
        enabled = submenu.addAction("开启摸鱼阅读")
        enabled.setCheckable(True)
        enabled.setChecked(self.state.get("enabled", True))
        enabled.triggered.connect(lambda checked: self.update(enabled=checked))
        show = submenu.addAction("打开阅读窗口", self.open_dialog)
        show.setEnabled(bool(self.state.get("hasBook")))
        auto = submenu.addAction("自动翻页")
        auto.setCheckable(True)
        auto.setChecked(self.state.get("autoTurn", False))
        auto.triggered.connect(lambda checked: self.update(autoTurn=checked))

    def open_dialog(self) -> None:
        from PySide6.QtCore import QObject, Qt
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

        if self.dialog is None:
            self.dialog = QDialog(self.owner, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
            self.dialog.setWindowTitle("小肥蠊 · 摸鱼阅读")
            self.dialog.setFont(QFont("Microsoft YaHei UI", 10))
            self.dialog.resize(430, 510)
            self.dialog.setStyleSheet(
                "QDialog { background: #FAF7EF; color: #403B32; }"
                "QLabel, QCheckBox { color: #403B32; }"
                "QTextEdit { background: #FFFCF5; color: #403B32; border: 1px solid #E2D9C9;"
                " border-radius: 8px; padding: 14px; font-family: 'Microsoft YaHei UI'; font-size: 16px; }"
                "QPushButton { background: #FFFDF8; color: #403B32; border: 1px solid #D9CFBC;"
                " border-radius: 6px; padding: 7px 12px; }"
                "QPushButton:disabled { color: #A89E8C; }"
            )
            layout = QVBoxLayout(self.dialog)
            layout.setContentsMargins(18, 16, 18, 16)
            self.title_label = QLabel()
            self.title_label.setTextFormat(Qt.TextFormat.PlainText)
            self.title_label.setWordWrap(True)
            self.title_label.setStyleSheet("font-size: 17px; font-weight: 600;")
            layout.addWidget(self.title_label)
            self.mode_label = QLabel("摸鱼阅读中")
            layout.addWidget(self.mode_label)
            self.text = QTextEdit()
            self.text.setReadOnly(True)
            layout.addWidget(self.text, 1)
            hint = QLabel("↑ / PgUp 上一页 · ↓ / PgDn 下一页 · 滚轮翻页")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #827662; font-size: 12px;")
            layout.addWidget(hint)
            controls = QHBoxLayout()
            self.previous = QPushButton("上一页")
            self.previous.clicked.connect(lambda: self.turn(-1))
            controls.addWidget(self.previous)
            self.progress = QLabel()
            self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
            controls.addWidget(self.progress, 1)
            self.next = QPushButton("下一页")
            self.next.clicked.connect(lambda: self.turn(1))
            controls.addWidget(self.next)
            layout.addLayout(controls)
            options = QHBoxLayout()
            self.auto = QCheckBox("自动翻页（空闲时）")
            self.auto.toggled.connect(lambda checked: self.update(autoTurn=checked))
            options.addWidget(self.auto)
            options.addStretch()
            select = QPushButton("导入 TXT")
            select.clicked.connect(self.choose_file)
            options.addWidget(select)
            layout.addLayout(options)
            reader = self

            class ReadingInputs(QObject):
                def eventFilter(self, watched: Any, event: Any) -> bool:
                    return reader.handle_input(event) or super().eventFilter(watched, event)

            self.input_filter = ReadingInputs(self.dialog)
            # Keep navigation within this window, including QTextEdit's viewport.
            for widget in [self.dialog, *self.dialog.findChildren(QWidget)]:
                widget.installEventFilter(self.input_filter)
        self.refresh_dialog()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        self.text.setFocus(Qt.FocusReason.OtherFocusReason)

    def refresh_dialog(self) -> None:
        state = self.state
        page, total = state.get("page", 0), state.get("totalPages", 0)
        self.title_label.setText(str(state.get("title") or "请导入自己的小说"))
        self.text.setPlainText(str(state.get("content") or "点击「导入 TXT」选择本机小说。"))
        self.progress.setText(f"{page + 1 if total else 0} / {total}")
        self.previous.setEnabled(page > 0)
        self.next.setEnabled(page + 1 < total)
        self.auto.blockSignals(True)
        self.auto.setChecked(state.get("autoTurn", False))
        self.auto.blockSignals(False)

    def draw_book(self, painter: Any, rect: tuple[int, int, int, int], reduced_motion: bool) -> None:
        if not self.active():
            return
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QPainterPath, QPen

        x, y, width, height = rect
        painter.save()
        painter.translate(x + width * 0.51, y + height * 0.65)
        scale = width / 412
        painter.scale(scale, scale)
        if not reduced_motion:
            painter.rotate(math.sin(time.monotonic() * 1.1) * 1.2)
        cover = QPainterPath()
        cover.moveTo(-63, -19)
        cover.lineTo(-7, -13)
        cover.quadTo(0, -8, 7, -13)
        cover.lineTo(63, -19)
        cover.lineTo(63, 34)
        cover.lineTo(7, 41)
        cover.quadTo(0, 38, -7, 41)
        cover.lineTo(-63, 34)
        cover.closeSubpath()
        painter.setPen(QPen(QColor("#88634A"), 3))
        painter.setBrush(QColor("#FFF2D1"))
        painter.drawPath(cover)
        painter.drawLine(QPointF(0, -8), QPointF(0, 37))
        painter.setPen(QPen(QColor("#CCB28D"), 1.5))
        for row in range(4):
            yy = -3 + row * 8
            painter.drawLine(QPointF(-51, yy), QPointF(-12, yy + 4))
            painter.drawLine(QPointF(12, yy + 4), QPointF(51, yy))
        phase = (time.monotonic() - self.turn_started) / 0.7
        if not reduced_motion and 0 <= phase < 1:
            painter.setBrush(QColor("#FFFCED"))
            painter.setPen(QPen(QColor("#CCB28D"), 1))
            leaf = QPainterPath()
            leaf.moveTo(0, -9)
            edge = 57 * math.cos(phase * math.pi)
            leaf.quadTo(edge, -37, edge, -16)
            leaf.lineTo(edge, 33)
            leaf.lineTo(0, 38)
            leaf.closeSubpath()
            painter.drawPath(leaf)
        painter.restore()
