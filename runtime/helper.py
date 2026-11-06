"""Phase 0 native BigFish helper.

The DSH plugin owns this process and sends newline-delimited JSON over stdin.
Closing stdin is a lifecycle signal: the helper exits instead of becoming an
independent desktop application.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import tempfile
import threading
import time
import uuid
import wave
from collections import OrderedDict
from collections import deque
from pathlib import Path
from typing import Any, TextIO

try:
    from .animation_model import AnimationModel, crossfade_duration, flight_clip, flight_heading, motion_pose
    from .layout_store import default_layout_path, load_layout, save_layout
    from .asset_paths import bundle_root
    from .pet_geometry import bubble_top, position_window
    from .voice_capture import Pcm16MonoConverter, VoiceSegmenter
    from .novel_reader import NovelReader
    from .xiangqi_mode import XiangqiMode
    from .video_mode import VideoMode
except ImportError:
    from animation_model import AnimationModel, crossfade_duration, flight_clip, flight_heading, motion_pose
    from layout_store import default_layout_path, load_layout, save_layout
    from asset_paths import bundle_root
    from pet_geometry import bubble_top, position_window
    from voice_capture import Pcm16MonoConverter, VoiceSegmenter
    from novel_reader import NovelReader
    from xiangqi_mode import XiangqiMode
    from video_mode import VideoMode


PROTOCOL_VERSION = 1
STATES = {"IDLE", "THINKING", "WORKING", "WAITING", "SUCCESS", "ERROR", "DISCONNECTED"}
# A decoded 412x344 ARGB32 frame costs ~0.55 MB, so keeping every frame of a
# 24 fps set resident would need well over a gigabyte. Frames are read from disk
# once as compressed bytes and decoded through a bounded cache instead.
DECODED_FRAME_CACHE = 24


def configure_qt_platform() -> None:
    """Prefer XWayland when available so desktop-window controls keep working."""
    if sys.platform != "linux" or os.environ.get("QT_QPA_PLATFORM"):
        return
    platforms: list[str] = []
    if os.environ.get("DISPLAY"):
        platforms.append("xcb")
    if os.environ.get("WAYLAND_DISPLAY"):
        platforms.append("wayland")
    if platforms:
        os.environ["QT_QPA_PLATFORM"] = ";".join(platforms)


def configure_stdio() -> None:
    """Make the JSONL pipe UTF-8 regardless of the Windows console code page."""
    for stream, errors in ((sys.stdin, "strict"), (sys.stdout, "backslashreplace"), (sys.stderr, "backslashreplace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors=errors)


def parse_message(line: str) -> dict[str, Any]:
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError("message must be an object")
    if message.get("protocolVersion") != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    kind = message.get("kind")
    if kind in {"state", "pulse"} and message.get("state") not in STATES:
        raise ValueError("unsupported companion state")
    return message


def emit_reply(kind: str, **payload: Any) -> None:
    print(
        json.dumps(
            {"protocolVersion": PROTOCOL_VERSION, "kind": kind, "timestamp": int(time.time() * 1000), **payload},
            ensure_ascii=False,
        ),
        flush=True,
    )


# ---- Glove cursor (native Win32 .cur) ----
def _cursor_api() -> tuple[Any, Any, Any]:
    """Return configured (LoadCursorFromFileW, SetCursor, LoadCursorW) callables.

    Function signatures are declared explicitly so HCURSOR values are handled
    as pointer-sized handles: without argtypes/restype, ctypes treats the
    return value as a C int and truncates 64-bit HCURSORs. wintypes has no
    HCURSOR type, so ``wintypes.HANDLE`` (pointer-sized) is used.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    load_from_file = user32.LoadCursorFromFileW
    load_from_file.argtypes = [wintypes.LPCWSTR]
    load_from_file.restype = wintypes.HANDLE

    set_cursor = user32.SetCursor
    set_cursor.argtypes = [wintypes.HANDLE]
    set_cursor.restype = wintypes.HANDLE

    load_cursor = user32.LoadCursorW
    load_cursor.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR]
    load_cursor.restype = wintypes.HANDLE

    return load_from_file, set_cursor, load_cursor


def load_native_cursor(path: Path) -> Any:
    """Load a .cur cursor with LoadCursorFromFileW (pointer-sized handles).

    Returns None outside Windows or on failure; callers then fall back to the
    Qt default cursor. The resource is loaded at its natural size: per the MSDN
    remarks, LoadCursorFromFileW does not participate in DPI virtualization, so
    the 32x32 .cur is NOT scaled up automatically; the OS renders the cursor
    bitmap on the same pipeline as system cursors.
    """
    if sys.platform != "win32":
        return None
    try:
        handle = _cursor_api()[0](str(path))
        return handle or None
    except Exception:
        return None


def set_native_cursor(handle: Any) -> None:
    """Set the current cursor immediately (bypasses Qt's cursor pipeline)."""
    try:
        _cursor_api()[1](handle)
    except Exception:
        pass


def reset_native_cursor() -> None:
    """Restore the default arrow cursor (IDC_ARROW)."""
    try:
        import ctypes

        # MAKEINTRESOURCE(32512): the identifier is passed as a pointer value.
        arrow = ctypes.cast(ctypes.c_void_p(32512), ctypes.c_wchar_p)
        _cursor_api()[2](None, arrow)
    except Exception:
        pass


class GloveCursorController:
    """Pure state machine for the glove cursor; no Qt or Win32 dependencies.

    ``open_h`` / ``closed_h`` may be None (non-Windows, or the .cur assets are
    missing): every query then returns None, so callers simply fall back to the
    default cursor. This keeps all cursor-state decisions testable.
    """

    WM_LBUTTONDOWN = 0x0201

    def __init__(self, open_h: Any, closed_h: Any) -> None:
        self.open_h = open_h
        self.closed_h = closed_h
        self.pressed = False

    def handle_for(self, closed: bool) -> Any:
        return self.closed_h if closed else self.open_h

    def on_enter(self) -> Any:
        """Pointer entered the pet window: show the open hand."""
        return self.open_h

    def on_leave(self) -> None:
        """Pointer left the pet window: clear the pressed flag, reset to arrow."""
        self.pressed = False
        return None

    def on_press(self) -> Any:
        """Left button pressed: show the closed fist."""
        self.pressed = True
        return self.closed_h

    def on_release(self, inside: bool) -> Any:
        """Left button released: open hand when still inside, otherwise None."""
        self.pressed = False
        return self.open_h if inside else None

    def on_wm_setcursor(self, mouse_msg: int) -> Any:
        """WM_SETCURSOR decision: closed on WM_LBUTTONDOWN (or while pressed)."""
        return self.handle_for(mouse_msg == self.WM_LBUTTONDOWN or self.pressed)


class EventRecorder:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._stream: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = path.open("a", encoding="utf-8")

    def record(self, message: dict[str, Any]) -> None:
        if self._stream is None:
            return
        self._stream.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._stream.flush()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()


def run_headless(recorder: EventRecorder) -> int:
    try:
        emit_reply("ready")
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = parse_message(line)
            except (ValueError, json.JSONDecodeError) as error:
                print(json.dumps({"kind": "error", "message": str(error)}), flush=True)
                continue
            recorder.record(message)
            if message.get("kind") == "ping":
                emit_reply("pong")
                continue
            if message.get("kind") == "shutdown":
                break
    finally:
        recorder.close()
    return 0


