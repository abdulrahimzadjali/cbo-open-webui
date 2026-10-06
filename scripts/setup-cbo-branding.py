import os
import shutil
import base64
from io import BytesIO
from PIL import Image

BRAIN_UPLOADS = r"C:\Users\Hp\.gemini\antigravity\brain\223ea0fd-abb6-4cfd-9c83-fe3665d461fb\.user_uploaded"
SEAL_SRC = os.path.join(BRAIN_UPLOADS, "media_1791186722209.png")
MOTIF_SRC = os.path.join(BRAIN_UPLOADS, "media_1791186722210.png")
BUILDING_SRC = os.path.join(BRAIN_UPLOADS, "media_1791186722118.png")
LOGO_HORIZ_SRC = os.path.join(BRAIN_UPLOADS, "media_1791186722105.png")
LOGO_HORIZ_RTL_SRC = os.path.join(BRAIN_UPLOADS, "media_1791186722216.png")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATIC_STATIC_DIR = os.path.join(STATIC_DIR, "static")
CBO_DIR = os.path.join(STATIC_DIR, "cbo")

os.makedirs(CBO_DIR, exist_ok=True)
os.makedirs(STATIC_STATIC_DIR, exist_ok=True)

# 1. Copy source assets to static/cbo/ (if source directory exists)
if os.path.exists(BRAIN_UPLOADS):
    shutil.copyfile(SEAL_SRC, os.path.join(CBO_DIR, "cbo-seal.png"))
    shutil.copyfile(MOTIF_SRC, os.path.join(CBO_DIR, "cbo-motif.png"))
    shutil.copyfile(BUILDING_SRC, os.path.join(CBO_DIR, "cbo-building-hero.png"))
    shutil.copyfile(LOGO_HORIZ_SRC, os.path.join(CBO_DIR, "cbo-logo-horizontal.png"))
    shutil.copyfile(LOGO_HORIZ_RTL_SRC, os.path.join(CBO_DIR, "cbo-logo-horizontal-rtl.png"))
    print("Copied primary CBO assets to static/cbo/")
else:
    print("Source upload directory not found, using existing assets in static/cbo/")

# Fallback to local files if brain uploads path is not present
SEAL_SRC = os.path.join(CBO_DIR, "cbo-seal.png") if not os.path.exists(SEAL_SRC) else SEAL_SRC
MOTIF_SRC = os.path.join(CBO_DIR, "cbo-motif.png") if not os.path.exists(MOTIF_SRC) else MOTIF_SRC

