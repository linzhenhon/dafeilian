"""Generate short, original Xiangqi board sound effects as PCM WAV files."""
from __future__ import annotations

import math
import random
import wave
from pathlib import Path


RATE = 44_100
OUTPUT = Path(__file__).resolve().parent.parent / "assets" / "sounds" / "xiangqi"


def bell(samples: list[float], start: float, frequency: float, duration: float, volume: float) -> None:
    first = round(start * RATE)
    count = round(duration * RATE)
    for index in range(count):
        time = index / RATE
        attack = min(1.0, time / 0.006)
        envelope = attack * math.exp(-time * 8.0)
        tone = math.sin(math.tau * frequency * time)
        tone += 0.32 * math.sin(math.tau * frequency * 2.71 * time)
        tone += 0.12 * math.sin(math.tau * frequency * 4.13 * time)
        position = first + index
        if position < len(samples):
            samples[position] += volume * envelope * tone


def wood_tap(samples: list[float], start: float, frequency: float, volume: float, seed: int) -> None:
    rng = random.Random(seed)
    first = round(start * RATE)
    count = round(0.075 * RATE)
    for index in range(count):
        time = index / RATE
        envelope = math.exp(-time * 68.0)
        tone = math.sin(math.tau * frequency * time) + 0.25 * math.sin(math.tau * frequency * 2.8 * time)
        noise = rng.uniform(-1.0, 1.0) * math.exp(-time * 120.0)
        position = first + index
        if position < len(samples):
            samples[position] += volume * envelope * (0.62 * tone + 0.38 * noise)


def render(name: str) -> None:
    if name in {"move", "capture"}:
        length = 0.21 if name == "move" else 0.30
    elif name == "check":
        length = 0.48
    else:
        length = 0.72
    samples = [0.0] * round(length * RATE)

    if name == "move":
        wood_tap(samples, 0.0, 680, 0.58, 11)
    elif name == "capture":
        wood_tap(samples, 0.0, 420, 0.64, 21)
        wood_tap(samples, 0.095, 560, 0.50, 22)
    elif name == "check":
        for start, frequency in ((0.00, 659.25), (0.14, 830.61), (0.28, 987.77)):
            bell(samples, start, frequency, 0.22, 0.30)
    elif name == "win":
        for start, frequency in ((0.00, 523.25), (0.13, 659.25), (0.26, 783.99), (0.39, 1046.50)):
            bell(samples, start, frequency, 0.30, 0.25)
    elif name == "loss":
        for start, frequency in ((0.00, 659.25), (0.16, 523.25), (0.32, 392.00)):
            bell(samples, start, frequency, 0.34, 0.27)
    else:
        raise ValueError(f"Unknown Xiangqi sound: {name}")

    peak = max(max(abs(sample) for sample in samples), 1e-9)
    gain = min(0.92 / peak, 1.0)
    pcm = bytearray()
    for sample in samples:
        value = round(max(-1.0, min(1.0, sample * gain)) * 32767)
        pcm.extend(int(value).to_bytes(2, "little", signed=True))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUTPUT / f"{name}.wav"), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm)


if __name__ == "__main__":
    for event in ("move", "capture", "check", "win", "loss"):
        render(event)
