"""Bounded 16 kHz PCM segmentation for dictation and continuous calls."""

from __future__ import annotations

from array import array
from collections import deque
from math import sqrt
import sys


class Pcm16MonoConverter:
    """Convert common native microphone PCM formats to 16 kHz mono Int16.

    Qt audio devices commonly expose 44.1/48 kHz stereo as their preferred
    format. Keeping the conversion here lets recording work on those devices
    while the segmenter and Whisper input retain one stable format.
    """

    TARGET_RATE = 16000
    SAMPLE_WIDTHS = {"UInt8": 1, "Int16": 2, "Int32": 4, "Float": 4}

    def __init__(self, sample_rate: int, channel_count: int, sample_format: str = "Int16"):
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channel_count <= 0:
            raise ValueError("channel_count must be positive")
        if sample_format not in self.SAMPLE_WIDTHS:
            raise ValueError(f"unsupported PCM sample format: {sample_format}")
        self.sample_rate = sample_rate
        self.channel_count = channel_count
        self.sample_format = sample_format
        self.sample_width = self.SAMPLE_WIDTHS[sample_format]
        self.pending = bytearray()
        self.rate_accumulator = 0

    def reset(self) -> None:
        self.pending.clear()
        self.rate_accumulator = 0

    def feed(self, data: bytes) -> bytes:
        self.pending.extend(data)
        frame_width = self.sample_width * self.channel_count
        byte_count = len(self.pending) - (len(self.pending) % frame_width)
        if byte_count <= 0:
            return b""
        raw = bytes(self.pending[:byte_count])
        del self.pending[:byte_count]
        samples = self._decode(raw)
        output = array("h")
        for offset in range(0, len(samples), self.channel_count):
            mono = round(sum(samples[offset:offset + self.channel_count]) / self.channel_count)
            self.rate_accumulator += self.TARGET_RATE
            while self.rate_accumulator >= self.sample_rate:
                output.append(max(-32768, min(32767, mono)))
                self.rate_accumulator -= self.sample_rate
        if sys.byteorder != "little":
            output.byteswap()
        return output.tobytes()

    def _decode(self, raw: bytes) -> list[int]:
        if self.sample_format == "UInt8":
            return [(sample - 128) << 8 for sample in raw]
        typecode = {"Int16": "h", "Int32": "i", "Float": "f"}[self.sample_format]
        decoded = array(typecode)
        decoded.frombytes(raw)
        if self.sample_format == "Int16":
            return list(decoded)
        if self.sample_format == "Int32":
            return [sample >> 16 for sample in decoded]
        return [round(max(-1.0, min(1.0, sample)) * 32767) for sample in decoded]


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
