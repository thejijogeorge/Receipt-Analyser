import os

from . import pdf_extractor, image_extractor

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
PDF_EXTENSIONS = {".pdf"}

SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS


def extract_text(file_path):
    """Extract raw text from a receipt file, choosing the right method
    based on file type: pdfplumber for PDFs, OCR for photographed/scanned
    images. Raises ValueError for unsupported file types.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in PDF_EXTENSIONS:
        return pdf_extractor.extract_text(file_path)
    if ext in IMAGE_EXTENSIONS:
        return image_extractor.extract_text(file_path)

    raise ValueError(f"Unsupported file type: {ext}")
