"""
OCR backend. This one is real (not mocked) out of the box: it uses
pytesseract + the Tesseract binary (installed in the Docker image) to
extract actual text from uploaded images. No API key required.
"""
import asyncio
import io

import pytesseract
from PIL import Image

from app.logging_config import get_logger

logger = get_logger("ocr_service")


def _run_ocr(image_bytes: bytes) -> dict:
    img = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    words = [w for w in data.get("text", []) if w.strip()]
    confidences = [
        float(c) for c, w in zip(data.get("conf", []), data.get("text", []))
        if w.strip() and c not in ("-1", -1)
    ]
    avg_conf = sum(confidences) / len(confidences) if confidences else None

    return {
        "text": " ".join(words),
        "word_count": len(words),
        "confidence": round(avg_conf, 2) if avg_conf is not None else None,
    }


async def extract_text(image_bytes: bytes) -> dict:
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _run_ocr, image_bytes)
        result["provider"] = "tesseract"
        return result
    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract binary not found in container")
        return {
            "text": "",
            "word_count": 0,
            "confidence": None,
            "provider": "unavailable",
        }
