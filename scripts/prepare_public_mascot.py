#!/usr/bin/env python3
"""Prepare the repository owner's approved mascot poses for public use.

The source renders stay in the ignored local-private-assets directory. Published
runtime sprites use the existing 412x344 RGBA canvas so every desktop renderer
keeps the same geometry and memory envelope.
"""

from pathlib import Path
from shutil import copy2

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "local-private-assets" / "pet" / "custom"
DESTINATION = ROOT / "assets" / "pet" / "custom"
CANVAS_SIZE = (412, 344)
POSES = (
    "front", "side", "back", "flying", "flying_side", "flying_back",
    "idle_pose", "thinking_pose", "working_pose", "waiting_pose",
    "head_pat", "poke", "tail", "recording_pose", "calling_pose",
    "file_ready", "file_caught",
)


def main() -> None:
    missing = [name for name in POSES if not (SOURCE / f"{name}.png").is_file()]
    if missing:
        raise SystemExit(f"Missing approved mascot poses: {', '.join(missing)}")

    DESTINATION.mkdir(parents=True, exist_ok=True)
    for name in POSES:
        source = SOURCE / f"{name}.png"
        destination = DESTINATION / source.name
        with Image.open(source) as image:
            rgba = image.convert("RGBA")
            if rgba.size == CANVAS_SIZE:
                copy2(source, destination)
                action = "copied"
            else:
                rgba.resize(CANVAS_SIZE, Image.Resampling.LANCZOS).save(destination, optimize=True)
                action = f"resized from {rgba.size[0]}x{rgba.size[1]}"
        print(f"{name}: {action}")


if __name__ == "__main__":
    main()
