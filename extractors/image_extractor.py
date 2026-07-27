import pytesseract
from PIL import Image, ImageOps, ImageFilter


def extract_text(file_path):
    """OCR a photographed/scanned receipt image. Photos of receipts (as
    opposed to clean digital PDFs) tend to have low contrast, small text,
    slight skew/crumpling, and uneven shadows.

    We preprocess using background normalization (subtracting blurred
    lighting gradient) to neutralize phone/hand shadows, followed by
    autocontrast. If binarized OCR produces insufficient text, we fall back
    to grayscale OCR so Tesseract can apply its internal adaptive binarization.
    """
    img = Image.open(file_path)

    gray = ImageOps.grayscale(img)
    w, h = gray.size
    gray = gray.resize((w * 2, h * 2), Image.LANCZOS)
    gray = ImageOps.autocontrast(gray)

    # Estimate background lighting/shadows using Gaussian blur
    bg = gray.filter(ImageFilter.GaussianBlur(radius=30))
    # Subtract background gradient to normalize lighting across shadows
    normalized = ImageOps.autocontrast(ImageOps.invert(ImageOps.difference(gray, bg)))

    # Try normalized image first (neutralizes shadows)
    text = pytesseract.image_to_string(normalized, config="--psm 6")

    # Fallback to direct grayscale (lets Tesseract apply its internal Otsu thresholding)
    if not text.strip() or len(text.strip()) < 30:
        text = pytesseract.image_to_string(gray, config="--psm 6")

    return text

