"""Convert an uploaded résumé (any supported format) to PDF.

Some platforms (Unstop) only accept PDF résumés. Rather than force a PDF upload,
we convert on demand: extract the résumé text and render a clean, plain PDF.
Formatting is not preserved — a PDF you upload directly stays untouched."""
import os

from fpdf import FPDF

from applicant.resume_parser import load_resume

# Map characters outside Latin-1 (fpdf core fonts) to safe ASCII equivalents.
_REPLACEMENTS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "•": "-", "…": "...",
    "₹": "Rs.", " ": " ", "﻿": "",
}


def ensure_pdf(path: str) -> str:
    """Return a PDF path for `path`. PDFs pass through untouched; other formats
    are converted to a text-based PDF cached next to the source."""
    if not path or not os.path.exists(path):
        return path
    if path.lower().endswith(".pdf"):
        return path

    out = path + ".pdf"
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
        return out

    text = load_resume(path) or ""
    _text_to_pdf(text, out)
    return out


def _sanitize(text: str) -> str:
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "ignore").decode("latin-1")


def _wrap_long_tokens(line: str, limit: int = 90) -> str:
    """Break tokens longer than a line width so multi_cell can render them."""
    out = []
    for tok in line.split(" "):
        while len(tok) > limit:
            out.append(tok[:limit])
            tok = tok[limit:]
        out.append(tok)
    return " ".join(out)


def _text_to_pdf(text: str, out_path: str) -> None:
    pdf = FPDF(format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in _sanitize(text).split("\n"):
        line = line.rstrip()
        if not line:
            pdf.ln(4)
            continue
        try:
            pdf.multi_cell(pdf.epw, 6, _wrap_long_tokens(line), new_x="LMARGIN", new_y="NEXT")
        except Exception:
            continue
    pdf.output(out_path)
