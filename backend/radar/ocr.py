"""OCR and perceptual hashing for ad creatives and thumbnails.

Illegal ads often put "kazino", "bonus", "250 FS" into the picture while the ad text stays
innocent, so every Meta ad image is read with Tesseract (Azerbaijani, Russian, Turkish,
English) and hashed (pHash) to cluster re-uploads of the same creative.
"""

from __future__ import annotations

import io
import re

import imagehash
from PIL import Image, ImageOps

from radar.config import get_settings


def prepare(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("L")
    if img.width < 1000:  # Tesseract reads small ad text far better when upscaled
        factor = 1000 / img.width
        img = img.resize((int(img.width * factor), int(img.height * factor)), Image.LANCZOS)
    return ImageOps.autocontrast(img)


def read_image(content: bytes) -> dict:
    import pytesseract

    img = Image.open(io.BytesIO(content))
    phash = str(imagehash.phash(img.convert("RGB")))
    text = ""
    if get_settings().ocr_enabled:
        raw = pytesseract.image_to_string(prepare(img), lang=get_settings().ocr_langs, config="--psm 11")
        text = re.sub(r"\s+", " ", raw).strip()
    return {"text": text, "phash": phash, "size": [img.width, img.height]}
