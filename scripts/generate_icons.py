"""Render STEVE's code-native mark into Fusion's toolbar PNG sizes (requires Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / "addin" / "STEVE" / "resources"
root.mkdir(exist_ok=True)
for size in (16, 32, 64):
    scale = size * 4 / 80
    image = Image.new("RGBA", (size * 4, size * 4))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([scale, scale, 79*scale, 79*scale], radius=25*scale,
                           fill="#1c3733", outline="#3e6960", width=max(1, round(scale)))
    stroke = round(5 * scale)
    for start, end, y in ((31, 57, 25), (31, 49, 40), (23, 49, 55)):
        draw.line([(start*scale, y*scale), (end*scale, y*scale)], fill="#addec7", width=stroke)
    # Pillow strokes inward, so expand the bounds to keep the arc centerline aligned.
    draw.arc([21*scale, 22.5*scale, 41*scale, 42.5*scale], 90, 270, fill="#addec7", width=stroke)
    draw.arc([39*scale, 37.5*scale, 59*scale, 57.5*scale], 270, 450, fill="#addec7", width=stroke)
    draw.ellipse([20.5*scale,52.5*scale,25.5*scale,57.5*scale], fill="#addec7")
    draw.ellipse([54*scale,22*scale,60*scale,28*scale], fill="#e1bb88")
    image.resize((size,size), Image.Resampling.LANCZOS).save(root / f"{size}x{size}.png")
