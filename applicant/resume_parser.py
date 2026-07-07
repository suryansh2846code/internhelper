import os
import base64
import config

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_IMAGE_MEDIA = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}


def load_resume(path: str = None) -> str:
    path = path or config.RESUME_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"Resume not found at {path}")

    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        return _parse_pdf(path)
    elif ext == ".docx":
        return _parse_docx(path)
    elif ext in _IMAGE_EXTS:
        return _parse_image(path)
    else:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


def _parse_pdf(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _parse_docx(path: str) -> str:
    from docx import Document
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _parse_image(path: str) -> str:
    """Use Claude vision to extract resume text from an image — no Tesseract needed."""
    import anthropic

    ext = os.path.splitext(path)[1].lower()
    media_type = _IMAGE_MEDIA.get(ext, "image/jpeg")

    with open(path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_data},
                },
                {
                    "type": "text",
                    "text": "Extract all text from this resume image. Return only the extracted text preserving structure. No commentary.",
                },
            ],
        }],
    )
    return msg.content[0].text