def create_fitted_square(img_path, target_size, padding_ratio=0.06):
    """Resizes image keeping aspect ratio and centers it on transparent square canvas."""
    im = Image.open(img_path).convert("RGBA")
    avail_size = int(target_size * (1 - padding_ratio * 2))
    im.thumbnail((avail_size, avail_size), Image.Resampling.LANCZOS)
    
    canvas = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))
    offset = ((target_size - im.width) // 2, (target_size - im.height) // 2)
    canvas.paste(im, offset, im)
    return canvas

# 2. Generate Favicons and App Manifest Icons (From Seal)
seal_512 = create_fitted_square(SEAL_SRC, 512, padding_ratio=0.03)
seal_512.save(os.path.join(STATIC_DIR, "favicon.png"), "PNG")
seal_512.save(os.path.join(STATIC_STATIC_DIR, "favicon.png"), "PNG")
seal_512.save(os.path.join(STATIC_STATIC_DIR, "web-app-manifest-512x512.png"), "PNG")

seal_192 = create_fitted_square(SEAL_SRC, 192, padding_ratio=0.03)
seal_192.save(os.path.join(STATIC_STATIC_DIR, "web-app-manifest-192x192.png"), "PNG")

seal_180 = create_fitted_square(SEAL_SRC, 180, padding_ratio=0.03)
seal_180.save(os.path.join(STATIC_STATIC_DIR, "apple-touch-icon.png"), "PNG")

seal_96 = create_fitted_square(SEAL_SRC, 96, padding_ratio=0.03)
seal_96.save(os.path.join(STATIC_STATIC_DIR, "favicon-96x96.png"), "PNG")

# Generate favicon.ico
ico_canvas = create_fitted_square(SEAL_SRC, 64, padding_ratio=0.03)
ico_canvas.save(os.path.join(STATIC_STATIC_DIR, "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
print("Generated favicons and PWA icons from CBO Seal")

# 3. Generate Splash and Logo Icons (From Diamond Motif)
motif_500 = create_fitted_square(MOTIF_SRC, 500, padding_ratio=0.06)
motif_500.save(os.path.join(STATIC_STATIC_DIR, "splash.png"), "PNG")
motif_500.save(os.path.join(STATIC_STATIC_DIR, "splash-dark.png"), "PNG")
motif_500.save(os.path.join(STATIC_STATIC_DIR, "logo.png"), "PNG")
print("Generated splash and logo icons from CBO Diamond Motif")

# 4. Generate static/static/favicon.svg
buf = BytesIO()
seal_500 = create_fitted_square(SEAL_SRC, 500, padding_ratio=0.03)
seal_500.save(buf, format="PNG")
b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" version="1.1" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:svgjs="http://svgjs.dev/svgjs" width="500" height="500" viewBox="0 0 500 500"><image width="500" height="500" xlink:href="data:image/png;base64,{b64_str}"></image><style>@media (prefers-color-scheme: light) {{ :root {{ filter: none; }} }}
@media (prefers-color-scheme: dark) {{ :root {{ filter: none; }} }}
</style></svg>'''
with open(os.path.join(STATIC_STATIC_DIR, "favicon.svg"), "w", encoding="utf-8") as f:
    f.write(svg_content)
print("Generated favicon.svg")

# 5. Generate Seamless Repeating Watermark Pattern Tiles
def generate_watermark_tiles():
    import numpy as np

    motif_file = MOTIF_SRC
    im = Image.open(motif_file).convert("RGBA")
    arr = np.array(im, dtype=np.float32)

    alpha = arr[:, :, 3]
    is_colored = alpha > 50

    # Red region: where R > 150 and G < 100
    is_red = is_colored & (arr[:, :, 0] > 150) & (arr[:, :, 1] < 100)
    # Gold region: outer diamond border
    is_gold = is_colored & (~is_red)

    def create_monochrome_motif(color_gold, color_red, alpha_mult=1.0):
        new_arr = np.zeros_like(arr)
        new_arr[is_gold, 0] = color_gold[0]
        new_arr[is_gold, 1] = color_gold[1]
        new_arr[is_gold, 2] = color_gold[2]
        new_arr[is_gold, 3] = arr[is_gold, 3] * alpha_mult

        new_arr[is_red, 0] = color_red[0]
        new_arr[is_red, 1] = color_red[1]
        new_arr[is_red, 2] = color_red[2]
        new_arr[is_red, 3] = arr[is_red, 3] * alpha_mult
        return Image.fromarray(np.uint8(np.clip(new_arr, 0, 255)))

    def create_seamless_tile(motif_img, tile_size=240, motif_size=108):
        m = motif_img.copy()
        m.thumbnail((motif_size, motif_size), Image.Resampling.LANCZOS)
        mw, mh = m.size

        tile = Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))

        # Center motif
        cx = (tile_size - mw) // 2
        cy = (tile_size - mh) // 2
        tile.paste(m, (cx, cy), m)

        # 4 corners (quincunx / staggered pattern)
        corners = [
            (-mw // 2, -mh // 2),
            (tile_size - mw // 2, -mh // 2),
            (-mw // 2, tile_size - mh // 2),
            (tile_size - mw // 2, tile_size - mh // 2)
        ]
        for ox, oy in corners:
            tile.paste(m, (ox, oy), m)

        return tile

    # Light mode tile: Warm gold / bronze tones
    m_light = create_monochrome_motif((191, 165, 118), (159, 132, 82), alpha_mult=0.15)
    tile_light = create_seamless_tile(m_light, tile_size=240, motif_size=108)
    tile_light.save(os.path.join(CBO_DIR, "cbo-watermark-tile-light.png"), "PNG")
    tile_light.save(os.path.join(STATIC_STATIC_DIR, "cbo-watermark-tile-light.png"), "PNG")

    # Dark mode tile: Luminous champagne gold tones
    m_dark = create_monochrome_motif((223, 207, 173), (200, 180, 140), alpha_mult=0.18)
    tile_dark = create_seamless_tile(m_dark, tile_size=240, motif_size=108)
    tile_dark.save(os.path.join(CBO_DIR, "cbo-watermark-tile-dark.png"), "PNG")
    tile_dark.save(os.path.join(STATIC_STATIC_DIR, "cbo-watermark-tile-dark.png"), "PNG")

    print("Generated seamless watermark pattern tiles (light & dark)")

generate_watermark_tiles()