def run_visual(recorder: EventRecorder, snapshot_path: Path | None = None,
               preview_voice_mode: str | None = None, preview_chess: bool = False,
               preview_video: Path | None = None, preview_douyin: str | None = None) -> int:
    configure_qt_platform()
    try:
        from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QPoint, QRectF, QSize, Qt, QTimer, QUrl, Signal
        from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap, QTextCursor
        from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QTextEdit, QVBoxLayout, QWidget
    except ImportError as error:
        print(
            f"PySide6 is required for visual mode ({error}). Run with --headless for protocol tests.",
            file=sys.stderr,
        )
        recorder.close()
        return 2
    try:
        from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices, QSoundEffect
    except ImportError:
        QAudio = QAudioFormat = QAudioSource = QMediaDevices = None
        QSoundEffect = None
    try:
        from PySide6.QtTextToSpeech import QTextToSpeech
    except ImportError:
        QTextToSpeech = None

    def action_icon(kind: str, color: str) -> QIcon:
        """Draw small action icons without relying on emoji or platform fonts."""
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(2, 2)
        painter.setPen(QPen(QColor(color), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "record":
            painter.drawRoundedRect(QRectF(9, 3, 6, 11), 3, 3)
            painter.drawArc(QRectF(5.5, 5, 13, 13), 180 * 16, 180 * 16)
            painter.drawLine(12, 18, 12, 21)
            painter.drawLine(9, 21, 15, 21)
        elif kind == "stop":
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
        elif kind in {"call", "hangup"}:
            path = QPainterPath()
            path.moveTo(5, 5)
            path.cubicTo(4, 10, 12, 20, 19, 19)
            painter.setPen(QPen(QColor(color), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(path)
            painter.setPen(QPen(QColor(color), 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(5, 5, 8, 8)
            painter.drawLine(16, 16, 19, 19)
            if kind == "hangup":
                painter.setPen(QPen(QColor(color), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(4, 20, 20, 4)
        elif kind == "send":
            path = QPainterPath()
            path.moveTo(3, 4)
            path.lineTo(21, 12)
            path.lineTo(3, 20)
            path.lineTo(7, 12)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(7, 12, 20, 12)
        elif kind == "add":
            painter.drawLine(12, 4, 12, 20)
            painter.drawLine(4, 12, 20, 12)
        elif kind == "file":
            path = QPainterPath()
            path.moveTo(9, 17)
            path.lineTo(17, 9)
            path.cubicTo(19, 7, 16, 4, 14, 6)
            path.lineTo(6, 14)
            path.cubicTo(3, 17, 7, 21, 10, 18)
            painter.drawPath(path)
        painter.end()
        return QIcon(pixmap)

    class Inbox(QObject):
        message = Signal(dict)
        closed = Signal()

    class TaskInput(QTextEdit):
        submitRequested = Signal()

        def keyPressEvent(self, event: Any) -> None:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.submitRequested.emit()
                event.accept()
                return
            super().keyPressEvent(event)

    class FileTaskDialog(QDialog):
        def __init__(self, owner: Any) -> None:
            super().__init__(None)
            self.owner = owner
            self.setAcceptDrops(True)

        def dragEnterEvent(self, event: Any) -> None:
            self.owner._accept_file_drag(event)

        def dragMoveEvent(self, event: Any) -> None:
            self.owner._accept_file_drag(event)

        def dragLeaveEvent(self, event: Any) -> None:
            self.owner._end_file_hover()
            event.accept()

        def dropEvent(self, event: Any) -> None:
            self.owner._drop_files(event)

    manifest_path = bundle_root() / "assets" / "pet-manifest-custom.json"
    asset_root = manifest_path.parent / "pet"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"Unable to load BigFish asset manifest: {error}", file=sys.stderr)
        recorder.close()
        return 2

    class GloveCursorFilter(QAbstractNativeEventFilter):
        """Owns WM_SETCURSOR while the pointer is over the pet window.

        The pet shows a glove hand cursor: an open hand on hover and a closed
        fist while the left button is held. Native .cur cursors are loaded with
        LoadCursorFromFileW and handed to the OS cursor pipeline directly (the
        same rendering path as system cursors; note the API loads the resource
        at its natural 32x32 size and does not participate in DPI
        virtualization). The message is consumed immediately instead of going
        through Qt's QCursor bitmaps, which are re-scaled by Qt and only take
        effect on the next cursor update cycle.
        """

        def __init__(self, widget: Any, open_h: Any, closed_h: Any) -> None:
            super().__init__()
            self.widget = widget
            self.open_h = open_h
            self.closed_h = closed_h

        def nativeEventFilter(self, event_type: bytes, message: Any):
            try:
                if event_type != b"windows_generic_MSG":
                    return False, 0
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message != 0x0020:  # WM_SETCURSOR
                    return False, 0
                hwnd = int(msg.hWnd) if msg.hWnd else 0
                if hwnd and hwnd != int(self.widget.winId()):
                    # Leave popups (context menu, …) to Qt's default cursor.
                    return False, 0
                hit_test = msg.lParam & 0xFFFF
                if hit_test != 1:  # HTCLIENT
                    return False, 0
                mouse_msg = (msg.lParam >> 16) & 0xFFFF
                handle = self.widget.glove.on_wm_setcursor(mouse_msg)
                if handle:
                    set_native_cursor(handle)
                    return True, 0
            except Exception:
                pass
            return False, 0

    class CompanionWindow(QWidget):
        LABELS = {
            "IDLE": "休息中",
            "THINKING": "思考中",
            "WORKING": "干活中",
            "WAITING": "等你呢",
            "SUCCESS": "完成啦",
            "ERROR": "出问题了",
            "DISCONNECTED": "已断开",
        }

        def __init__(self) -> None:
            super().__init__()
            self.layout_path = default_layout_path()
            self.layout = load_layout(self.layout_path)
            configured_scale = os.environ.get("DSH_DAFEIYU_SCALE")
            try:
                self.scale = min(1.4, max(0.55, float(configured_scale))) if configured_scale else self.layout["scale"]
            except ValueError:
                self.scale = self.layout["scale"]
            configured_bubble_scale = os.environ.get("DSH_DAFEIYU_BUBBLE_SCALE")
            try:
                self.bubble_scale = (
                    min(1.2, max(0.8, float(configured_bubble_scale)))
                    if configured_bubble_scale
                    else self.layout["bubbleScale"]
                )
            except ValueError:
                self.bubble_scale = self.layout["bubbleScale"]
            configured_reduced_motion = os.environ.get("DSH_DAFEIYU_REDUCED_MOTION")
            self.reduced_motion = (
                configured_reduced_motion == "1"
                if configured_reduced_motion is not None
                else self.layout["reducedMotion"]
            )
            configured_sound_enabled = os.environ.get("DSH_DAFEIYU_SOUND_ENABLED")
            self.sound_enabled = configured_sound_enabled != "0"
            configured_sound_pack = os.environ.get("DSH_DAFEIYU_SOUND_PACK")
            self.sound_pack = configured_sound_pack if configured_sound_pack in {"original", "clean", "video", "custom"} else "original"
            custom_sounds_dir = os.environ.get("DSH_DAFEIYU_CUSTOM_SOUNDS_DIR")
            self.custom_sounds_dir = Path(custom_sounds_dir).expanduser() if custom_sounds_dir else bundle_root() / "assets" / "sounds" / "custom"
            self.custom_sound_revision = 0
            self.idle_title = os.environ.get("DSH_DAFEIYU_IDLE_TITLE", "小弟陪大哥待命").strip()[:40] or "小弟陪大哥待命"
            self.sound_effects: dict[Path, Any] = {}
            configured_sound_states = os.environ.get("DSH_DAFEIYU_SOUND_STATES")
            self.sound_states = (
                {part.strip() for part in configured_sound_states.split(",") if part.strip()}
                if configured_sound_states is not None
                else {"SUCCESS", "ERROR"}
            )
            self.activity_level = os.environ.get("DSH_DAFEIYU_ACTIVITY_LEVEL", "normal")
            configured_bubble_mode = os.environ.get("DSH_DAFEIYU_BUBBLE_MODE")
            self.bubble_mode = (
                configured_bubble_mode
                if configured_bubble_mode in {"always", "hidden", "custom"}
                else self.layout.get("bubbleMode", "always")
            )
            configured_bubble_states = os.environ.get("DSH_DAFEIYU_BUBBLE_STATES")
            if configured_bubble_states is not None:
                self.bubble_states = [part.strip() for part in configured_bubble_states.split(",") if part.strip()]
            else:
                self.bubble_states = list(self.layout.get("bubbleStates", ["SUCCESS", "ERROR", "WAITING"]))
            self.model = AnimationModel(manifest)
            self.motion_profiles = manifest.get("motionProfiles", {})
            self.motion_clip_name = self.model.active_clip_name
            self.motion_started_ms = self._now_ms()
            self.frame_sources: dict[str, bytes] = {}
            for clip in self.model.clips.values():
                for frame in clip.frames:
                    if frame in self.frame_sources:
                        continue
                    try:
                        self.frame_sources[frame] = (asset_root / frame).read_bytes()
                    except OSError as error:
                        raise RuntimeError(f"Unable to load BigFish frame: {frame}") from error
            self.decoded_frames: OrderedDict[str, QPixmap] = OrderedDict()
            # Fail here, not on the first paint, when the assets are unreadable or
            # the bundled Qt cannot decode the selected PNG or WebP assets.
            for clip in self.model.clips.values():
                if clip.frames:
                    self._pixmap(clip.frames[0])
            self.decoded_frames.clear()

            self.display_state = "IDLE"
            self.status_state = "IDLE"
            self.status_message = self.idle_title
            self.status_detail = "DSH · 等待下一次任务"
            self.status_deadline_ms: int | None = self._now_ms() + 4200
            # Glove cursor: native .cur handles (loaded at natural size).
            self.glove_open_h = load_native_cursor(asset_root.parent / "cursor_grab.cur")
            self.glove_closed_h = load_native_cursor(asset_root.parent / "cursor_grabbing.cur")
            self.glove = GloveCursorController(self.glove_open_h, self.glove_closed_h)
            self.overlay_state: str | None = None
            self.overlay_message = ""
            self.overlay_detail = ""
            self.overlay_deadline_ms: int | None = None
            self.task = ""
            self.tasks: list[dict[str, Any]] = []
            self.task_dialog: QDialog | None = None
            self.task_editor: QTextEdit | None = None
            self.task_feedback: QLabel | None = None
            self.task_send_button: QPushButton | None = None
            self.task_input: TaskInput | None = None
            self.task_inline_send: QPushButton | None = None
            self.task_file_button: QPushButton | None = None
            self.task_dialog_file_button: QPushButton | None = None
            self.task_file_label: QLabel | None = None
            self.task_file_list: QListWidget | None = None
            self.task_dialog_file_label: QLabel | None = None
            self.task_dialog_file_list: QListWidget | None = None
            self.task_files: list[str] = []
            self.pending_task_files: list[str] = []
            self.voice_record_button: QPushButton | None = None
            self.voice_call_button: QPushButton | None = None
            self.voice_mode = "off"
            self.voice_started_ms: int | None = None
            self.voice_ready = False
            self.voice_level = 0.0
            self.voice_level_at_ms = 0
            self.voice_last_speech_ms = 0
            self.voice_last_text = ""
            self.voice_last_text_at_ms = 0
            self.call_history: deque[tuple[str, str]] = deque(maxlen=40)
            self.call_transcript: QTextEdit | None = None
            self.voice_source: Any = None
            self.voice_device: Any = None
            self.voice_converter: Pcm16MonoConverter | None = None
            self.voice_segmenter = VoiceSegmenter()
            self.voice_pending: dict[str, str] = {}
            self.voice_pending_started_ms = 0
            self.voice_tasks: deque[str] = deque()
            self.speech_queue: deque[str] = deque()
            self.tts = QTextToSpeech() if QTextToSpeech is not None else None
            if self.tts is not None:
                chinese_voices = [voice for voice in self.tts.availableVoices() if voice.locale().name().startswith("zh")]
                if chinese_voices:
                    self.tts.setVoice(chinese_voices[0])
                self.tts.stateChanged.connect(self._on_speech_state)
            self.pending_task_id: str | None = None
            self.pending_task_text = ""
            self.webui_url = os.environ.get("DSH_DAFEIYU_WEBUI_URL", "http://127.0.0.1:3080/")
            self.open_label = os.environ.get("DSH_DAFEIYU_OPEN_LABEL", "打开 DSH")
            self.balance_summary = ""
            self.chess_mode = False
            self.xiangqi_mode = XiangqiMode(self)
            self.watching_video = False
            self.video_watcher = VideoMode(self)
            self.market_watch_enabled = False
            self.market_watch_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
            self.market_watch_symbol = "BTCUSDT"
            self.market_watch_interval = "15m"
            self.market_watch_status = "disabled"
            self.market_watch_endpoint = "stream.binance.com:9443"
            self.market_watch_quotes: dict[str, dict[str, Any]] = {}
            self.market_watch_history: deque[float] = deque(maxlen=40)
            self.novel_reader = NovelReader(self, emit_reply)
            self.drag_origin: QPoint | None = None
            self.drag_direction_anchor: QPoint | None = None
            self.drag_direction = "down"
            self.pet_origin: QPoint | None = None
            self.pet_x = 0
            self.pet_y = 0
            self.dragging = False
            self.file_drop_hover = False
            self.last_tick_ms = self._now_ms()
            self.fade_from_pixmap: QPixmap | None = None
            self.fade_started = 0.0
            self.fade_duration = 0.15
            self.animation_timer = QTimer(self)
            self.animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.animation_timer.timeout.connect(self._tick)
            self.animation_timer.start(self._animation_interval_ms())
            self.micro_timer = QTimer(self)
            self.micro_timer.setSingleShot(True)
            self.micro_timer.timeout.connect(self._play_idle_micro)
            if not self.reduced_motion:
                self._schedule_micro()
            self.snapshot_saved = False
            self.setWindowTitle("DSH 大肥鱼")
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAcceptDrops(True)
            self.task_input = TaskInput(self)
            self.task_input.setAcceptDrops(False)
            self.task_input.setPlaceholderText("给小弟安排任务…")
            self.task_input.setAcceptRichText(False)
            self.task_input.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self.task_input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.task_input.setStyleSheet(
                "QTextEdit { background: transparent; color: #25282D; border: 0; padding: 2px 0; font-size: 13px;"
                " selection-background-color: #CFE0FF; }"
            )
            self.task_input.submitRequested.connect(self._submit_inline_task)
            self.task_input.textChanged.connect(self._sync_bubble_size)
            self.task_inline_send = QPushButton(self)
            self.task_inline_send.setIcon(action_icon("send", "#FFFFFF"))
            self.task_inline_send.setToolTip("发送任务到当前对话")
            self.task_inline_send.setAccessibleName("发送任务")
            self.task_inline_send.setCursor(Qt.CursorShape.PointingHandCursor)
            self.task_inline_send.setStyleSheet(
                "QPushButton { color: white; background: #3478F6; border: 0; border-radius: 15px; }"
                "QPushButton:hover { background: #2563DB; }"
                "QPushButton:disabled { background: #93B4F8; }"
            )
            self.task_inline_send.clicked.connect(self._submit_inline_task)
            self.voice_record_button = QPushButton(self)
            self.voice_call_button = QPushButton(self)
            for button in (self.voice_record_button, self.voice_call_button):
                button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.voice_record_button.clicked.connect(lambda: self._toggle_voice("dictation"))
            self.voice_call_button.clicked.connect(lambda: self._toggle_voice("call"))
            self.task_file_button = QPushButton(self)
            self.task_file_button.setIcon(action_icon("add", "#354052"))
            self.task_file_button.setAccessibleName("选择文件")
            self.task_file_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.task_file_button.setStyleSheet(
                "QPushButton { color: #354052; background: transparent; border: 0; border-radius: 14px; font-weight: 600; }"
                "QPushButton:hover { background: #EEF3FC; }"
            )
            self.task_file_button.clicked.connect(self._choose_task_files)
            self.task_file_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.task_file_button.customContextMenuRequested.connect(lambda _pos: self._show_task_files_menu())
            self.task_file_label = QLabel("已选文件 · 双击移除", self)
            self.task_file_label.setStyleSheet("color: #596579; font-size: 11px; font-weight: 600;")
            self.task_file_list = self._make_file_list(self)
            self.call_transcript = QTextEdit(self)
            self.call_transcript.setReadOnly(True)
            self.call_transcript.setPlaceholderText("你说的话和大哥的回复会显示在这里")
            self.call_transcript.setStyleSheet(
                "QTextEdit { background: #F5F8FC; color: #25282D; border: 1px solid #DFE7F2;"
                " border-radius: 10px; padding: 6px 8px; font-size: 11px; }"
            )
            self.call_transcript.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.call_transcript.setAcceptDrops(False)
            self.call_transcript.hide()
            self.chess_button = QPushButton("下象棋", self)
            self.chess_button.setAccessibleName("与小肥蠊下象棋")
            self.chess_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.chess_button.setStyleSheet(
                "QPushButton { color: #2E806B; background: #EAF3ED; border: 0; border-radius: 8px;"
                " padding: 2px 8px; font-size: 11px; } QPushButton:hover { background: #D8EADD; }"
            )
            self.chess_button.clicked.connect(self.xiangqi_mode.enter)
            self.video_button = QPushButton("看视频", self)
            self.video_button.setAccessibleName("和小肥蠊一起看视频")
            self.video_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.video_button.setStyleSheet(self.chess_button.styleSheet())
            self.video_button.clicked.connect(self.video_watcher.enter)
            self._refresh_voice_buttons()
            self._refresh_task_files()
            self._apply_window_size()
            QTimer.singleShot(0, self._restore_visible_position)

        def _make_file_list(self, parent: QWidget) -> QListWidget:
            view = QListWidget(parent)
            view.setAcceptDrops(False)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            view.setTextElideMode(Qt.TextElideMode.ElideMiddle)
            view.setStyleSheet(
                "QListWidget { background: #F5F8FC; color: #354258; border: 1px solid #DFE7F2;"
                " border-radius: 8px; padding: 2px; font-size: 11px; }"
                "QListWidget::item { padding: 2px 4px; }"
                "QListWidget::item:selected { background: #DFEAFF; color: #245EB2; border-radius: 4px; }"
            )
            view.itemDoubleClicked.connect(lambda item: self._remove_task_file(item.data(Qt.ItemDataRole.UserRole)))
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(lambda position: self._show_file_list_menu(view, position))
            return view

        def _show_file_list_menu(self, view: QListWidget, position: QPoint) -> None:
            if not self.task_files:
                return
            menu = QMenu(view)
            item = view.itemAt(position)
            if item is not None:
                menu.addAction("移除这个文件", lambda: self._remove_task_file(item.data(Qt.ItemDataRole.UserRole)))
            menu.addAction("清空文件", self._clear_task_files)
            menu.exec(view.mapToGlobal(position))

        def apply_message(self, message: dict[str, Any]) -> None:
            recorder.record(message)
            kind = message.get("kind")
            if kind == "shutdown":
                QApplication.quit()
                return
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            if kind == "task":
                self.task = str(message.get("task", ""))
                self._show_status(
                    str(message.get("message", self.task)),
                    str(message.get("detail", "")),
                    self.model.base_state,
                    None if self.model.base_state in {"THINKING", "WORKING", "WAITING", "ERROR"} else 6000,
                )
            elif kind == "tasks":
                raw_tasks = message.get("tasks")
                self.tasks = raw_tasks if isinstance(raw_tasks, list) else []
                self._sync_bubble_size()
            elif kind == "config":
                self._apply_config(message)
            elif kind == "task_result":
                self._finish_task_submission(message)
            elif kind == "voice_transcript":
                self._apply_voice_transcript(message)
            elif kind == "voice_status":
                self._apply_voice_status(message)
            elif kind == "call_message":
                if self.voice_mode == "call":
                    self._append_call_message("大哥", str(message.get("text", "")))
            elif kind == "speak":
                self._speak_reply(str(message.get("text", "")))
            elif kind == "novel":
                self.novel_reader.apply(message)
            elif kind == "balance":
                self.balance_summary = str(message.get("summary", ""))[:200]
                self._sync_bubble_size()
            elif kind == "market":
                was_enabled = self.market_watch_enabled
                self.market_watch_enabled = message.get("enabled") is True
                raw_symbols = message.get("symbols")
                if isinstance(raw_symbols, list):
                    symbols = list(dict.fromkeys(
                        str(item).strip().upper() for item in raw_symbols
                        if isinstance(item, str) and 5 <= len(item) <= 20 and item.strip().isalnum()
                    ))[:5]
                    if symbols:
                        self.market_watch_symbols = symbols
                raw_interval = message.get("interval")
                if raw_interval in {"1m", "15m", "1h", "4h"}:
                    if raw_interval != self.market_watch_interval:
                        self.market_watch_history.clear()
                    self.market_watch_interval = raw_interval
                selected = message.get("selectedSymbol")
                if isinstance(selected, str) and selected in self.market_watch_symbols:
                    if selected != self.market_watch_symbol:
                        self.market_watch_history.clear()
                    self.market_watch_symbol = selected
                self.market_watch_status = str(message.get("status", "connecting"))
                endpoint = message.get("endpoint")
                if isinstance(endpoint, str) and len(endpoint) <= 80:
                    self.market_watch_endpoint = endpoint
                raw_quotes = message.get("quotes")
                if isinstance(raw_quotes, list):
                    self.market_watch_quotes = {
                        str(item.get("symbol")): item for item in raw_quotes
                        if isinstance(item, dict) and isinstance(item.get("symbol"), str)
                    }
                quote = self.market_watch_quotes.get(self.market_watch_symbol)
                price = quote.get("price") if isinstance(quote, dict) else None
                if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
                    if not self.market_watch_history or self.market_watch_history[-1] != float(price):
                        self.market_watch_history.append(float(price))
                if was_enabled != self.market_watch_enabled:
                    self._sync_bubble_size()
                else:
                    self.update()
            elif kind == "alert":
                if message.get("alert") == "APPROVAL":
                    self._notify_alert("APPROVAL")
            elif kind in {"state", "pulse"}:
                previous_base_state = self.model.base_state
                state = str(message.get("state", "IDLE"))
                self.display_state = state
                if kind == "pulse":
                    ttl_ms = max(250, int(message.get("ttlMs", 1800)))
                    resume_state = str(message.get("resumeState", self.model.base_state))
                    self.model.apply_pulse(
                        state,
                        ttl_ms,
                        self._now_ms(),
                        resume_state,
                        message.get("resumeActivity"),
                        complete_clip=not self.reduced_motion,
                    )
                    ttl_ms = self.model.pulse_deadline_ms - self._now_ms()
                    self._show_status(
                        str(message.get("resumeMessage", self.LABELS.get(resume_state, resume_state))),
                        str(message.get("resumeDetail", "")),
                        resume_state,
                        None if resume_state in {"THINKING", "WORKING", "WAITING", "ERROR"} else ttl_ms + 2200,
                    )
                    self._show_overlay(
                        str(message.get("message", self.LABELS.get(state, state))),
                        str(message.get("detail", "")),
                        state,
                        ttl_ms,
                    )
                    if state in {"SUCCESS", "ERROR"}:
                        self._notify_alert(state)
                else:
                    activity = None if self.reduced_motion else message.get("activity")
                    self.model.apply_state(state, activity)
                    self.display_state = self.model.pulse_state or state
                    if self.model.pulse_state is None:
                        self._clear_overlay()
                    persistent = state in {"THINKING", "WORKING", "WAITING", "ERROR"}
                    self._show_status(
                        str(message.get("message", self.LABELS.get(state, state))),
                        str(message.get("detail", "")),
                        state,
                        None if persistent else 4200,
                    )
                if previous_base_state != self.model.base_state and not self.reduced_motion:
                    self._schedule_micro()
            self._sync_frame_transition(previous_frame, previous_clip)
            self._sync_bubble_size()
            self.update()
            if snapshot_path is not None and not self.snapshot_saved:
                QTimer.singleShot(180, self._save_snapshot)

        def _set_reduced_motion(self, enabled: bool) -> None:
            self.reduced_motion = enabled
            self.animation_timer.setInterval(self._animation_interval_ms())
            if enabled:
                self.micro_timer.stop()
                if not self.dragging:
                    self.model.clear_overlay()
            else:
                self._schedule_micro()

        def _apply_config(self, message: dict[str, Any]) -> None:
            """Apply a live CONFIG message without restarting the window."""
            idle_title = message.get("idleTitle")
            if isinstance(idle_title, str) and idle_title.strip():
                previous_title = self.idle_title
                self.idle_title = idle_title.strip()[:40]
                if self.status_state == "IDLE" and self.status_message in {previous_title, "我在这儿等新任务哦"}:
                    self.status_message = self.idle_title
            if isinstance(message.get("openUrl"), str):
                self.webui_url = message["openUrl"]
            if isinstance(message.get("openLabel"), str):
                self.open_label = message["openLabel"]
            scale = message.get("scale")
            if isinstance(scale, (int, float)) and not isinstance(scale, bool):
                self.scale = min(1.4, max(0.55, float(scale)))
            bubble_scale = message.get("bubbleScale")
            if isinstance(bubble_scale, (int, float)) and not isinstance(bubble_scale, bool):
                self.bubble_scale = min(1.2, max(0.8, float(bubble_scale)))
            reduced_motion = message.get("reducedMotion")
            if isinstance(reduced_motion, bool) and reduced_motion != self.reduced_motion:
                self._set_reduced_motion(reduced_motion)
            sound_enabled = message.get("soundEnabled")
            if isinstance(sound_enabled, bool):
                self.sound_enabled = sound_enabled
            sound_pack = message.get("soundPack")
            if sound_pack in {"original", "clean", "video", "custom"}:
                self.sound_pack = sound_pack
            revision = message.get("customSoundRevision")
            if isinstance(revision, int) and revision != self.custom_sound_revision:
                self.custom_sound_revision = revision
                for effect in self.sound_effects.values():
                    effect.stop()
                    effect.deleteLater()
                self.sound_effects.clear()
            sound_states = message.get("soundStates")
            if isinstance(sound_states, list):
                self.sound_states = {state for state in sound_states if isinstance(state, str)}
            activity_level = message.get("activityLevel")
            if activity_level in {"quiet", "normal", "lively"}:
                self.activity_level = activity_level
                if not self.reduced_motion:
                    self._schedule_micro()
            bubble_mode = message.get("bubbleMode")
            if bubble_mode in {"always", "hidden", "custom"}:
                self.bubble_mode = bubble_mode
            bubble_states = message.get("bubbleStates")
            if isinstance(bubble_states, list):
                self.bubble_states = [str(state) for state in bubble_states if isinstance(state, str)]
            market_watch_enabled = message.get("marketWatchEnabled")
            if isinstance(market_watch_enabled, bool):
                self.market_watch_enabled = market_watch_enabled
            raw_symbols = message.get("marketWatchSymbols")
            if isinstance(raw_symbols, list):
                symbols = list(dict.fromkeys(
                    str(item).strip().upper() for item in raw_symbols
                    if isinstance(item, str) and 5 <= len(item) <= 20 and item.strip().isalnum()
                ))[:5]
                if symbols:
                    self.market_watch_symbols = symbols
            selected = message.get("marketWatchSymbol")
            if isinstance(selected, str) and selected in self.market_watch_symbols:
                if selected != self.market_watch_symbol:
                    self.market_watch_history.clear()
                self.market_watch_symbol = selected
            interval = message.get("marketWatchInterval")
            if interval in {"1m", "15m", "1h", "4h"}:
                if interval != self.market_watch_interval:
                    self.market_watch_history.clear()
                self.market_watch_interval = interval
            self._sync_bubble_size()
            self._save_layout()

        def _apply_glove(self, closed: bool) -> None:
            """Closed fist while the button is held, open hand otherwise.

            Sets the cursor directly so feedback is immediate instead of
            waiting for the next WM_SETCURSOR pass.
            """
            self.glove.pressed = closed
            handle = self.glove.handle_for(closed)
            if handle:
                set_native_cursor(handle)

        def enterEvent(self, event: Any) -> None:
            self._apply_glove(False)
            super().enterEvent(event)

        def leaveEvent(self, event: Any) -> None:
            self.glove.pressed = False
            reset_native_cursor()
            super().leaveEvent(event)

        def _animation_interval_ms(self) -> int:
            if self.reduced_motion:
                return 40
            # Sub-frame poll: a once-per-frame timer turns one early delivery into a whole-frame hitch.
            return max(8, min(20, round(self.model.active_clip.frame_ms / 3)))

        def _rearm_animation_interval(self) -> None:
            wanted = self._animation_interval_ms()
            if self.animation_timer.interval() != wanted:
                self.animation_timer.setInterval(wanted)

        def _pixmap(self, frame: str) -> QPixmap:
            cached = self.decoded_frames.get(frame)
            if cached is not None:
                self.decoded_frames.move_to_end(frame)
                return cached
            pixmap = QPixmap()
            if not pixmap.loadFromData(self.frame_sources[frame]):
                raise RuntimeError(f"Unable to load BigFish frame: {frame}")
            self.decoded_frames[frame] = pixmap
            while len(self.decoded_frames) > DECODED_FRAME_CACHE:
                self.decoded_frames.popitem(last=False)
            return pixmap

        def _tick(self) -> None:
            now_ms = self._now_ms()
            elapsed_ms = max(0, now_ms - self.last_tick_ms)
            self.last_tick_ms = now_ms
            had_pulse = self.model.pulse_state is not None
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            model_elapsed = 0 if self.reduced_motion else elapsed_ms
            self.model.advance(model_elapsed, now_ms)
            self._sync_frame_transition(previous_frame, previous_clip)
            if had_pulse and self.model.pulse_state is None:
                self.display_state = self.model.base_state
            if self.overlay_deadline_ms is not None and now_ms >= self.overlay_deadline_ms:
                self._clear_overlay()
            self._rearm_animation_interval()
            self.update()

        def _play_idle_micro(self) -> None:
            if self.chess_mode or self.watching_video or self.novel_reader.active():
                self._schedule_micro()
                return
            if self.reduced_motion:
                return
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            self.model.play_idle_micro(random.randrange(max(1, len(self.model.idle_micro_clips))))
            self._sync_frame_transition(previous_frame, previous_clip)
            self.update()
            self._schedule_micro()

        def _sync_frame_transition(
            self,
            previous_frame: str,
            previous_clip: str,
            *,
            allow_fade: bool = True,
        ) -> None:
            current_frame = self.model.frame
            if current_frame == previous_frame:
                return
            # Preserve an in-progress clip fade while its new video advances.
            if allow_fade and previous_clip == self.model.active_clip_name:
                return
            duration = crossfade_duration(previous_clip, self.model.active_clip_name) if allow_fade else None
            if duration is None:
                self.fade_from_pixmap = None
                return
            self.fade_from_pixmap = (
                self._pixmap(previous_frame) if previous_frame in self.frame_sources else None
            )
            self.fade_started = time.monotonic()
            self.fade_duration = duration

        def _play_model_overlay(
            self,
            clip_name: str,
            *,
            allow_fade: bool = True,
            repaint: bool = True,
        ) -> bool:
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            if not self.model.play_overlay(clip_name):
                return False
            self._sync_frame_transition(previous_frame, previous_clip, allow_fade=allow_fade)
            if repaint:
                self.update()
            return True

        def _begin_drag(self) -> None:
            if self.dragging:
                return
            self.dragging = True
            self.micro_timer.stop()
            played = self._play_model_overlay(flight_clip(self.drag_direction), allow_fade=False, repaint=False)
            if not played:
                self.animation_timer.stop()
                return
            clip = self.model.active_clip
            if self.reduced_motion or not clip.loop:
                self.animation_timer.stop()
            else:
                self.last_tick_ms = self._now_ms()
                self.animation_timer.start(self._animation_interval_ms())

        def _finish_drag(self) -> None:
            if not self.dragging:
                return
            now_ms = self._now_ms()
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            # Expire an underlying pulse before revealing it after a long drag.
            self.model.advance(0, now_ms)
            if self.reduced_motion or not self.model.play_overlay("dragging_release"):
                self.model.clear_overlay()
            self._sync_frame_transition(previous_frame, previous_clip, allow_fade=False)
            self.dragging = False
            self.last_tick_ms = now_ms
            self.animation_timer.start(self._animation_interval_ms())
            if not self.reduced_motion:
                self._schedule_micro()

        def _update_drag_direction(self, point: QPoint) -> None:
            if self.drag_direction_anchor is None:
                self.drag_direction_anchor = point
                return
            dx = point.x() - self.drag_direction_anchor.x()
            dy = point.y() - self.drag_direction_anchor.y()
            if dx * dx + dy * dy < 64:
                return
            heading = flight_heading(dx, dy, self.drag_direction)
            self.drag_direction_anchor = point
            if heading == self.drag_direction:
                return
            self.drag_direction = heading
            clip = flight_clip(heading)
            if clip != self.model.active_clip_name:
                self._play_model_overlay(clip, allow_fade=False)
            else:
                self.update()

        def _schedule_micro(self) -> None:
            if self.reduced_motion:
                self.micro_timer.stop()
                return
            lower, upper = self.model.idle_micro_interval(self.activity_level)
            self.micro_timer.start(self.model.overlay_remaining_ms + random.randint(lower, upper))

        def _bubble_visible(self) -> bool:
            if self.chess_mode or self.watching_video:
                return False
            if self.voice_mode != "off" or "dictation" in self.voice_pending.values():
                return True
            if self.task_files:
                return True
            if self.bubble_mode == "hidden":
                return False
            if self.market_watch_enabled:
                return True
            if self.bubble_mode == "always":
                return True
            if len(self.tasks) >= 2:
                return any(task.get("state") in self.bubble_states for task in self.tasks)
            state = self.overlay_state or self.status_state or self.model.base_state or "IDLE"
            return state in self.bubble_states

        def _sync_bubble_size(self) -> None:
            old_size = (self.width(), self.height())
            self._apply_window_size()
            if (self.width(), self.height()) != old_size:
                self._move_to_pet(self.pet_x, self.pet_y)
            else:
                self._position_task_input()

        def _apply_window_size(self) -> None:
            pet_width = round(int(manifest["maxFrameWidth"]) * self.scale)
            pet_height = round(int(manifest["maxFrameHeight"]) * self.scale)
            if self._bubble_visible():
                bubble_width = round(420 * self.bubble_scale)
                bubble_height = self._card_height()
                self.setFixedSize(max(pet_width + 50, bubble_width + 28), pet_height + bubble_height + 34)
            else:
                self.setFixedSize(pet_width + 50, pet_height + 26)

        def _screen_geometry_at(self, x: int, y: int):
            screen = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
            if screen is None:
                return None
            return screen.availableGeometry()

        def _pet_size(self) -> tuple[int, int]:
            return (
                round(int(manifest["maxFrameWidth"]) * self.scale),
                round(int(manifest["maxFrameHeight"]) * self.scale),
            )

        def _move_to_pet(self, pet_x: int, pet_y: int) -> None:
            """Resize or move the container around the character's anchor."""
            geometry = self._screen_geometry_at(pet_x, pet_y)
            screen = (geometry.x(), geometry.y(), geometry.width(), geometry.height()) if geometry is not None else None
            window_x, window_y, self.pet_x, self.pet_y = position_window(
                (pet_x, pet_y), self._pet_size(), (self.width(), self.height()), screen,
                self._card_height() if self._bubble_visible() else 0,
            )
            self.move(window_x, window_y)
            self._position_task_input()
            self.update()

        def _pet_offset_x(self, pet_width: int) -> int:
            return min(max(self.pet_x - self.x(), 0), self.width() - pet_width)

        def _pet_rect(self) -> tuple[int, int, int, int]:
            pet_width, pet_height = self._pet_size()
            offset_y = min(max(self.pet_y - self.y(), 0), self.height() - pet_height)
            return self._pet_offset_x(pet_width), offset_y, pet_width, pet_height

        def _bubble_rect(self) -> tuple[int, int, int, int]:
            card_width = round(420 * self.bubble_scale)
            card_height = self._card_height()
            pet_width, _ = self._pet_size()
            pet_center_x = self._pet_offset_x(pet_width) + pet_width // 2
            margin = 14
            card_x = pet_center_x - card_width // 2
            min_x = margin
            max_x = self.width() - card_width - margin
            if max_x < min_x:
                max_x = min_x
            card_x = min(max(card_x, min_x), max_x)
            _, pet_y, _, pet_height = self._pet_rect()
            card_y = bubble_top(pet_y, pet_height, card_height, self.height())
            return card_x, card_y, card_width, card_height

        def _task_input_height(self) -> int:
            minimum = round(50 * self.bubble_scale)
            maximum = round(140 * self.bubble_scale)
            if self.task_input is None:
                return minimum
            content = math.ceil(self.task_input.document().size().height()) + round(8 * self.bubble_scale)
            return min(maximum, max(minimum, content))

        def _file_list_height(self) -> int:
            # The list font and icons use physical pixels; leave room for three
            # complete rows even when the surrounding bubble is scaled down.
            return 8 + 34 * min(len(self.task_files), 3)

        def _file_extra_height(self) -> int:
            if not self.task_files:
                return 0
            return self._file_list_height() + round(32 * self.bubble_scale)

        def _composer_height(self) -> int:
            scale = self.bubble_scale
            button_size = max(30, round(36 * scale))
            return (
                self._task_input_height() + self._file_extra_height()
                + round(9 * scale) + 8 + button_size + round(8 * scale)
            )

        def _composer_rect(self) -> tuple[int, int, int, int]:
            card_x, card_y, card_width, card_height = self._bubble_rect()
            scale = self.bubble_scale
            margin = round(16 * scale)
            footer = round(28 * scale)
            height = self._composer_height()
            bottom = card_y + card_height - footer - round(12 * scale)
            return card_x + margin, bottom - height, card_width - 2 * margin, height

        def _position_task_input(self) -> None:
            if self.task_input is None or self.task_inline_send is None or self.task_file_button is None or self.voice_record_button is None or self.voice_call_button is None:
                return
            visible = self._bubble_visible()
            if hasattr(self, "chess_button"):
                self.chess_button.setVisible(visible)
            if hasattr(self, "video_button"):
                self.video_button.setVisible(visible)
            self.task_input.setVisible(visible)
            self.task_inline_send.setVisible(visible)
            self.voice_record_button.setVisible(visible)
            self.voice_call_button.setVisible(visible)
            self.task_file_button.setVisible(visible)
            if self.task_file_label is not None:
                self.task_file_label.setVisible(visible and bool(self.task_files))
            if self.task_file_list is not None:
                self.task_file_list.setVisible(visible and bool(self.task_files))
            if self.call_transcript is not None:
                self.call_transcript.setVisible(visible and self.voice_mode == "call")
            if not visible:
                return
            card_x, card_y, card_width, card_height = self._bubble_rect()
            composer_x, composer_y, composer_width, composer_height = self._composer_rect()
            scale = self.bubble_scale
            if hasattr(self, "chess_button"):
                self.chess_button.setGeometry(
                    card_x + card_width - round(90 * scale), card_y + card_height - round(31 * scale),
                    round(74 * scale), max(20, round(23 * scale)),
                )
            if hasattr(self, "video_button"):
                self.video_button.setGeometry(
                    card_x + card_width - round(170 * scale), card_y + card_height - round(31 * scale),
                    round(74 * scale), max(20, round(23 * scale)),
                )
            margin = round(16 * scale)
            button_size = max(30, round(36 * scale))
            gap = max(6, round(8 * scale))
            input_height = self._task_input_height()
            input_top = composer_y + self._file_extra_height() + round(9 * scale)
            if self.task_files and self.task_file_label is not None and self.task_file_list is not None:
                self.task_file_label.setGeometry(
                    composer_x + round(11 * scale), composer_y + round(7 * scale),
                    composer_width - round(22 * scale), round(18 * scale),
                )
                self.task_file_list.setGeometry(
                    composer_x + round(10 * scale), composer_y + round(27 * scale),
                    composer_width - round(20 * scale), self._file_list_height(),
                )
            if self.call_transcript is not None and self.voice_mode == "call":
                transcript_top = card_y + round(116 * scale)
                transcript_bottom = composer_y - round(8 * scale)
                self.call_transcript.setGeometry(
                    card_x + margin, transcript_top,
                    card_width - 2 * margin, max(round(40 * scale), transcript_bottom - transcript_top),
                )
            self.task_input.setGeometry(
                composer_x + round(12 * scale), input_top,
                composer_width - round(24 * scale), input_height,
            )
            icon_size = QSize(max(18, round(20 * scale)), max(18, round(20 * scale)))
            for button in (self.voice_record_button, self.voice_call_button, self.task_file_button, self.task_inline_send):
                button.setIconSize(icon_size)
            row_y = composer_y + composer_height - button_size - round(8 * scale)
            send_x = composer_x + composer_width - button_size - round(8 * scale)
            call_x = send_x - gap - button_size
            record_x = call_x - gap - button_size
            self.task_file_button.setGeometry(composer_x + round(8 * scale), row_y, max(30, round(40 * scale)), button_size)
            self.voice_record_button.setGeometry(record_x, row_y, button_size, button_size)
            self.voice_call_button.setGeometry(call_x, row_y, button_size, button_size)
            self.task_inline_send.setGeometry(send_x, row_y, button_size, button_size)

        def _restore_visible_position(self) -> None:
            pet_width, pet_height = self._pet_size()
            top_offset = self.height() - pet_height - 8
            center_offset = (self.width() - pet_width) // 2
            saved_pet_x = self.layout.get("petX")
            saved_pet_y = self.layout.get("petY")
            if isinstance(saved_pet_x, int) and isinstance(saved_pet_y, int):
                pet_x, pet_y = saved_pet_x, saved_pet_y
            else:
                saved_x = self.layout.get("x")
                saved_y = self.layout.get("y")
                if isinstance(saved_x, int) and isinstance(saved_y, int):
                    # Legacy layouts stored the window position.  Recreate the
                    # pet position that the old centered layout would have had.
                    pet_x = saved_x + center_offset
                    pet_y = saved_y + top_offset
                else:
                    geometry = self._screen_geometry_at(self.x() + self.width() // 2, self.y() + self.height() // 2)
                    if geometry is None:
                        return
                    pet_x = geometry.right() - pet_width - 24
                    pet_y = geometry.bottom() - pet_height - 24
            self._move_to_pet(pet_x, pet_y)

        def _save_layout(self) -> None:
            self.layout = {
                "version": 1,
                "x": self.x(),
                "y": self.y(),
                "petX": self.pet_x,
                "petY": self.pet_y,
                "scale": self.scale,
                "bubbleScale": self.bubble_scale,
                "reducedMotion": self.reduced_motion,
                "bubbleMode": self.bubble_mode,
                "bubbleStates": self.bubble_states,
            }
            try:
                save_layout(self.layout_path, self.layout)
            except OSError as error:
                print(f"Unable to save BigFish layout: {error}", file=sys.stderr)

        def _save_snapshot(self) -> None:
            if snapshot_path is None or self.snapshot_saved:
                return
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.snapshot_saved = self.grab().save(str(snapshot_path), "PNG")

        def _show_status(self, message: str, detail: str, state: str, ttl_ms: int | None) -> None:
            self.status_message = message
            self.status_detail = detail
            self.status_state = state
            self.status_deadline_ms = None if ttl_ms is None else self._now_ms() + ttl_ms

        def _show_overlay(self, message: str, detail: str, state: str, ttl_ms: int) -> None:
            self.overlay_message = message
            self.overlay_detail = detail or self.status_detail
            self.overlay_state = state
            self.overlay_deadline_ms = self._now_ms() + ttl_ms

        def _clear_overlay(self) -> None:
            self.overlay_message = ""
            self.overlay_detail = ""
            self.overlay_state = None
            self.overlay_deadline_ms = None

        @staticmethod
        def _now_ms() -> int:
            return int(time.monotonic() * 1000)

        def _current_card(self) -> tuple[str, str, str] | None:
            now_ms = self._now_ms()
            if self.overlay_state == "ERROR" and self.overlay_message and (
                self.overlay_deadline_ms is None or now_ms < self.overlay_deadline_ms
            ):
                return self.overlay_message, self.overlay_detail, "ERROR"
            if self.file_drop_hover:
                return "小弟来接文件", "松开鼠标，添加到任务附件", "IDLE"
            if self.voice_mode != "off":
                seconds = max(0, (now_ms - (self.voice_started_ms or now_ms)) // 1000)
                elapsed = f"{seconds // 60:02}:{seconds % 60:02}"
                phase = self._voice_phase(now_ms)
                if self.voice_mode == "call":
                    return "语音通话中", f"通话 {elapsed} · {phase}", "VOICE_CALL"
                return "正在录音", f"录音 {elapsed} · {phase}", "VOICE_RECORD"
            if "dictation" in self.voice_pending.values():
                seconds = max(0, (now_ms - self.voice_pending_started_ms) // 1000)
                return "正在识别录音", f"已等待 {seconds} 秒 · 识别完成后填入输入框", "THINKING"
            if self.overlay_message and (
                self.overlay_deadline_ms is None or now_ms < self.overlay_deadline_ms
            ):
                return self.overlay_message, self.overlay_detail, self.overlay_state or self.status_state
            if self.status_message and (
                self.status_deadline_ms is None or now_ms < self.status_deadline_ms
            ):
                return self.status_message, self.status_detail, self.status_state
            if self.balance_summary:
                return self.idle_title, "DSH · 等待下一次任务", "IDLE"
            if self.task_files:
                return self.idle_title, f"已选 {len(self.task_files)} 个文件，等待发送", "IDLE"
            if self._bubble_visible():
                return self.idle_title, "DSH · 等待下一次任务", "IDLE"
            return None

        def _voice_phase(self, now_ms: int) -> str:
            if self.voice_mode == "call" and self.tts is not None and self.tts.state() == QTextToSpeech.State.Speaking:
                return "正在朗读回复"
            if not self.voice_ready:
                return "加载识别模型"
            if now_ms - self.voice_last_speech_ms < 700:
                return "正在说话"
            if any(mode == self.voice_mode for mode in self.voice_pending.values()):
                return "正在识别"
            if self.voice_mode == "call" and (self.pending_task_id is not None or self.voice_tasks):
                return "正在发送任务"
            return "正在聆听"

        def _live_voice_level(self, now_ms: int) -> float:
            return self.voice_level * max(0.0, 1.0 - (now_ms - self.voice_level_at_ms) / 420.0)

        def _draw_voice_visualizer(self, painter: QPainter, card_x: int, card_y: int, card_width: int, s: float) -> None:
            now_ms = self._now_ms()
            activity = self._live_voice_level(now_ms)
            speaking = self.voice_mode == "call" and self.tts is not None and self.tts.state() == QTextToSpeech.State.Speaking
            if speaking:
                activity = 0.5
            foreground = QColor("#EA4655" if self.voice_mode == "dictation" else "#3478F6")
            background = QColor("#E5EAF0")
            bar_count = 44
            gap = 2.0 * s
            bar_width = 4.0 * s
            total_width = bar_count * bar_width + (bar_count - 1) * gap
            start_x = card_x + (card_width - total_width) / 2
            center_y = card_y + 77 * s
            phase = now_ms / 1000.0
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            for index in range(bar_count):
                center_falloff = 1.0 - abs(index - (bar_count - 1) / 2) / ((bar_count - 1) / 2)
                variation = 0.25 + 0.75 * abs(math.sin(index * 1.27 + phase * (5.5 if speaking else 1.8)))
                contour = (0.25 + 0.75 * center_falloff) * variation
                height = (3.0 + 21.0 * activity * contour) * s
                painter.setBrush(foreground if activity * contour > 0.07 else background)
                painter.drawRoundedRect(
                    QRectF(start_x + index * (bar_width + gap), center_y - height / 2, bar_width, height),
                    1.8 * s, 1.8 * s,
                )
            painter.restore()

            if not self.voice_ready:
                caption = "本地模型启动中，首次可能需要约 1 分钟"
            elif self.voice_last_text and now_ms - self.voice_last_text_at_ms < 7000:
                caption = ("上一句：" if self.voice_mode == "call" else "已识别：") + self.voice_last_text
            else:
                caption = "停顿后自动发送" if self.voice_mode == "call" else "停顿后识别文字，点“停录”结束"
            caption_font = QFont("Microsoft YaHei UI")
            caption_font.setPointSizeF(8.5 * max(1.0, s))
            painter.setFont(caption_font)
            painter.setPen(QColor("#858B95"))
            width = card_width - round(48 * s)
            painter.drawText(
                card_x + round(24 * s), card_y + round(91 * s), width, round(18 * s),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                QFontMetrics(caption_font).elidedText(caption, Qt.TextElideMode.ElideRight, width),
            )

        @staticmethod
        def _status_colors(state: str) -> tuple[QColor, QColor]:
            return {
                "VOICE_RECORD": (QColor("#FFE5E7"), QColor("#EA4655")),
                "VOICE_CALL": (QColor("#DDEBFF"), QColor("#3478F6")),
                "SUCCESS": (QColor("#D9F7E4"), QColor("#12B85A")),
                "ERROR": (QColor("#FDE3E3"), QColor("#E5484D")),
                "WAITING": (QColor("#FFF0CE"), QColor("#D88A00")),
                "THINKING": (QColor("#E2ECFF"), QColor("#4C78E8")),
                "WORKING": (QColor("#DDEBFF"), QColor("#3478F6")),
                "DISCONNECTED": (QColor("#ECEEF1"), QColor("#7B818A")),
            }.get(state, (QColor("#ECEEF1"), QColor("#747A84")))

        def _draw_status_icon(self, painter: QPainter, state: str, center_x: int, center_y: int) -> None:
            background, foreground = self._status_colors(state)
            radius = 23
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
            pen = QPen(foreground, 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if state == "SUCCESS":
                painter.drawLine(center_x - 10, center_y, center_x - 3, center_y + 8)
                painter.drawLine(center_x - 3, center_y + 8, center_x + 12, center_y - 10)
            elif state == "ERROR":
                painter.drawLine(center_x - 8, center_y - 8, center_x + 8, center_y + 8)
                painter.drawLine(center_x + 8, center_y - 8, center_x - 8, center_y + 8)
            elif state == "WAITING":
                painter.drawLine(center_x, center_y - 10, center_x, center_y + 3)
                painter.setBrush(foreground)
                painter.drawEllipse(center_x - 2, center_y + 9, 4, 4)
            elif state in {"THINKING", "WORKING"}:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                for offset in (-9, 0, 9):
                    painter.drawEllipse(center_x + offset - 3, center_y - 3, 6, 6)
            elif state == "VOICE_RECORD":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                painter.drawEllipse(center_x - 8, center_y - 8, 16, 16)
            elif state == "VOICE_CALL":
                painter.drawArc(center_x - 12, center_y - 12, 24, 24, 35 * 16, 110 * 16)
                painter.drawArc(center_x - 7, center_y - 7, 14, 14, 215 * 16, 110 * 16)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                painter.drawEllipse(center_x - 5, center_y - 5, 10, 10)

        def _card_height(self) -> int:
            scale = self.bubble_scale
            footer = round(28 * scale)
            if len(self.tasks) >= 2 and self.voice_mode == "off":
                rows = min(len(self.tasks), 3)
                top = round((58 + rows * 26) * scale)
            else:
                voice_extra = 44 if self.voice_mode != "off" else 0
                call_history_extra = 150 if self.voice_mode == "call" else 0
                top = round((84 + voice_extra + call_history_extra) * scale)
            if self.market_watch_enabled and self.voice_mode == "off":
                top += round(72 * scale)
            return top + self._composer_height() + footer + round(12 * scale)

        def _market_watch_top(self, card_y: int) -> int:
            scale = self.bubble_scale
            if len(self.tasks) >= 2 and self.voice_mode == "off":
                base = 58 + min(len(self.tasks), 3) * 26
            else:
                base = 84
            return card_y + round((base + 4) * scale)

        def _draw_market_watch(self, painter: QPainter, card_x: int, card_y: int, card_width: int, s: float) -> None:
            x = card_x + round(16 * s)
            y = self._market_watch_top(card_y)
            width = card_width - round(32 * s)
            height = round(64 * s)
            painter.save()
            painter.setPen(QPen(QColor("#E1E8F0"), 1))
            painter.setBrush(QColor("#F7FAFD"))
            painter.drawRoundedRect(QRectF(x, y, width, height), round(12 * s), round(12 * s))

            title_font = QFont("Microsoft YaHei UI")
            title_font.setPointSizeF(8.0 * max(1.0, s))
            detail_font = QFont("Microsoft YaHei UI")
            detail_font.setPointSizeF(9.0 * max(1.0, s))
            price_font = QFont("Microsoft YaHei UI")
            price_font.setPointSizeF(13.0 * max(1.0, s))
            price_font.setWeight(QFont.Weight.DemiBold)
            symbol_label = self.market_watch_symbol.replace("USDT", "/USDT")
            title = f"盯盘  ·  {symbol_label}  ·  {self.market_watch_interval}"
            painter.setFont(title_font)
            painter.setPen(QColor("#677385"))
            title_width = width - round(92 * s)
            painter.drawText(x + round(10 * s), y + round(4 * s), title_width, round(17 * s),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(title_font).elidedText(title, Qt.TextElideMode.ElideRight, title_width))
            endpoint_short = {
                "stream.binance.com:9443": "9443",
                "stream.binance.com:443": "443",
                "data-stream.binance.vision": "vision",
            }.get(self.market_watch_endpoint, "备用")
            status_text = {
                "connected": "● 实时", "connecting": f"连接 {endpoint_short}",
                "reconnecting": f"重试 {endpoint_short}",
                "unavailable": "不可用", "disabled": "已关闭",
            }.get(self.market_watch_status, "等待中")
            status_color = QColor("#16A05D") if self.market_watch_status == "connected" else QColor("#C1842A") if self.market_watch_status == "reconnecting" else QColor("#8A929E")
            painter.setPen(status_color)
            painter.drawText(x + width - round(80 * s), y + round(4 * s), round(70 * s), round(17 * s),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, status_text)

            quote = self.market_watch_quotes.get(self.market_watch_symbol)
            if not isinstance(quote, dict):
                status_labels = {
                    "connecting": f"正在连接 {self.market_watch_endpoint}…",
                    "reconnecting": f"连接失败，正在尝试 {self.market_watch_endpoint}…",
                    "unavailable": "当前运行环境不支持 WebSocket", "disabled": "行情已关闭",
                }
                painter.setFont(detail_font)
                painter.setPen(QColor("#8A929E"))
                status_label = QFontMetrics(detail_font).elidedText(
                    status_labels.get(self.market_watch_status, "等待行情数据…"),
                    Qt.TextElideMode.ElideRight,
                    width - round(20 * s),
                )
                painter.drawText(x + round(10 * s), y + round(25 * s), width - round(20 * s), round(28 * s),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 status_label)
                painter.restore()
                return

            price = quote.get("price")
            change = quote.get("changePercent")
            if isinstance(price, (int, float)) and not isinstance(price, bool):
                price_text = f"{price:,.8g}"
            else:
                price_text = "--"
            if isinstance(change, (int, float)) and not isinstance(change, bool):
                change_text = f"{change:+.2f}%"
                color = QColor("#16A05D") if change > 0 else QColor("#D94B4B") if change < 0 else QColor("#697586")
            else:
                change_text = "--"
                color = QColor("#697586")
            painter.setFont(price_font)
            painter.setPen(QColor("#273142"))
            painter.drawText(x + round(10 * s), y + round(23 * s), round(155 * s), round(27 * s),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, price_text)
            painter.setFont(detail_font)
            painter.setPen(color)
            painter.drawText(x + round(164 * s), y + round(24 * s), round(82 * s), round(25 * s),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, change_text)

            history = list(self.market_watch_history)
            if len(history) > 1:
                chart_x = x + round(255 * s)
                chart_y = y + round(30 * s)
                chart_width = max(round(42 * s), width - round(267 * s))
                chart_height = round(22 * s)
                low, high = min(history), max(history)
                span = high - low or max(abs(high) * 0.0001, 1e-8)
                path = QPainterPath()
                for index, point in enumerate(history):
                    px = chart_x + chart_width * index / (len(history) - 1)
                    py = chart_y + chart_height * (1 - (point - low) / span)
                    if index == 0:
                        path.moveTo(px, py)
                    else:
                        path.lineTo(px, py)
                painter.setPen(QPen(color, max(1.5, 2 * s), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(path)
            painter.restore()

        def _draw_card_background(
            self,
            painter: QPainter,
            card_x: int,
            card_y: int,
            card_width: int,
            card_height: int,
            corner_radius: int,
            s: float,
        ) -> None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(17, 24, 39, 13))
            painter.drawRoundedRect(
                card_x + 1, card_y + round(13 * s), card_width - 2, card_height,
                corner_radius, corner_radius,
            )
            painter.setBrush(QColor(17, 24, 39, 18))
            painter.drawRoundedRect(
                card_x, card_y + round(7 * s), card_width, card_height,
                corner_radius, corner_radius,
            )
            painter.setPen(QPen(QColor(218, 221, 226, 205), 1))
            painter.setBrush(QColor(252, 252, 253, 248))
            painter.drawRoundedRect(
                card_x, card_y, card_width, card_height,
                corner_radius, corner_radius,
            )

        def _draw_multi_task_card(
            self,
            painter: QPainter,
            card_x: int,
            card_y: int,
            card_width: int,
            card_height: int,
            s: float,
        ) -> None:
            title_font = QFont("Microsoft YaHei UI")
            title_font.setPointSizeF(11.0 * max(1.0, s))
            title_font.setWeight(QFont.Weight.DemiBold)
            detail_font = QFont("Microsoft YaHei UI")
            detail_font.setPointSizeF(9.0 * max(1.0, s))
            text_x = card_x + round(16 * s)
            text_width = max(40, card_width - round(32 * s))
            painter.setFont(title_font)
            painter.setPen(QColor("#25282D"))
            title = f"{len(self.tasks)} 个任务进行中"
            painter.drawText(
                text_x,
                card_y + round(10 * s),
                text_width,
                max(12, round(22 * s)),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                QFontMetrics(title_font).elidedText(title, Qt.TextElideMode.ElideRight, text_width),
            )
            painter.setFont(detail_font)
            for index, task in enumerate(self.tasks[:3]):
                row_y = card_y + round((36 + index * 24) * s)
                state = str(task.get("state", "IDLE"))
                state_label = self.LABELS.get(state, state)
                label = task.get("project") or task.get("task") or task.get("message") or state_label
                line = f"{state_label} · {label}"
                _, foreground = self._status_colors(state)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                painter.drawEllipse(text_x, row_y + round(4 * s), round(8 * s), round(8 * s))
                painter.setPen(QColor("#747981"))
                painter.drawText(
                    text_x + round(14 * s),
                    row_y,
                    text_width - round(14 * s),
                    max(12, round(20 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    QFontMetrics(detail_font).elidedText(line, Qt.TextElideMode.ElideRight, text_width - round(14 * s)),
                )
            if len(self.tasks) > 3:
                more = f"还有 {len(self.tasks) - 3} 个任务…"
                painter.setPen(QColor("#9AA0A6"))
                painter.drawText(
                    text_x + round(14 * s),
                    card_y + round((36 + 3 * 24) * s),
                    text_width,
                    max(12, round(20 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    more,
                )

        SOUND_FILES = {"SUCCESS": "success.wav", "ERROR": "error.wav", "APPROVAL": "approval.wav"}

        def _play_chess_sound(self, sound: str) -> None:
            if not self.sound_enabled or sound not in {"move", "capture", "check", "win", "loss"}:
                return
            sound_path = bundle_root() / "assets" / "sounds" / "xiangqi" / f"{sound}.wav"
            if not sound_path.is_file():
                return
            played = False
            if sys.platform == "win32":
                try:
                    import winsound

                    winsound.PlaySound(
                        str(sound_path),
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                    )
                    played = True
                except (ImportError, OSError, RuntimeError):
                    pass
            elif QSoundEffect is not None:
                try:
                    effect = self.sound_effects.get(sound_path)
                    if effect is None:
                        effect = QSoundEffect(self)
                        effect.setSource(QUrl.fromLocalFile(str(sound_path)))
                        effect.setVolume(0.75)
                        self.sound_effects[sound_path] = effect
                    effect.play()
                    played = True
                except (OSError, RuntimeError):
                    pass
            if not played:
                try:
                    QApplication.beep()
                except Exception:
                    pass

        def _notify_alert(self, state: str) -> None:
            if self.sound_enabled and state in self.sound_states:
                sound_name = self.SOUND_FILES.get(state, "error.wav")
                sound_dir = bundle_root() / "assets" / "sounds"
                if self.sound_pack == "custom":
                    sound_path = self.custom_sounds_dir / sound_name
                    if not sound_path.is_file():
                        sound_path = sound_dir / sound_name
                elif self.sound_pack in {"clean", "video"}:
                    sound_path = sound_dir / self.sound_pack / sound_name
                else:
                    sound_path = sound_dir / sound_name
                played = False
                if sys.platform == "win32":
                    try:
                        import winsound

                        winsound.PlaySound(
                            str(sound_path),
                            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                        )
                        played = True
                    except (ImportError, OSError, RuntimeError):
                        pass
                elif QSoundEffect is not None:
                    try:
                        effect = self.sound_effects.get(sound_path)
                        if effect is None:
                            effect = QSoundEffect(self)
                            effect.setSource(QUrl.fromLocalFile(str(sound_path)))
                            self.sound_effects[sound_path] = effect
                        effect.play()
                        played = True
                    except (OSError, RuntimeError):
                        pass
                if not played:
                    try:
                        QApplication.beep()
                    except Exception:
                        pass

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # 平滑缩放：放大/缩小时插值，避免锯齿和模糊
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            card = self._current_card() if self._bubble_visible() else None
            card_x, card_y, card_width, card_height = self._bubble_rect()
            s = self.bubble_scale
            corner_radius = round(30 * s)

            if len(self.tasks) >= 2 and self.voice_mode == "off" and self._bubble_visible():
                self._draw_card_background(painter, card_x, card_y, card_width, card_height, corner_radius, s)
                self._draw_multi_task_card(painter, card_x, card_y, card_width, card_height, s)
            elif card:
                title, detail, card_state = card
                self._draw_card_background(painter, card_x, card_y, card_width, card_height, corner_radius, s)
                icon_center_x = card_x + card_width - round(39 * s)
                icon_center_y = card_y + round(42 * s)
                painter.save()
                painter.translate(icon_center_x, icon_center_y)
                painter.scale(s, s)
                painter.translate(-icon_center_x, -icon_center_y)
                self._draw_status_icon(painter, card_state, icon_center_x, icon_center_y)
                painter.restore()

                text_x = card_x + round(24 * s)
                text_width = max(40, card_width - round(102 * s))
                title_font = QFont("Microsoft YaHei UI")
                title_font.setPointSizeF(11.0 * max(1.0, s))
                title_font.setWeight(QFont.Weight.DemiBold)
                detail_font = QFont("Microsoft YaHei UI")
                detail_font.setPointSizeF(9.0 * max(1.0, s))
                painter.setFont(title_font)
                painter.setPen(QColor("#25282D"))
                title_text = QFontMetrics(title_font).elidedText(
                    title,
                    Qt.TextElideMode.ElideRight,
                    text_width,
                )
                painter.drawText(
                    text_x,
                    card_y + round(15 * s),
                    text_width,
                    max(12, round(27 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    title_text,
                )
                painter.setFont(detail_font)
                painter.setPen(QColor("#747981"))
                detail_text = QFontMetrics(detail_font).elidedText(
                    detail,
                    Qt.TextElideMode.ElideRight,
                    text_width,
                )
                painter.drawText(
                    text_x,
                    card_y + round(43 * s),
                    text_width,
                    max(12, round(24 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    detail_text,
                )
                if card_state in {"VOICE_RECORD", "VOICE_CALL"}:
                    self._draw_voice_visualizer(painter, card_x, card_y, card_width, s)

            if self.market_watch_enabled and self.voice_mode == "off" and self._bubble_visible():
                self._draw_market_watch(painter, card_x, card_y, card_width, s)

            if self._bubble_visible():
                composer_x, composer_y, composer_width, composer_height = self._composer_rect()
                radius = round(18 * s)
                painter.save()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(30, 45, 70, 12))
                painter.drawRoundedRect(
                    QRectF(composer_x, composer_y + 2, composer_width, composer_height), radius, radius,
                )
                painter.setPen(QPen(QColor("#DFE3EA"), 1))
                painter.setBrush(QColor("#FFFFFF"))
                painter.drawRoundedRect(
                    QRectF(composer_x + 0.5, composer_y + 0.5, composer_width - 1, composer_height - 1),
                    radius, radius,
                )
                painter.restore()

            if self.balance_summary and self._bubble_visible():
                balance_font = QFont("Microsoft YaHei UI")
                balance_font.setPointSizeF(9.0 * max(1.0, s))
                painter.setFont(balance_font)
                painter.setPen(QColor("#53616F"))
                text_width = card_width - round(194 * s)
                text = QFontMetrics(balance_font).elidedText(self.balance_summary, Qt.TextElideMode.ElideRight, text_width)
                painter.drawText(card_x + round(16 * s), card_y + card_height - round(31 * s),
                                 text_width, round(23 * s), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

            visual_clip = self.model.active_clip_name
            visual_frame = self.model.frame
            file_reaction = self.file_drop_hover or self.model.overlay_clip_name == "file_catch"
            if not self.dragging and not file_reaction and self.chess_mode:
                visual_clip = "thinking" if self.xiangqi_mode.busy else "idle"
                visual_frame = manifest["clips"][visual_clip]["frames"][0]
            elif not self.dragging and not file_reaction and self.watching_video:
                visual_clip = "idle"
                visual_frame = manifest["clips"][visual_clip]["frames"][0]
            elif not self.dragging and not file_reaction and self.voice_mode != "off":
                visual_clip = "voice_calling" if self.voice_mode == "call" else "voice_recording"
                visual_frame = manifest["clips"][visual_clip]["frames"][0]
            elif not self.dragging and not file_reaction and "dictation" in self.voice_pending.values():
                visual_clip = "thinking"
                visual_frame = manifest["clips"][visual_clip]["frames"][0]
            pixmap = self._pixmap(visual_frame)
            if self.motion_clip_name != visual_clip:
                self.motion_clip_name = visual_clip
                self.motion_started_ms = self._now_ms()
            offset_x, offset_y, angle, scale_x, scale_y = motion_pose(
                self.motion_profiles,
                visual_clip,
                self._now_ms() - self.motion_started_ms,
                self.reduced_motion,
            )
            if self.watching_video and not self.dragging and not file_reaction and not self.reduced_motion:
                angle -= 2
                if self.video_watcher.animating:
                    angle += math.sin(time.monotonic() * 1.2) * 1.2
                    offset_y += math.sin(time.monotonic() * 1.1)

            fade_alpha = 1.0
            if visual_clip == self.model.active_clip_name and self.fade_from_pixmap is not None and not self.fade_from_pixmap.isNull():
                fade_elapsed = time.monotonic() - self.fade_started
                if fade_elapsed < self.fade_duration:
                    fade_alpha = min(1.0, (fade_elapsed / self.fade_duration) ** 0.7)
                else:
                    self.fade_from_pixmap = None

            def draw_pet(pix: QPixmap, alpha: float) -> None:
                x, y, pw, ph = self._pet_rect()
                painter.save()
                painter.setOpacity(alpha)
                painter.translate(x + pw / 2 + offset_x * self.scale, y + ph / 2 + offset_y * self.scale)
                flight_bank = {
                    "right": 18, "up_right": -2, "down_right": 32,
                    "left": -18, "up_left": 2, "down_left": -32,
                }.get(self.drag_direction, 0) if self.dragging else 0
                painter.rotate(angle + flight_bank)
                mirrored = self.dragging and self.drag_direction in {"left", "up_left", "down_left"}
                painter.scale(-scale_x if mirrored else scale_x, scale_y)
                painter.drawPixmap(QRectF(-pw / 2, -ph / 2, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
                painter.restore()

            if fade_alpha < 1.0 and self.fade_from_pixmap is not None:
                # Keep the old frame opaque underneath so the pet never flashes transparent.
                draw_pet(self.fade_from_pixmap, 1.0)
            draw_pet(pixmap, fade_alpha)
            self.novel_reader.draw_book(painter, self._pet_rect(), self.reduced_motion)
            self.xiangqi_mode.draw_prop(painter, self._pet_rect())
            self.video_watcher.draw_prop(painter, self._pet_rect())

        def mousePressEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton and self._pet_hit(event.position().x(), event.position().y()):
                self._apply_glove(True)
                self.drag_origin = event.globalPosition().toPoint()
                self.drag_direction_anchor = self.drag_origin
                self.drag_direction = "down"
                self.pet_origin = QPoint(self.pet_x, self.pet_y)
                self.dragging = False

        def dragEnterEvent(self, event: Any) -> None:
            self._accept_file_drag(event)

        def dragMoveEvent(self, event: Any) -> None:
            self._accept_file_drag(event)

        def dragLeaveEvent(self, event: Any) -> None:
            self._end_file_hover()
            event.accept()

        def dropEvent(self, event: Any) -> None:
            self._drop_files(event)

        def mouseMoveEvent(self, event: QMouseEvent) -> None:
            if self.drag_origin is not None and self.pet_origin is not None:
                point = event.globalPosition().toPoint()
                if not self.dragging and (point - self.drag_origin).manhattanLength() > 5:
                    initial = point - self.drag_origin
                    self.drag_direction = flight_heading(initial.x(), initial.y())
                    self.drag_direction_anchor = point
                    self._begin_drag()
                elif self.dragging:
                    self._update_drag_direction(point)
                delta = point - self.drag_origin
                self._move_to_pet(self.pet_origin.x() + delta.x(), self.pet_origin.y() + delta.y())

        def mouseReleaseEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                if self.dragging:
                    self._finish_drag()
                    self._move_to_pet(self.pet_x, self.pet_y)
                    self._save_layout()
                elif self.drag_origin is not None:
                    self._play_click_interaction(event.position().x(), event.position().y())
            self.drag_origin = None
            self.drag_direction_anchor = None
            self.pet_origin = None
            self.dragging = False
            # The button state is authoritative: restore the open hand if the
            # pointer is still over the pet, or the default arrow otherwise.
            self.glove.pressed = False
            if self.rect().contains(event.position().toPoint()):
                self._apply_glove(False)
            else:
                reset_native_cursor()

        def _pet_hit(self, x: float, y: float) -> bool:
            pet_x, pet_y, pet_width, pet_height = self._pet_rect()
            if not (pet_x <= x < pet_x + pet_width and pet_y <= y < pet_y + pet_height):
                return False
            image = self._pixmap(self.model.frame).toImage()
            source_x = min(image.width() - 1, int((x - pet_x) * image.width() / pet_width))
            source_y = min(image.height() - 1, int((y - pet_y) * image.height() / pet_height))
            return image.pixelColor(source_x, source_y).alpha() > 16

        def _play_click_interaction(self, x: float, y: float) -> None:
            if not self._pet_hit(x, y):
                return
            pet_x, pet_y, pet_width, pet_height = self._pet_rect()
            relative_x = x - pet_x
            relative_y = y - pet_y
            if relative_y < pet_height * 0.61:
                self._play_interaction("head_pat", "摸摸也不能让我少干活哦~")
            elif relative_x < pet_width * 0.44 or relative_x > pet_width * 0.56:
                self._play_interaction("tail", "尾巴不是进度条啦！")
            else:
                self._play_interaction("poke", "戳我干嘛，任务还在跑呢")

        def _play_interaction(self, clip_name: str, message: str) -> None:
            previous_frame, previous_clip = self.model.frame, self.model.active_clip_name
            if not self.model.play_interaction(clip_name, self._now_ms()):
                return
            self._sync_frame_transition(previous_frame, previous_clip)
            if self.reduced_motion:
                def settle() -> None:
                    if self.model.overlay_clip_name != clip_name:
                        return
                    old_frame, old_clip = self.model.frame, self.model.active_clip_name
                    self.model.clear_overlay()
                    self._sync_frame_transition(old_frame, old_clip, allow_fade=False)
                    self.update()

                QTimer.singleShot(self.model.active_clip.frame_ms, settle)
            self._show_overlay(message, self.status_detail, self.status_state, 1800)
            self._schedule_micro()
            self.update()

        def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton and self._pet_hit(event.position().x(), event.position().y()):
                self._play_interaction("head_pat", "好啦好啦，知道你喜欢我~")

        def contextMenuEvent(self, event: Any) -> None:
            menu = QMenu(self)
            if self.watching_video:
                menu.addAction("继续看视频", self.video_watcher.enter)
                menu.addAction("收起视频", self.video_watcher.leave)
            else:
                menu.addAction("看视频", self.video_watcher.enter)
            menu.addSeparator()
            if self.chess_mode:
                menu.addAction("继续下象棋", self.xiangqi_mode.enter)
                menu.addAction("收起棋盘", self.xiangqi_mode.leave)
            else:
                menu.addAction("下象棋", self.xiangqi_mode.enter)
            menu.addSeparator()
            self.novel_reader.add_menu(menu)
            menu.addSeparator()
            record_action = menu.addAction("停止录音" if self.voice_mode == "dictation" else "语音录入…")
            call_action = menu.addAction("挂断语音通话" if self.voice_mode == "call" else "开始语音通话")
            menu.addSeparator()
            size_menu = menu.addMenu("大小")
            size_actions = {}
            for label, scale in (("迷你", 0.6), ("小", 0.8), ("标准", 1.0), ("大", 1.25)):
                action = size_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(abs(self.scale - scale) < 0.05)
                size_actions[action] = scale
            bubble_size_menu = menu.addMenu("气泡大小")
            bubble_size_actions = {}
            for label, bubble_scale in (("小", 0.8), ("标准", 1.0), ("大", 1.2)):
                action = bubble_size_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(abs(self.bubble_scale - bubble_scale) < 0.05)
                bubble_size_actions[action] = bubble_scale
            reduced_action = menu.addAction("减少动态")
            reduced_action.setCheckable(True)
            reduced_action.setChecked(self.reduced_motion)
            sound_menu = menu.addMenu("声音")
            sound_enabled_action = sound_menu.addAction("播放提示音")
            sound_enabled_action.setCheckable(True)
            sound_enabled_action.setChecked(self.sound_enabled)
            sound_menu.addSeparator()
            sound_pack_actions = {}
            for label, pack in (("提示音 C", "video"), ("提示音 B", "clean"), ("提示音 A", "original"), ("自定义", "custom")):
                action = sound_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(self.sound_pack == pack)
                sound_pack_actions[action] = pack
            market_menu = menu.addMenu("炒币盯盘")
            market_enabled_action = market_menu.addAction("启用实时行情卡片")
            market_enabled_action.setCheckable(True)
            market_enabled_action.setChecked(self.market_watch_enabled)
            market_menu.addSeparator()
            market_symbol_menu = market_menu.addMenu("桌宠展示币种")
            market_symbol_actions = {}
            for symbol in self.market_watch_symbols:
                action = market_symbol_menu.addAction(symbol.replace("USDT", "/USDT"))
                action.setCheckable(True)
                action.setChecked(self.market_watch_symbol == symbol)
                market_symbol_actions[action] = symbol
            market_interval_menu = market_menu.addMenu("涨跌周期")
            market_interval_actions = {}
            for label, interval in (("1 分钟", "1m"), ("15 分钟", "15m"), ("1 小时", "1h"), ("4 小时", "4h")):
                action = market_interval_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(self.market_watch_interval == interval)
                market_interval_actions[action] = interval
            open_webui_action = menu.addAction(self.open_label)
            menu.addSeparator()
            hide_action = menu.addAction("本次隐藏")
            exit_action = menu.addAction("本次关闭")
            selected = menu.exec(event.globalPos())
            if selected == record_action:
                QTimer.singleShot(0, lambda: self._toggle_voice("dictation"))
            elif selected == call_action:
                QTimer.singleShot(0, lambda: self._toggle_voice("call"))
            elif selected in size_actions:
                self.scale = size_actions[selected]
                self._apply_window_size()
                self._move_to_pet(self.pet_x, self.pet_y)
                self._save_layout()
                emit_reply("settings", scale=self.scale)
            elif selected in bubble_size_actions:
                self.bubble_scale = bubble_size_actions[selected]
                self._apply_window_size()
                self._move_to_pet(self.pet_x, self.pet_y)
                self._save_layout()
                emit_reply("settings", bubbleScale=self.bubble_scale)
            elif selected == reduced_action:
                self._set_reduced_motion(reduced_action.isChecked())
                self._save_layout()
                emit_reply("settings", reducedMotion=self.reduced_motion)
                self.update()
            elif selected == sound_enabled_action:
                self.sound_enabled = sound_enabled_action.isChecked()
                emit_reply("settings", soundEnabled=self.sound_enabled)
            elif selected in sound_pack_actions:
                self.sound_pack = sound_pack_actions[selected]
                emit_reply("settings", soundPack=self.sound_pack)
            elif selected == market_enabled_action:
                self.market_watch_enabled = market_enabled_action.isChecked()
                emit_reply("settings", marketWatchEnabled=self.market_watch_enabled)
                self._sync_bubble_size()
                self.update()
            elif selected in market_symbol_actions:
                self.market_watch_symbol = market_symbol_actions[selected]
                self.market_watch_history.clear()
                emit_reply("settings", marketWatchSymbol=self.market_watch_symbol)
                self.update()
            elif selected in market_interval_actions:
                self.market_watch_interval = market_interval_actions[selected]
                self.market_watch_history.clear()
                emit_reply("settings", marketWatchInterval=self.market_watch_interval)
                self.update()
            elif selected == open_webui_action:
                self._open_client()
            elif selected == hide_action:
                self.hide()
            elif selected == exit_action:
                self._save_layout()
                emit_reply("closed", reason="user")
                QApplication.quit()

        def _open_task_dialog(self) -> None:
            if self.task_dialog is not None:
                self.task_dialog.raise_()
                self.task_dialog.activateWindow()
                return
            # A child of the frameless Tool window can be hidden behind its
            # owner on Windows. Keep a Python reference and use a real window.
            dialog = FileTaskDialog(self)
            dialog.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
            dialog.setWindowTitle("给大哥派任务")
            dialog.setFont(QFont("Microsoft YaHei UI", 10))
            dialog.setStyleSheet(
                "QDialog { background: #FFFFFF; }"
                "QLabel { color: #242A35; }"
                "QTextEdit { background: #F8FAFD; color: #242A35; border: 1px solid #CBD5E1;"
                " border-radius: 8px; padding: 8px; selection-background-color: #3478F6; }"
                "QTextEdit:focus { border: 1px solid #3478F6; }"
                "QPushButton { min-width: 76px; padding: 7px 10px; border: 1px solid #CBD5E1;"
                " border-radius: 7px; background: #FFFFFF; color: #242A35; }"
                "QPushButton:hover { background: #F1F5F9; }"
                "QPushButton#sendTask { background: #3478F6; border-color: #3478F6; color: #FFFFFF; }"
                "QPushButton#sendTask:hover { background: #2563DB; }"
                "QPushButton#sendTask:disabled { background: #93B4F8; border-color: #93B4F8; }"
            )
            dialog.setMinimumWidth(400)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(20, 18, 20, 18)
            layout.setSpacing(12)
            heading = QLabel("发送到当前 DSH 对话")
            heading.setStyleSheet("font-size: 16px; font-weight: 600;")
            layout.addWidget(heading)
            editor = QTextEdit(dialog)
            editor.setAcceptDrops(False)
            editor.setPlaceholderText("输入想让大哥完成的任务…")
            editor.setMinimumHeight(110)
            editor.setPlainText(self.pending_task_text)
            layout.addWidget(editor)
            file_label = QLabel("已选文件 · 双击移除", dialog)
            file_label.setStyleSheet("color: #596579; font-weight: 600;")
            layout.addWidget(file_label)
            file_list = self._make_file_list(dialog)
            file_list.setFixedHeight(98)
            layout.addWidget(file_list)
            feedback = QLabel("正在发送上一条任务…" if self.pending_task_id else "任务会在当前对话中排队执行")
            feedback.setTextFormat(Qt.TextFormat.PlainText)
            feedback.setWordWrap(True)
            feedback.setStyleSheet("color: #667085;")
            layout.addWidget(feedback)
            buttons = QHBoxLayout()
            file_button = QPushButton("添加文件", dialog)
            file_button.setIcon(action_icon("file", "#245EB2"))
            file_button.clicked.connect(self._choose_task_files)
            file_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            file_button.customContextMenuRequested.connect(lambda _pos: self._show_task_files_menu(file_button))
            buttons.addWidget(file_button)
            buttons.addStretch()
            cancel_button = QPushButton("取消", dialog)
            send_button = QPushButton("发送任务", dialog)
            send_button.setObjectName("sendTask")
            send_button.setDefault(True)
            send_button.setEnabled(self.pending_task_id is None)
            buttons.addWidget(cancel_button)
            buttons.addWidget(send_button)
            layout.addLayout(buttons)
            cancel_button.clicked.connect(dialog.reject)

            def submit() -> None:
                text = editor.toPlainText().strip()
                if (not text and not self.task_files) or len(text) > 4000:
                    feedback.setText("请输入任务或选择文件，最多 4000 字")
                    return
                if self._send_task(text, self.task_files):
                    feedback.setText("正在发送到当前对话…")

            send_button.clicked.connect(submit)

            def closed(_result: int) -> None:
                if self.task_dialog is dialog:
                    self.task_dialog = None
                    self.task_editor = None
                    self.task_feedback = None
                    self.task_send_button = None
                    self.task_dialog_file_button = None
                    self.task_dialog_file_label = None
                    self.task_dialog_file_list = None

            dialog.finished.connect(closed)
            self.task_dialog = dialog
            self.task_editor = editor
            self.task_feedback = feedback
            self.task_send_button = send_button
            self.task_dialog_file_button = file_button
            self.task_dialog_file_label = file_label
            self.task_dialog_file_list = file_list
            self._refresh_task_files()
            dialog.adjustSize()
            geometry = self._screen_geometry_at(self.x(), self.y())
            if geometry is not None:
                x = geometry.left() + (geometry.width() - dialog.width()) // 2
                y = geometry.top() + (geometry.height() - dialog.height()) // 2
                dialog.move(x, y)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            editor.setFocus()

        def _toggle_voice(self, mode: str) -> None:
            if self.watching_video:
                self.video_watcher.leave()
            if self.chess_mode:
                self.xiangqi_mode.leave()
            if self.voice_mode == mode:
                self._stop_voice()
                return
            if self.voice_mode != "off":
                self._stop_voice()
            if QAudioSource is None or QMediaDevices is None or QAudioFormat is None:
                self._show_overlay("录音不可用", "当前桌宠未包含 Qt 录音组件", "ERROR", 4500)
                return
            input_device = QMediaDevices.defaultAudioInput()
            if input_device.isNull():
                self._show_overlay("没有找到麦克风", "请连接麦克风并检查系统录音权限", "ERROR", 4500)
                return
            audio_format = QAudioFormat()
            audio_format.setSampleRate(16000)
            audio_format.setChannelCount(1)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not input_device.isFormatSupported(audio_format):
                audio_format = input_device.preferredFormat()
            sample_format = audio_format.sampleFormat().name
            try:
                self.voice_converter = Pcm16MonoConverter(
                    audio_format.sampleRate(),
                    audio_format.channelCount(),
                    sample_format,
                )
            except ValueError:
                self._show_overlay("麦克风格式不支持", f"暂不支持设备格式 {sample_format}", "ERROR", 4500)
                return
            self.voice_segmenter.reset()
            self.voice_source = QAudioSource(input_device, audio_format, self)
            self.voice_source.setBufferSize(16000)
            self.voice_source.stateChanged.connect(self._on_voice_source_state)
            self.voice_device = self.voice_source.start()
            if self.voice_device is None:
                self.voice_source.deleteLater()
                self.voice_source = None
                self.voice_converter = None
                self._show_overlay("无法开始录音", "请检查麦克风权限或是否被其他程序占用", "ERROR", 4500)
                return
            self.voice_device.readyRead.connect(self._consume_voice_audio)
            self.voice_mode = mode
            self.voice_started_ms = self._now_ms()
            self.voice_ready = False
            self.voice_level = 0.0
            self.voice_level_at_ms = 0
            self.voice_last_speech_ms = 0
            self.voice_last_text = ""
            self.voice_last_text_at_ms = 0
            if mode == "call":
                self.call_history.clear()
                if self.call_transcript is not None:
                    self.call_transcript.clear()
            self._refresh_voice_buttons()
            emit_reply("voice_mode", active=mode == "call", mode=mode)
            self._sync_bubble_size()
            self.update()

        def _on_voice_source_state(self, state: Any) -> None:
            if self.voice_mode == "off" or self.voice_source is None:
                return
            if state == QAudio.State.StoppedState and self.voice_source.error() != QAudio.Error.NoError:
                self._show_overlay("录音已中断", "请检查麦克风权限或设备连接", "ERROR", 4500)
                QTimer.singleShot(0, lambda: self._stop_voice(finalize=False))

        def _refresh_voice_buttons(self) -> None:
            if self.voice_record_button is not None:
                recording = self.voice_mode == "dictation"
                self.voice_record_button.setIcon(action_icon("stop" if recording else "record", "#FFFFFF" if recording else "#245EB2"))
                self.voice_record_button.setToolTip("停止录音" if recording else "录音转文字")
                self.voice_record_button.setAccessibleName("停止录音" if recording else "录音转文字")
                self.voice_record_button.setStyleSheet(
                    "QPushButton { color: white; background: #EA4655; border: 0; border-radius: 15px; }"
                    "QPushButton:hover { background: #D73343; }"
                    if self.voice_mode == "dictation" else
                    "QPushButton { color: #245EB2; background: transparent; border: 0; border-radius: 15px; }"
                    "QPushButton:hover { background: #EEF3FC; }"
                )
            if self.voice_call_button is not None:
                calling = self.voice_mode == "call"
                self.voice_call_button.setIcon(action_icon("hangup" if calling else "call", "#FFFFFF" if calling else "#245EB2"))
                self.voice_call_button.setToolTip("挂断通话" if calling else "开始语音通话")
                self.voice_call_button.setAccessibleName("挂断通话" if calling else "开始语音通话")
                self.voice_call_button.setStyleSheet(
                    "QPushButton { color: white; background: #3478F6; border: 0; border-radius: 15px; }"
                    "QPushButton:hover { background: #2563DB; }"
                    if self.voice_mode == "call" else
                    "QPushButton { color: #245EB2; background: transparent; border: 0; border-radius: 15px; }"
                    "QPushButton:hover { background: #EEF3FC; }"
                )

        def _consume_voice_audio(self) -> None:
            if self.voice_device is None or self.voice_mode == "off":
                return
            data = bytes(self.voice_device.readAll())
            if not data:
                return
            if self.voice_converter is not None:
                data = self.voice_converter.feed(data)
            if not data:
                return
            segments = self.voice_segmenter.feed(data)
            if self.voice_segmenter.meter_frames:
                now_ms = self._now_ms()
                self.voice_level = min(1.0, math.sqrt(self.voice_segmenter.recent_energy / 4000.0))
                self.voice_level_at_ms = now_ms
                if self.voice_segmenter.recent_talking:
                    self.voice_last_speech_ms = now_ms
                self.update()
            for segment in segments:
                self._transcribe_voice_segment(segment, self.voice_mode)

        def _stop_voice(self, finalize: bool = True) -> None:
            if self.voice_mode == "off":
                return
            mode = self.voice_mode
            self._consume_voice_audio()
            if finalize:
                segment = self.voice_segmenter.flush()
                if segment is not None:
                    self._transcribe_voice_segment(segment, mode)
            else:
                self.voice_segmenter.reset()
            self.voice_mode = "off"
            self.voice_started_ms = None
            self.voice_ready = False
            self.voice_level = 0.0
            self.voice_last_text = ""
            if self.voice_source is not None:
                self.voice_source.stop()
                self.voice_source.deleteLater()
            self.voice_source = None
            self.voice_device = None
            self.voice_converter = None
            if mode == "call":
                self.speech_queue.clear()
                if self.tts is not None:
                    self.tts.stop()
                self._preserve_voice_queue()
            emit_reply("voice_mode", active=False, mode="off")
            self._refresh_voice_buttons()
            self._sync_bubble_size()
            self.update()

        def _transcribe_voice_segment(self, segment: bytes, mode: str) -> None:
            if len(segment) < VoiceSegmenter.FRAME_BYTES * 2:
                return
            voice_dir = Path(os.environ.get("DSH_DAFEIYU_VOICE_DIR") or Path(tempfile.gettempdir()) / "dsh-dafeiyu-voice")
            voice_dir.mkdir(parents=True, exist_ok=True)
            request_id = uuid.uuid4().hex
            filename = voice_dir / f"{request_id}.wav"
            with wave.open(str(filename), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(segment)
            if not self.voice_pending:
                self.voice_pending_started_ms = self._now_ms()
            self.voice_pending[request_id] = mode
            emit_reply("voice_transcribe", requestId=request_id, path=str(filename))

        def _apply_voice_transcript(self, message: dict[str, Any]) -> None:
            mode = self.voice_pending.pop(str(message.get("requestId", "")), None)
            if mode is None:
                return
            if not self.voice_pending:
                self.voice_pending_started_ms = 0
            if message.get("error"):
                self._show_overlay("语音识别失败", str(message["error"])[:100], "ERROR", 5500)
                if self.voice_mode != "off":
                    self._stop_voice(finalize=False)
                self._sync_bubble_size()
                self.update()
                return
            text = str(message.get("text", "")).strip()
            if not text:
                self._show_overlay("未识别到文字", "请靠近麦克风、说完整一句后重试", "ERROR", 4500)
                self._sync_bubble_size()
                self.update()
                return
            if mode == self.voice_mode:
                self.voice_last_text = text[:120]
                self.voice_last_text_at_ms = self._now_ms()
            if mode == "dictation":
                if self._append_voice_text(text) and self.voice_mode == "off":
                    self._show_overlay("录音已转文字", "请检查输入框并发送", "SUCCESS", 3500)
            elif self.voice_mode != "call":
                self._append_voice_text(text)
            else:
                if mode == "call" and self.voice_mode == "call":
                    self._append_call_message("我", text)
                for offset in range(0, len(text), 4000):
                    self.voice_tasks.append(text[offset:offset + 4000])
                self._dispatch_voice_tasks()
            self._sync_bubble_size()
            self.update()

        def _append_voice_text(self, text: str) -> bool:
            if self.task_input is None:
                return False
            current = self.task_input.toPlainText().strip()
            combined = f"{current}\n{text}" if current else text
            if len(combined) > 4000:
                self._show_overlay("输入已满", "请先发送已有文字，再继续录音", "ERROR", 4500)
                if self.voice_mode != "off":
                    self._stop_voice(finalize=False)
                return False
            self.task_input.setPlainText(combined)
            self.task_input.moveCursor(QTextCursor.MoveOperation.End)
            self.task_input.ensureCursorVisible()
            return True

        def _append_call_message(self, speaker: str, text: str) -> None:
            content = text.strip()
            if not content or self.call_transcript is None:
                return
            if len(content) > 12000:
                content = content[:12000] + "…（内容过长，已截断）"
            self.call_history.append((speaker, content))
            self.call_transcript.setPlainText("\n\n".join(f"{name}：{line}" for name, line in self.call_history))
            scrollbar = self.call_transcript.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        def _preserve_voice_queue(self) -> None:
            while self.voice_tasks:
                if not self._append_voice_text(self.voice_tasks[0]):
                    break
                self.voice_tasks.popleft()

        def _apply_voice_status(self, message: dict[str, Any]) -> None:
            if self.voice_mode == "off":
                return
            if message.get("ready") is True:
                self.voice_ready = True
                self._show_overlay("语音识别已就绪", "可以继续说话", "IDLE", 2200)
            else:
                self._show_overlay("语音识别不可用", str(message.get("error", "请检查本地模型设置"))[:100], "ERROR", 5500)
                self._stop_voice(finalize=False)
            self.update()

        def _dispatch_voice_tasks(self) -> None:
            if self.voice_mode != "call" or self.pending_task_id is not None or not self.voice_tasks:
                return
            text = self.voice_tasks.popleft()
            if not self._send_task(text):
                self.voice_tasks.appendleft(text)

        def _speak_reply(self, text: str) -> None:
            if self.voice_mode != "call" or not text.strip():
                return
            if self.tts is None or not self.tts.availableVoices():
                self._show_overlay("朗读不可用", "系统没有可用的语音", "ERROR", 4500)
                return
            if self.tts.state() != QTextToSpeech.State.Ready:
                self.speech_queue.append(text)
                return
            if self.voice_source is not None:
                self.voice_source.suspend()
            self.voice_segmenter.reset()
            if self.voice_converter is not None:
                self.voice_converter.reset()
            self.tts.say(text)

        def _on_speech_state(self, state: Any) -> None:
            if self.tts is None:
                return
            if state == QTextToSpeech.State.Error:
                self.speech_queue.clear()
                self._show_overlay("朗读失败", "请检查系统语音和输出设备", "ERROR", 4500)
                if self.voice_mode == "call" and self.voice_source is not None:
                    self.voice_source.resume()
                return
            if state != QTextToSpeech.State.Ready:
                return
            if self.voice_mode == "call" and self.speech_queue:
                self._speak_reply(self.speech_queue.popleft())
                return
            if self.voice_mode == "call" and self.voice_source is not None:
                if self.voice_device is not None:
                    self.voice_device.readAll()
                self.voice_segmenter.reset()
                if self.voice_converter is not None:
                    self.voice_converter.reset()
                self.voice_source.resume()

        def _refresh_task_files(self) -> None:
            count = len(self.task_files)
            tooltip = "\n".join(Path(path).name for path in self.task_files) if count else "选择文件作为当前对话的附件；右键可移除"
            if self.task_file_button is not None:
                self.task_file_button.setText(str(count) if count else "")
                self.task_file_button.setToolTip(tooltip)
                self.task_file_button.setAccessibleName(f"已选 {count} 个文件，点击添加" if count else "选择文件")
            if self.task_dialog_file_button is not None:
                self.task_dialog_file_button.setText(f"添加文件 ({count})" if count else "添加文件")
                self.task_dialog_file_button.setToolTip(tooltip)
            for label in (self.task_file_label, self.task_dialog_file_label):
                if label is not None:
                    label.setText(f"已选文件（{count}） · 双击移除")
                    label.setVisible(bool(count))
            for view in (self.task_file_list, self.task_dialog_file_list):
                if view is None:
                    continue
                view.clear()
                for path in self.task_files:
                    item = QListWidgetItem(action_icon("file", "#6984AB"), Path(path).name)
                    item.setData(Qt.ItemDataRole.UserRole, path)
                    item.setToolTip(path)
                    view.addItem(item)
                view.setVisible(bool(count))
            if self.task_input is not None:
                self.task_input.setPlaceholderText("给小弟安排任务…")

        def _choose_task_files(self) -> None:
            parent = self.task_dialog if self.task_dialog is not None else self
            paths, _filter = QFileDialog.getOpenFileNames(parent, "选择发送到当前 DSH 对话的文件")
            if not paths:
                return
            self._add_task_files(paths)

        @staticmethod
        def _local_drop_files(mime: Any) -> list[str]:
            if not mime.hasUrls():
                return []
            urls = mime.urls()
            if not urls or len(urls) > 8:
                return []
            paths: list[str] = []
            for url in urls:
                if not url.isLocalFile():
                    return []
                path = url.toLocalFile()
                if not path or not Path(path).is_file():
                    return []
                paths.append(path)
            return list(dict.fromkeys(paths))

        def _can_accept_file_drop(self, paths: list[str]) -> bool:
            return bool(paths) and self.pending_task_id is None and len(set(self.task_files).union(paths)) <= 8

        def _accept_file_drag(self, event: Any) -> None:
            paths = self._local_drop_files(event.mimeData())
            if not self._can_accept_file_drop(paths):
                event.ignore()
                self._end_file_hover()
                return
            event.acceptProposedAction()
            if self.file_drop_hover:
                return
            self.file_drop_hover = True
            self.micro_timer.stop()
            self._play_model_overlay("file_hover", allow_fade=False)
            self.last_tick_ms = self._now_ms()
            self.animation_timer.start(self._animation_interval_ms())
            self.update()

        def _end_file_hover(self) -> None:
            if not self.file_drop_hover:
                return
            self.file_drop_hover = False
            if self.model.overlay_clip_name == "file_hover":
                previous_frame, previous_clip = self.model.frame, self.model.active_clip_name
                self.model.clear_overlay()
                self._sync_frame_transition(previous_frame, previous_clip, allow_fade=False)
            if not self.reduced_motion:
                self._schedule_micro()
            self.update()

        def _animate_file_catch(self) -> None:
            self.file_drop_hover = False
            if self.model.overlay_clip_name == "file_catch":
                self.model.clear_overlay()
            self._play_model_overlay("file_catch", allow_fade=False)
            self.last_tick_ms = self._now_ms()
            self.animation_timer.start(self._animation_interval_ms())
            if self.reduced_motion:
                clip_duration = len(self.model.active_clip.frames) * self.model.active_clip.frame_ms
                def settle() -> None:
                    if self.model.overlay_clip_name == "file_catch":
                        self.model.clear_overlay()
                        self.update()
                QTimer.singleShot(clip_duration, settle)
            else:
                self._schedule_micro()

        def _add_task_files(self, paths: list[str]) -> bool:
            selected = list(dict.fromkeys([*self.task_files, *paths]))
            if self.pending_task_id is not None or len(selected) > 8:
                self._show_overlay("文件过多", "一次最多选择 8 个文件", "ERROR", 3500)
                self.update()
                return False
            self.task_files = selected
            self._refresh_task_files()
            self._sync_bubble_size()
            if self.task_feedback is not None:
                self.task_feedback.setText(f"已选 {len(self.task_files)} 个文件，可直接发送或补充任务")
            self._show_overlay("文件接住啦", f"已选 {len(self.task_files)} 个附件 · 可直接发送或补充任务", "SUCCESS", 3000)
            self._animate_file_catch()
            self.update()
            return True

        def _drop_files(self, event: Any) -> None:
            paths = self._local_drop_files(event.mimeData())
            if not self._can_accept_file_drop(paths):
                event.ignore()
                self._end_file_hover()
                return
            event.acceptProposedAction()
            if not self._add_task_files(paths):
                event.ignore()
                self._end_file_hover()

        def _show_task_files_menu(self, button: QPushButton | None = None) -> None:
            anchor = button or self.task_file_button
            if not self.task_files or anchor is None:
                return
            menu = QMenu(self)
            for path in self.task_files:
                action = menu.addAction(f"移除 {Path(path).name}")
                action.triggered.connect(lambda _checked=False, selected=path: self._remove_task_file(selected))
            menu.addSeparator()
            menu.addAction("清空文件", self._clear_task_files)
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

        def _remove_task_file(self, path: str) -> None:
            self.task_files = [selected for selected in self.task_files if Path(selected) != Path(path)]
            self._refresh_task_files()
            self._sync_bubble_size()

        def _clear_task_files(self) -> None:
            self.task_files.clear()
            self._refresh_task_files()
            self._sync_bubble_size()

        def _send_task(self, text: str, files: list[str] | None = None) -> bool:
            text = text.strip()
            files = list(files or [])
            if self.pending_task_id is not None or (not text and not files) or len(text) > 4000 or len(files) > 8:
                return False
            self.pending_task_id = uuid.uuid4().hex
            self.pending_task_text = text
            self.pending_task_files = files
            if self.task_input is not None:
                self.task_input.setEnabled(False)
            if self.task_inline_send is not None:
                self.task_inline_send.setEnabled(False)
            if self.task_file_button is not None:
                self.task_file_button.setEnabled(False)
            if self.task_dialog_file_button is not None:
                self.task_dialog_file_button.setEnabled(False)
            if self.task_send_button is not None:
                self.task_send_button.setEnabled(False)
            emit_reply("submit_task", requestId=self.pending_task_id, text=text, files=files)
            return True

        def _submit_inline_task(self) -> None:
            if self.task_input is None:
                return
            text = self.task_input.toPlainText().strip()
            if not text and not self.task_files:
                self.task_input.setFocus()
                return
            self._send_task(text, self.task_files)

        def _finish_task_submission(self, message: dict[str, Any]) -> None:
            if message.get("requestId") != self.pending_task_id:
                return
            sent_text = self.pending_task_text
            sent_files = self.pending_task_files
            self.pending_task_id = None
            accepted = message.get("accepted") is True
            if self.task_input is not None:
                self.task_input.setEnabled(True)
            if self.task_inline_send is not None:
                self.task_inline_send.setEnabled(True)
            if self.task_file_button is not None:
                self.task_file_button.setEnabled(True)
            if self.task_dialog_file_button is not None:
                self.task_dialog_file_button.setEnabled(True)
            if accepted:
                self.pending_task_text = ""
                self.pending_task_files = []
                if sent_files:
                    self.task_files = [path for path in self.task_files if path not in sent_files]
                    self._refresh_task_files()
                if self.task_input is not None and self.task_input.toPlainText().strip() == sent_text:
                    self.task_input.clear()
                if self.task_dialog is not None:
                    self.task_dialog.accept()
                self._show_overlay("任务已发送", "已加入当前 DSH 对话", "SUCCESS", 3000)
                if self.voice_mode == "call":
                    QTimer.singleShot(0, self._dispatch_voice_tasks)
                elif self.voice_tasks:
                    QTimer.singleShot(0, self._preserve_voice_queue)
            else:
                self.pending_task_files = []
                error = str(message.get("error", "任务发送失败，请重试"))[:200]
                if self.task_feedback is not None:
                    self.task_feedback.setText(error)
                    self.task_feedback.setStyleSheet("color: #B42318;")
                if self.task_send_button is not None:
                    self.task_send_button.setEnabled(True)
                if self.voice_mode == "call":
                    self._stop_voice(finalize=False)
                if self.task_input is not None and not self.task_input.toPlainText().strip():
                    self.task_input.setPlainText(sent_text)
                self._show_overlay("任务发送失败", error, "ERROR", 4500)
            self._sync_bubble_size()
            self.update()

        def _open_client(self) -> None:
            if not QDesktopServices.openUrl(QUrl(self.webui_url)):
                print("Unable to open the configured DSH client", file=sys.stderr)
                self._show_overlay("无法打开 DSH", "请确认 DSH 已安装、打开地址设置正确", "ERROR", 4000)
                self._sync_bubble_size()
                self.update()

    application = QApplication(sys.argv[:1])
    application.setQuitOnLastWindowClosed(False)
    inbox = Inbox()
    window = CompanionWindow()
    if preview_voice_mode in {"dictation", "call"}:
        window.voice_mode = preview_voice_mode
        window.voice_started_ms = window._now_ms() - 65000
        window.voice_ready = True
        window.voice_level = 0.9
        window.voice_level_at_ms = window._now_ms()
        window.voice_last_speech_ms = window._now_ms()
        if preview_voice_mode == "call":
            window._append_call_message("我", "帮我看看今天还有什么任务")
            window._append_call_message("大哥", "今天还有两项任务，先完成最重要的一项。")
        window._refresh_voice_buttons()
        window._sync_bubble_size()
    glove_filter = GloveCursorFilter(window, window.glove_open_h, window.glove_closed_h)
    application.installNativeEventFilter(glove_filter)
    inbox.message.connect(window.apply_message)
    inbox.closed.connect(application.quit)

    def read_stdin() -> None:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = parse_message(line)
                if message.get("kind") == "ping":
                    emit_reply("pong")
                inbox.message.emit(message)
            except (ValueError, json.JSONDecodeError) as error:
                print(json.dumps({"kind": "error", "message": str(error)}), flush=True)
        inbox.closed.emit()

    reader = threading.Thread(target=read_stdin, name="dsh-bigfish-stdin", daemon=True)
    reader.start()
    window.show()
    if preview_chess and snapshot_path is not None:
        def chess_preview() -> None:
            window.xiangqi_mode.enter()
            window.xiangqi_mode.select(54)
            window.xiangqi_mode.select(45)
            started = time.monotonic()

            def save_chess() -> None:
                mode = window.xiangqi_mode
                if mode.busy and time.monotonic() - started < 8:
                    QTimer.singleShot(40, save_chess)
                    return
                if mode.busy or len(mode.game.history) != 2:
                    print("Chess preview failed to complete a local opponent move", file=sys.stderr)
                    application.exit(2)
                    return
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                window.snapshot_saved = window.grab().save(str(snapshot_path))
                board_path = snapshot_path.with_name(snapshot_path.stem + "-board.png")
                if not mode.dialog.grab().save(str(board_path)):
                    application.exit(2)

            QTimer.singleShot(40, save_chess)

        QTimer.singleShot(0, chess_preview)
    if preview_video is not None and snapshot_path is not None:
        def video_preview() -> None:
            mode = window.video_watcher
            window.snapshot_saved = True
            if not mode.enter():
                application.exit(2)
                return
            mode.audio.setMuted(True)
            if not mode.load(str(preview_video)):
                print("Video preview could not open the local file", file=sys.stderr)
                application.exit(2)
                return
            started = time.monotonic()

            def save_video() -> None:
                if mode.player.error() != mode.player.Error.NoError or time.monotonic() - started > 8:
                    print("Video preview could not render a frame: " + mode.player.errorString(), file=sys.stderr)
                    application.exit(2)
                    return
                if mode.video.image.isNull():
                    QTimer.singleShot(40, save_video)
                    return
                mode.player.pause()
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(snapshot_path))
                video_path = snapshot_path.with_name(snapshot_path.stem + "-video.png")
                if not mode.dialog.grab().save(str(video_path)):
                    application.exit(2)

            QTimer.singleShot(40, save_video)

        QTimer.singleShot(0, video_preview)
    if preview_douyin is not None and snapshot_path is not None:
        def douyin_preview() -> None:
            from urllib.parse import urlparse
            parsed = urlparse(preview_douyin)
            if not ((parsed.scheme == 'http' and parsed.hostname == '127.0.0.1')
                    or (parsed.scheme == 'https' and parsed.hostname == 'www.douyin.com')):
                print('Browser preview only supports official Douyin or the loopback test server', file=sys.stderr)
                application.exit(2)
                return
            try:
                from . import douyin_browser as browser_module
            except ImportError:
                import douyin_browser as browser_module
            browser_module.DOUYIN_HOME = preview_douyin
            mode = window.video_watcher
            window.snapshot_saved = True
            if not mode.enter() or not mode.show_douyin():
                print('Embedded browser could not start', file=sys.stderr)
                application.exit(2)
                return
            started = time.monotonic()
            checking = False

            def verified(value) -> None:
                nonlocal checking
                if not value:
                    checking = False
                    QTimer.singleShot(60, wait_browser)
                    return
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(snapshot_path))
                browser_path = snapshot_path.with_name(snapshot_path.stem + '-douyin.png')
                if not mode.dialog.grab().save(str(browser_path)):
                    application.exit(2)
                    return
                emit_reply('browser_preview', success=True)

            def wait_browser() -> None:
                nonlocal checking
                if time.monotonic() - started > 12:
                    print('Embedded browser timed out', file=sys.stderr)
                    application.exit(2)
                    return
                if mode.browser.ready and not checking:
                    checking = True
                    mode.browser.page.runJavaScript("!!document.body && document.body.innerText.length > 0", verified)
                elif not checking:
                    QTimer.singleShot(60, wait_browser)

            QTimer.singleShot(200, wait_browser)

        QTimer.singleShot(0, douyin_preview)
    emit_reply("ready")
    code = application.exec()
    recorder.close()
    return code


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="DSH BigFish native helper")
    parser.add_argument("--headless", action="store_true", help="validate the protocol without opening a window")
    parser.add_argument("--event-log", type=Path, help="append received protocol messages to a JSONL file")
    parser.add_argument("--snapshot", type=Path, help="save one diagnostic visual frame after the first message")
    parser.add_argument("--snapshot-voice-mode", choices=("dictation", "call"), help="show a voice pose in a diagnostic snapshot without starting the microphone")
    parser.add_argument("--snapshot-chess", action="store_true", help="verify a chess round and save the pet and board snapshots")
    parser.add_argument("--snapshot-video", type=Path, help="verify local video decoding and save the pet and player snapshots")
    parser.add_argument("--snapshot-douyin", help="verify the native embedded browser using official Douyin or a loopback fixture URL")
    args = parser.parse_args()
    if args.snapshot_voice_mode and args.snapshot is None:
        parser.error("--snapshot-voice-mode requires --snapshot")
    if args.snapshot_chess and (args.snapshot is None or args.snapshot_voice_mode or args.headless):
        parser.error("--snapshot-chess requires --snapshot in visual mode without --snapshot-voice-mode")
    if args.snapshot_video and (args.snapshot is None or args.headless or args.snapshot_chess or args.snapshot_voice_mode):
        parser.error("--snapshot-video requires --snapshot in visual mode without other preview modes")
    if args.snapshot_douyin and (args.snapshot is None or args.headless or args.snapshot_chess or args.snapshot_voice_mode or args.snapshot_video):
        parser.error("--snapshot-douyin requires --snapshot in visual mode without other preview modes")
    recorder = EventRecorder(args.event_log)
    return run_headless(recorder) if args.headless else run_visual(recorder, args.snapshot, args.snapshot_voice_mode, args.snapshot_chess, args.snapshot_video, args.snapshot_douyin)


if __name__ == "__main__":
    raise SystemExit(main())
