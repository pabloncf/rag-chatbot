from dataclasses import dataclass

from .pdf_parser import ParsedPage


@dataclass
class Chunk:
    content: str
    chunk_index: int
    page_number: int


def chunk_pages(
    pages: list[ParsedPage],
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[Chunk]:
    """Split parsed pages into overlapping word-based chunks."""
    chunks: list[Chunk] = []
    chunk_index = 0
    step = max(chunk_size - overlap, 1)

    for page in pages:
        words = page.text.split()
        start = 0
        while start < len(words):
            content = " ".join(words[start : start + chunk_size]).strip()
            if content:
                chunks.append(
                    Chunk(content=content, chunk_index=chunk_index, page_number=page.page_number)
                )
                chunk_index += 1
            start += step

    return chunks
