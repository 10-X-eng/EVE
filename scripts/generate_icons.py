"""Render EVE's code-native mark into Fusion's toolbar PNG sizes (requires Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / "addin" / "EVE" / "resources"
root.mkdir(exist_ok=True)
for size in (16, 32, 64):
    scale = size * 4 / 80
    image = Image.new("RGBA", (size * 4, size * 4))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([scale, scale, 79*scale, 79*scale], radius=25*scale,
                           fill="#1c3733", outline="#3e6960", width=max(1, round(scale)))
    for y, end in ((25, 57), (40, 50), (55, 57)):
        draw.rounded_rectangle([23*scale, (y-2.5)*scale, end*scale, (y+2.5)*scale],
                               radius=2.5*scale, fill="#addec7")
    draw.ellipse([53*scale,37*scale,59*scale,43*scale], fill="#e1bb88")
    image.resize((size,size), Image.Resampling.LANCZOS).save(root / f"{size}x{size}.png")
