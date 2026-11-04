#!/usr/bin/env python3
"""Create the public, original robot sprites and non-voice notification sounds.

Private character renders and voice recordings belong in local-private-assets/.
This script deliberately uses only Pillow drawing primitives and synthesized tones.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SPRITES = ROOT / "assets/pet/custom"
SOUNDS = ROOT / "assets/sounds"
SIZE = (412, 344)
POSES = (
    "front", "side", "back", "flying", "flying_side", "flying_back",
    "idle_pose", "thinking_pose", "working_pose", "waiting_pose",
    "head_pat", "poke", "tail", "recording_pose", "calling_pose",
    "file_ready", "file_caught",
)
EVENTS = ("success", "error", "approval", "sleep", "alarm", "todo")
NOTES = {
    "success": (523.25, 659.25, 783.99),
    "error": (392.0, 329.63, 261.63),
    "approval": (659.25, 659.25, 880.0),
    "sleep": (440.0, 392.0, 329.63),
    "alarm": (783.99, 1046.5, 783.99),
    "todo": (493.88, 587.33, 659.25),
}


def sprite(pose: str) -> Image.Image:
    image = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    flying = pose.startswith("flying")
    tilt = 12 if pose in {"flying", "flying_side", "working_pose"} else 0
    eyes = pose not in {"back", "flying_back"}
    # The mascot is an original blue screen robot: rounded body, headphones,
    # cyan faceplate, and a small four-point star. It is unrelated to the
    # user's private insect character and to the upstream whale character.
    draw.ellipse((136, 263, 276, 285), fill=(25, 73, 113, 49))
    draw.rounded_rectangle((122, 107, 290, 262), radius=62, fill=(23, 77, 132, 255), outline=(18, 53, 96, 255), width=5)
    for y in range(115, 256):
        alpha = max(0, 72 - (y - 115) // 2)
        draw.line((137, y, 271, y), fill=(119, 212, 245, alpha), width=1)
    draw.rounded_rectangle((136, 124, 276, 201), radius=31, fill=(180, 239, 250, 255), outline=(40, 143, 191, 255), width=5)
    draw.arc((113, 82, 299, 225), 188, 354, fill=(13, 46, 91, 255), width=11)
    draw.rounded_rectangle((111, 130, 132, 187), radius=9, fill=(28, 105, 163, 255))
    draw.rounded_rectangle((280, 130, 301, 187), radius=9, fill=(28, 105, 163, 255))
    if eyes:
        draw.ellipse((172, 153, 187, 169), fill=(22, 70, 111, 255))
        draw.ellipse((224, 153, 239, 169), fill=(22, 70, 111, 255))
        draw.arc((191, 165, 221, 187), 4, 176, fill=(22, 70, 111, 255), width=4)
    else:
        draw.rounded_rectangle((172, 150, 240, 168), radius=8, fill=(42, 139, 182, 255))
    draw.polygon([(206, 211), (212, 222), (223, 228), (212, 234), (206, 245), (200, 234), (189, 228), (200, 222)], fill=(143, 230, 243, 255))
    draw.rounded_rectangle((158, 250, 181, 278), radius=10, fill=(20, 65, 109, 255))
    draw.rounded_rectangle((231, 250, 254, 278), radius=10, fill=(20, 65, 109, 255))
    if flying:
        draw.ellipse((67, 187, 137, 223), fill=(65, 170, 211, 245), outline=(20, 100, 158, 255), width=4)
        draw.ellipse((275, 187, 345, 223), fill=(65, 170, 211, 245), outline=(20, 100, 158, 255), width=4)
        draw.arc((146, 271, 267, 307), 190, 350, fill=(100, 209, 243, 210), width=7)
    elif pose in {"file_ready", "file_caught"}:
        draw.rounded_rectangle((284, 196, 325, 239), radius=6, fill=(255, 245, 197, 255), outline=(49, 127, 164, 255), width=3)
        draw.line((293, 208, 316, 208), fill=(49, 127, 164, 255), width=3)
        if pose == "file_caught":
            draw.ellipse((309, 187, 335, 213), fill=(107, 211, 131, 255))
    elif pose in {"recording_pose", "calling_pose"}:
        draw.rounded_rectangle((293, 194, 313, 234), radius=9, fill=(42, 124, 182, 255))
        draw.arc((287, 197, 320, 235), 0, 180, fill=(84, 215, 237, 255), width=4)
        if pose == "calling_pose":
            draw.arc((318, 185, 351, 221), 270, 90, fill=(84, 215, 237, 255), width=4)
    elif pose == "thinking_pose":
        draw.ellipse((300, 100, 318, 118), fill=(120, 214, 244, 255))
        draw.ellipse((323, 84, 335, 96), fill=(120, 214, 244, 200))
    elif pose == "waiting_pose":
        draw.arc((295, 140, 349, 196), 185, 345, fill=(120, 214, 244, 255), width=5)
    elif pose == "working_pose":
        draw.line((300, 204, 335, 198), fill=(71, 174, 221, 255), width=7)
    elif pose == "head_pat":
        draw.ellipse((145, 80, 266, 101), fill=(119, 209, 234, 105))
    elif pose == "poke":
        draw.ellipse((280, 160, 312, 192), outline=(91, 214, 241, 255), width=4)
    elif pose == "tail":
        draw.arc((266, 215, 350, 292), 230, 80, fill=(85, 191, 231, 255), width=10)
    if pose == "side":
        image = image.transform(SIZE, Image.Transform.AFFINE, (0.83, 0, 33, 0, 1, 0), resample=Image.Resampling.BICUBIC)
    if tilt:
        image = image.rotate(tilt, resample=Image.Resampling.BICUBIC)
    return image


def sound(path: Path, event: str, pack: int) -> None:
    rate = 44_100
    duration = 2.35 + 0.12 * pack
    frames = bytearray()
    frequencies = NOTES[event]
    for index in range(round(rate * duration)):
        moment = index / rate
        value = 0.0
        for note, frequency in enumerate(frequencies):
            start = 0.14 + note * (0.46 + pack * 0.04)
            local = moment - start
            if 0 <= local < 0.52:
                envelope = min(1, local / 0.012) * max(0, 1 - local / 0.52) ** 2
                pitch = frequency * (1 + pack * 0.04)
                value += 0.20 * envelope * (math.sin(2 * math.pi * pitch * local) + 0.15 * math.sin(4 * math.pi * pitch * local))
        frames.extend(struct.pack("<h", round(max(-1, min(1, value)) * 32767)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(frames)


def main() -> None:
    SPRITES.mkdir(parents=True, exist_ok=True)
    for pose in POSES:
        sprite(pose).save(SPRITES / f"{pose}.png")
    for pack, folder in enumerate((SOUNDS, SOUNDS / "clean", SOUNDS / "video")):
        for event in EVENTS:
            sound(folder / f"{event}.wav", event, pack)


if __name__ == "__main__":
    main()
