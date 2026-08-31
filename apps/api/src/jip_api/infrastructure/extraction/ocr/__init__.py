"""Optical character recognition, for documents with no text layer."""

from jip_api.infrastructure.extraction.ocr.base import OcrEngine, OcrPage, OcrResult
from jip_api.infrastructure.extraction.ocr.rasterise import rasterise
from jip_api.infrastructure.extraction.ocr.tesseract import TesseractEngine, get_ocr_engine

__all__ = [
    "OcrEngine",
    "OcrPage",
    "OcrResult",
    "TesseractEngine",
    "get_ocr_engine",
    "rasterise",
]
