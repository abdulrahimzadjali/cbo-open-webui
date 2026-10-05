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

# 1. Copy source assets to static/cbo/
shutil.copyfile(SEAL_SRC, os.path.join(CBO_DIR, "cbo-seal.png"))
shutil.copyfile(MOTIF_SRC, os.path.join(CBO_DIR, "cbo-motif.png"))
shutil.copyfile(BUILDING_SRC, os.path.join(CBO_DIR, "cbo-building-hero.png"))
shutil.copyfile(LOGO_HORIZ_SRC, os.path.join(CBO_DIR, "cbo-logo-horizontal.png"))
shutil.copyfile(LOGO_HORIZ_RTL_SRC, os.path.join(CBO_DIR, "cbo-logo-horizontal-rtl.png"))
print("Copied primary CBO assets to static/cbo/")

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
