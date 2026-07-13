import pytesseract
from PIL import Image, ImageOps


def extract_text(file_path):
    """OCR a photographed/scanned receipt image. Photos of receipts (as
    opposed to clean digital PDFs) tend to have low contrast, small text,
    and slight skew/crumpling, so we preprocess before handing off to
    tesseract: grayscale, upscale, boost contrast, then binarize. This
    noticeably improves accuracy on real phone-camera receipt photos
    versus running OCR on the raw image.
    """
    img = Image.open(file_path)

    gray = ImageOps.grayscale(img)

    # upscale -- tesseract does much better with larger text
    w, h = gray.size
    gray = gray.resize((w * 2, h * 2), Image.LANCZOS)

    gray = ImageOps.autocontrast(gray)

    # binarize (simple fixed threshold works well for receipt paper)
    bw = gray.point(lambda x: 0 if x < 150 else 255, "1")

    # psm 6: assume a single uniform block of text -- suits receipt layout
    return pytesseract.image_to_string(bw, config="--psm 6")
