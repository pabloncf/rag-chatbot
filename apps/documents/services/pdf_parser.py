from dataclasses import dataclass

import fitz  # PyMuPDF


@dataclass
class ParsedPage:
    page_number: int
    text: str


def parse_pdf(file_path: str) -> tuple[list[ParsedPage], int]:
    """Extract text from each page of a PDF. Returns (pages, total_page_count)."""
    pages: list[ParsedPage] = []
    with fitz.open(file_path) as doc:
        total_pages = len(doc)
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if text:
                pages.append(ParsedPage(page_number=page_num, text=text))
    return pages, total_pages
