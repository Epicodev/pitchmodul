"""
PDF parser. Henter tekst-indhold fra årsrapporter til Claude-analyse.
"""
import pdfplumber
from typing import BinaryIO, List
import io


def extract_text(file_or_bytes) -> str:
    """
    Uddrag tekst fra PDF. Tager enten et bytes-objekt, file-like, eller sti.
    Returnerer alt tekst joined med dobbelt-newline mellem sider.
    """
    if isinstance(file_or_bytes, bytes):
        source = io.BytesIO(file_or_bytes)
    else:
        source = file_or_bytes

    pages: List[str] = []
    with pdfplumber.open(source) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"--- Side {i} ---\n{text.strip()}")

    return "\n\n".join(pages)
