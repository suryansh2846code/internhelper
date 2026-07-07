import os
import config


def load_resume(path: str = None) -> str:
    path = path or config.RESUME_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"Resume not found at {path}")

    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        return _parse_pdf(path)
    else:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


def _parse_pdf(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)
