"""Bounded 16 kHz PCM segmentation for dictation and continuous calls."""

from __future__ import annotations

from array import array
from collections import deque
from math import sqrt


class VoiceSegmenter:
    FRAME_BYTES = 3200  # 100 ms, mono signed 16-bit PCM at 16 kHz

    def __init__(self, threshold: int = 320, silence_frames: int = 8, max_frames: int = 200):
        self.threshold = threshold
        self.silence_frames = silence_frames
        self.max_frames = max_frames
        self.reset()

    def reset(self) -> None:
        self.pending = bytearray()
        self.preroll: deque[bytes] = deque(maxlen=3)
        self.frames: list[bytes] = []
        self.quiet = 0
        self.voiced = 0
        self.recent_energy = 0.0
        self.recent_talking = False
        self.meter_frames = 0

    def feed(self, data: bytes) -> list[bytes]:
        self.pending.extend(data)
        complete: list[bytes] = []
        self.recent_energy = 0.0
        self.recent_talking = False
        self.meter_frames = 0
        while len(self.pending) >= self.FRAME_BYTES:
            frame = bytes(self.pending[: self.FRAME_BYTES])
            del self.pending[: self.FRAME_BYTES]
            samples = array('h')
            samples.frombytes(frame)
            energy = sqrt(sum(sample * sample for sample in samples) / len(samples))
            talking = energy >= self.threshold
            self.recent_energy = max(self.recent_energy, energy)
            self.recent_talking = self.recent_talking or talking
            self.meter_frames += 1
            if not self.frames:
                if talking:
                    self.frames = [*self.preroll, frame]
                    self.preroll.clear()
                    self.voiced = 1
                else:
                    self.preroll.append(frame)
                continue
            self.frames.append(frame)
            if talking:
                self.voiced += 1
                self.quiet = 0
            else:
                self.quiet += 1
            if self.quiet >= self.silence_frames or len(self.frames) >= self.max_frames:
                if self.voiced >= 2:
                    complete.append(b''.join(self.frames))
                self.frames = []
                self.quiet = 0
                self.voiced = 0
        return complete

    def flush(self) -> bytes | None:
        result = b''.join(self.frames) if self.voiced >= 2 else None
        self.reset()
        return result
