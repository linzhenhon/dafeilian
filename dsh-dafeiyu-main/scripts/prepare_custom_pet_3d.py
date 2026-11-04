"""Fit generated 3D-style pet views to the existing desktop sprite canvas."""

from pathlib import Path
from shutil import copy2

try:
    from PIL import Image, ImageFilter
except ImportError as error:
    raise SystemExit("Pillow is required to prepare pet assets: python -m pip install Pillow") from error


ROOT = Path(__file__).resolve().parents[1]
PET = ROOT / "assets" / "pet"
SOURCE = PET / "custom-3d-source"
ACTIVE = PET / "custom"
ORIGINAL = PET / "custom-original-2d"
CANVAS_SIZE = (412, 344)
SPRITE_HEIGHT = 268
FOOT_LINE = 312


def main() -> None:
    ORIGINAL.mkdir(exist_ok=True)
    for name in ("front", "side", "back", "flying", "idle_pose", "thinking_pose", "working_pose", "waiting_pose"):
        old = ACTIVE / f"{name}.png"
        backup = ORIGINAL / old.name
        if old.exists() and not backup.exists():
            copy2(old, backup)

        source = Image.open(SOURCE / f"{name}.png").convert("RGBA")
        alpha = source.getchannel("A")
        visible = alpha.point(lambda value: 255 if value >= 5 else 0)
        bounds = visible.getbbox()
        if bounds is None:
            raise ValueError(f"No visible pixels in {name}.png")
        crop = source.crop(bounds)
        clean_alpha = crop.getchannel("A").point(lambda value: 0 if value < 5 else value)
        crop.putalpha(clean_alpha.filter(ImageFilter.MinFilter(5)))
        target_height = SPRITE_HEIGHT if name != "flying" else 260
        target_width = 350 if name == "flying" else CANVAS_SIZE[0]
        factor = min(target_height / crop.height, target_width / crop.width)
        width, height = round(crop.width * factor), round(crop.height * factor)
        sprite = crop.resize((width, height), Image.Resampling.LANCZOS)
        sprite.putalpha(sprite.getchannel("A").filter(ImageFilter.MinFilter(3)))
        canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
        canvas.alpha_composite(sprite, ((CANVAS_SIZE[0] - width) // 2, FOOT_LINE - height))
        canvas.save(old, optimize=True)
        print(f"{name}: source {source.size}, visible {bounds}, sprite {sprite.size}")


if __name__ == "__main__":
    main()
