"""Local video player and watching animation for the desktop companion."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any


VIDEO_EXTENSIONS = {'.mp4', '.m4v', '.mkv', '.webm', '.avi', '.mov', '.mpg', '.mpeg'}


def timestamp(milliseconds: int) -> str:
    seconds = max(0, int(milliseconds)) // 1000
    hours, minutes, seconds = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f'{hours:02}:{minutes:02}:{seconds:02}' if hours else f'{minutes:02}:{seconds:02}'


class VideoMode:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.dialog = None
        self.player = None
        self.path: Path | None = None
        self.novel_was_visible = False
        self.task_was_visible = False
        self.source = 'local'
        self.browser = None

    @property
    def playing(self) -> bool:
        return self.player is not None and self.player.playbackState() == self.player.PlaybackState.PlayingState

    @property
    def animating(self) -> bool:
        return self.playing or (self.source == 'douyin' and self.browser is not None
                                and self.browser.ready and self.owner.watching_video)

    def enter(self) -> bool:
        if self.owner.watching_video:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return True
        if self.dialog is None:
            try:
                self._create_dialog()
            except (ImportError, RuntimeError):
                self.owner._show_overlay('播放器不可用', '请安装包含 Qt 视频组件的桌宠版本', 'ERROR', 5000)
                return False
        if self.owner.chess_mode:
            self.owner.xiangqi_mode.leave()
        if self.owner.voice_mode != 'off':
            self.owner._stop_voice(finalize=False)
        novel, task = self.owner.novel_reader.dialog, self.owner.task_dialog
        self.novel_was_visible = novel is not None and novel.isVisible()
        self.task_was_visible = task is not None and task.isVisible()
        if self.novel_was_visible:
            novel.hide()
        if self.task_was_visible:
            task.hide()
        self.owner.watching_video = True
        self.owner._sync_bubble_size()
        self._position_dialog()
        self.dialog.show()
        if self.source == 'douyin' and self.browser is not None:
            self.browser.resume()
        self.dialog.raise_()
        self.dialog.activateWindow()
        self.owner.update()
        return True

    def _position_dialog(self) -> None:
        screen = self.owner._screen_geometry_at(self.owner.pet_x, self.owner.pet_y)
        if screen is not None:
            preferred = (1100, 780) if self.source == 'douyin' else (620, 470)
            self.dialog.resize(min(preferred[0], screen.width() - 32), min(preferred[1], screen.height() - 54))
            width, height = self.dialog.width(), self.dialog.height()
            x = self.owner.pet_x - width - 14
            if x < screen.left():
                x = self.owner.pet_x + self.owner._pet_size()[0] + 14
            self.dialog.move(max(screen.left() + 8, min(x, screen.right() - width - 8)),
                             max(screen.top() + 24, min(self.owner.pet_y - 70, screen.bottom() - height - 28)))

    def use_local(self) -> None:
        self.source = 'local'
        if self.browser is not None:
            self.browser.suspend()
        self.local_panel.show()
        self.local_button.setChecked(True)
        self.douyin_button.setChecked(False)
        self.title.setText(self.path.name if self.path is not None else '和小肥蠊一起看视频')
        self.status.setText('已暂停 · 空格继续播放' if self.path is not None else '选择本地视频，开启一起看视频模式。')
        for shortcut in self.shortcuts:
            shortcut.setEnabled(True)
        if self.owner.watching_video:
            self._position_dialog()

    def show_douyin(self) -> bool:
        if not self.owner.watching_video and not self.enter():
            return False
        if self.browser is None:
            try:
                try:
                    from .douyin_browser import DouyinBrowser
                except ImportError:
                    from douyin_browser import DouyinBrowser
                self.browser = DouyinBrowser(self.dialog, self._browser_status, self.leave)
                self.main_layout.addWidget(self.browser.widget, 1)
            except (ImportError, RuntimeError, OSError) as error:
                self.douyin_button.setChecked(False)
                self.local_button.setChecked(True)
                self.status.setText(str(error))
                return False
        if self.playing:
            self.player.pause()
        self.source = 'douyin'
        self.local_panel.hide()
        self.local_button.setChecked(False)
        self.douyin_button.setChecked(True)
        self.title.setText('抖音 · 小肥蠊陪你一起看')
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False)
        self._position_dialog()
        self.browser.resume()
        return True

    def _browser_status(self, text: str) -> None:
        if self.source == 'douyin':
            self.status.setText(text)
            self.owner.update()

    def leave(self, *_args) -> None:
        if not self.owner.watching_video:
            return
        if self.playing:
            self.player.pause()
        if self.browser is not None:
            self.browser.suspend()
        self.dialog.hide()
        self.owner.watching_video = False
        self.owner._sync_bubble_size()
        if self.novel_was_visible and self.owner.novel_reader.state.get('enabled'):
            self.owner.novel_reader.dialog.show()
        if self.task_was_visible and self.owner.task_dialog is not None:
            self.owner.task_dialog.show()
        self.owner.update()

    def dispose(self) -> None:
        if self.browser is not None:
            self.browser.dispose()
        if self.player is not None:
            from PySide6.QtCore import QUrl

            self.player.stop()
            self.player.setSource(QUrl())
        if self.dialog is not None:
            self.dialog.hide()

    def choose_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self.dialog, '选择和小肥蠊一起看的视频', '',
                                            '视频 (*.mp4 *.m4v *.mkv *.webm *.avi *.mov *.mpg *.mpeg)')
        if path:
            self.load(path)

    def load(self, path: str, *, autoplay: bool = True) -> bool:
        from PySide6.QtCore import QUrl

        candidate = Path(path).expanduser()
        if candidate.suffix.lower() not in VIDEO_EXTENSIONS or not candidate.is_file():
            if self.dialog is not None:
                self.status.setText('请选择存在的 MP4、MKV、WebM、AVI 或 MOV 等本地视频。')
            return False
        if not self.owner.watching_video and not self.enter():
            return False
        self.use_local()
        self.path = candidate.resolve()
        self.title.setText(self.path.name)
        self.title.setToolTip(str(self.path))
        self.placeholder.hide()
        self.video.show()
        self.seek.setRange(0, 0)
        self.seek.setEnabled(False)
        self.time_label.setText('00:00 / 00:00')
        self.video.clear()
        self.player.setSource(QUrl.fromLocalFile(str(self.path)))
        self.play_button.setEnabled(True)
        if autoplay:
            self.player.play()
        return True

    def toggle_play(self) -> None:
        if self.path is None:
            return
        if self.playing:
            self.player.pause()
        else:
            if self.player.mediaStatus() == self.player.MediaStatus.EndOfMedia:
                self.player.setPosition(0)
            self.player.play()

    def skip(self, milliseconds: int) -> None:
        if self.player.isSeekable():
            self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + milliseconds)))

    def _position_changed(self, position: int) -> None:
        from PySide6.QtCore import QSignalBlocker

        if not self.seek.isSliderDown():
            with QSignalBlocker(self.seek):
                self.seek.setValue(position)
        self.time_label.setText(f'{timestamp(position)} / {timestamp(self.player.duration())}')

    def _duration_changed(self, duration: int) -> None:
        self.seek.setRange(0, max(0, duration))
        self.seek.setEnabled(duration > 0 and self.player.isSeekable())
        self._position_changed(self.player.position())

    def _state_changed(self, *_args) -> None:
        self.play_button.setText('暂停' if self.playing else '播放')
        if self.source == 'local' and self.path is not None and self.player.error() == self.player.Error.NoError:
            self.status.setText('小肥蠊正陪你一起看' if self.playing else '已暂停 · 空格继续播放')
        self.owner.update()

    def _media_status(self, status) -> None:
        if self.source != 'local':
            return
        if status == self.player.MediaStatus.EndOfMedia:
            self.status.setText('播放完啦，点「重播」再看一遍。')
            self.play_button.setText('重播')
        elif status == self.player.MediaStatus.LoadingMedia:
            self.status.setText('正在打开视频…')

    def _error(self, *_args) -> None:
        if self.source == 'local':
            self.status.setText('播放失败，请更换视频或编码格式：' + self.player.errorString())
        self.owner.update()

    def _create_dialog(self) -> None:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QShortcut, QTransform
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
        from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

        class VideoSurface(QWidget):
            """Paint decoded frames in the same native surface as the player controls."""
            def __init__(self, parent):
                super().__init__(parent)
                self.image = QImage()
                self.sink = QVideoSink(self)
                self.sink.videoFrameChanged.connect(self.receive_frame)
                self.setAccessibleName('视频画面')
                self.setMinimumHeight(130)

            def videoSink(self):
                return self.sink

            def clear(self):
                self.image = QImage()
                self.update()

            def receive_frame(self, frame):
                if frame.isValid():
                    image = frame.toImage()
                    if not image.isNull():
                        rotation = frame.rotation() if hasattr(frame, 'rotation') else frame.rotationAngle()
                        angle = rotation.value
                        if angle:
                            image = image.transformed(QTransform().rotate(angle))
                        if hasattr(frame, 'mirrored') and frame.mirrored():
                            image = image.mirrored(True, False)
                        self.image = image
                        self.update()

            def paintEvent(self, _event):
                painter = QPainter(self)
                painter.fillRect(self.rect(), QColor('#101820'))
                if not self.image.isNull():
                    size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
                    target = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                                    size.width(), size.height())
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    painter.drawImage(target, self.image)
                painter.end()

        self.dialog = QDialog(self.owner, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.dialog.setWindowTitle('小肥蠊 · 一起看视频')
        self.dialog.setMinimumSize(360, 300)
        self.dialog.setFont(QFont('Microsoft YaHei UI', 10))
        self.dialog.setStyleSheet(
            'QDialog { background: #19232C; } QLabel { color: #DFE8ED; }'
            'QPushButton { color: #E4ECEF; background: #293943; border: 1px solid #3D515D;'
            ' border-radius: 7px; padding: 7px 10px; } QPushButton:hover { background: #364E58; }'
            'QPushButton:disabled { color: #7A8B93; }'
            'QPushButton:checked { background: #37564E; border-color: #9AC9AC; }'
            'QSlider::groove:horizontal { height: 4px; background: #3D515D; border-radius: 2px; }'
            'QSlider::sub-page:horizontal { background: #9AC9AC; border-radius: 2px; }'
            'QSlider::handle:horizontal { width: 12px; margin: -4px 0; background: #C4E5CF; border-radius: 6px; }'
        )
        layout = QVBoxLayout(self.dialog)
        self.main_layout = layout
        layout.setContentsMargins(16, 14, 16, 14)
        self.title = QLabel('和小肥蠊一起看视频')
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setStyleSheet('font-size: 16px; font-weight: 600;')
        layout.addWidget(self.title)
        self.status = QLabel('选择本地视频，开启一起看视频模式。')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setStyleSheet('color: #9AB5BC; font-size: 12px;')
        layout.addWidget(self.status)
        sources = QHBoxLayout()
        self.local_button = QPushButton('本地视频')
        self.local_button.setCheckable(True)
        self.local_button.setChecked(True)
        self.local_button.clicked.connect(self.use_local)
        sources.addWidget(self.local_button)
        self.douyin_button = QPushButton('抖音 · 扫码登录')
        self.douyin_button.setCheckable(True)
        self.douyin_button.setEnabled(sys.platform == 'win32')
        self.douyin_button.clicked.connect(self.show_douyin)
        sources.addWidget(self.douyin_button)
        sources.addStretch()
        layout.addLayout(sources)
        self.local_panel = QWidget(self.dialog)
        content = QVBoxLayout(self.local_panel)
        content.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.local_panel, 1)
        self.video = VideoSurface(self.dialog)
        content.addWidget(self.video, 1)
        self.video.hide()
        self.placeholder = QLabel('选一部视频\n小肥蠊陪你一起看')
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet('background: #101820; color: #91A8B2; border-radius: 10px; font-size: 16px;')
        self.placeholder.setMinimumHeight(130)
        content.addWidget(self.placeholder, 1)
        self.audio = QAudioOutput(self.dialog)
        self.audio.setVolume(0.35)
        self.player = QMediaPlayer(self.dialog)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoSink(self.video.videoSink())
        timeline = QHBoxLayout()
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName('视频进度')
        self.seek.setEnabled(False)
        self.seek.sliderReleased.connect(lambda: self.player.setPosition(self.seek.value()))
        self.seek.valueChanged.connect(lambda value: self.player.setPosition(value) if not self.seek.isSliderDown() else None)
        self.seek.sliderMoved.connect(lambda value: self.time_label.setText(f'{timestamp(value)} / {timestamp(self.player.duration())}'))
        timeline.addWidget(self.seek, 1)
        self.time_label = QLabel('00:00 / 00:00')
        self.time_label.setStyleSheet('font-size: 11px; color: #A9BBC3;')
        timeline.addWidget(self.time_label)
        content.addLayout(timeline)
        controls = QHBoxLayout()
        self.open_button = QPushButton('选择视频')
        self.open_button.clicked.connect(self.choose_file)
        controls.addWidget(self.open_button)
        self.play_button = QPushButton('播放')
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)
        self.mute_button = QPushButton('静音')
        self.mute_button.setCheckable(True)
        self.mute_button.toggled.connect(self.audio.setMuted)
        self.mute_button.toggled.connect(lambda muted: self.mute_button.setText('取消静音' if muted else '静音'))
        controls.addWidget(self.mute_button)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setAccessibleName('视频音量')
        self.volume.setRange(0, 100)
        self.volume.setValue(35)
        self.volume.setFixedWidth(64)
        self.volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        controls.addWidget(self.volume)
        controls.addStretch()
        self.close_button = QPushButton('收起视频')
        self.close_button.clicked.connect(self.leave)
        controls.addWidget(self.close_button)
        content.addLayout(controls)
        hint = QLabel('空格 播放/暂停   ·   ← / → 快退/快进 5 秒   ·   Esc 收起')
        hint.setWordWrap(True)
        hint.setStyleSheet('font-size: 11px; color: #849BA7;')
        content.addWidget(hint)
        self.shortcuts = []
        for key, callback in ((Qt.Key.Key_Space, self.toggle_play), (Qt.Key.Key_Left, lambda: self.skip(-5000)),
                              (Qt.Key.Key_Right, lambda: self.skip(5000))):
            shortcut = QShortcut(QKeySequence(key), self.dialog)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.seekableChanged.connect(lambda seekable: self.seek.setEnabled(seekable and self.player.duration() > 0))
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._error)
        self.dialog.finished.connect(self.leave)
        QApplication.instance().aboutToQuit.connect(self.dispose)

    def draw_prop(self, painter, rect) -> None:
        if not self.owner.watching_video or self.owner.dragging or self.owner.file_drop_hover:
            return
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QColor, QPainterPath, QPen

        x, y, width, height = rect
        painter.save()
        painter.translate(x + width * 0.51, y + height * 0.68)
        painter.scale(width / 412, width / 412)
        painter.setPen(QPen(QColor('#263C45'), 2))
        painter.setBrush(QColor('#3B535D'))
        painter.drawRoundedRect(QRectF(-62, -24, 124, 63), 6, 6)
        glow = math.sin(time.monotonic() * 1.7) * 8 if self.animating and not self.owner.reduced_motion else 0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(35 + round(glow), 83 + round(glow), 98 + round(glow)))
        painter.drawRoundedRect(QRectF(-54, -17, 108, 48), 3, 3)
        painter.setBrush(QColor('#A7D0CD'))
        if self.animating:
            painter.drawRoundedRect(QRectF(-40, 9, 32, 4), 2, 2)
            painter.drawRoundedRect(QRectF(-40, 18, 67, 3), 1, 1)
        else:
            triangle = QPainterPath()
            triangle.moveTo(-7, -7)
            triangle.lineTo(10, 4)
            triangle.lineTo(-7, 15)
            triangle.closeSubpath()
            painter.drawPath(triangle)
        painter.setBrush(QColor('#526873'))
        painter.drawRoundedRect(QRectF(-5, 39, 10, 9), 1, 1)
        painter.drawRoundedRect(QRectF(-24, 47, 48, 5), 2, 2)
        painter.restore()
