from __future__ import annotations

import anthropic
from django.conf import settings

from apps.embeddings.services.vector_store import SearchResult

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024

SYSTEM_PROMPT = """You are a helpful assistant that answers questions strictly based on the provided document context.

Rules:
- Answer using ONLY the information in the provided context. Do not use outside knowledge.
- If the context does not contain sufficient information, state that clearly.
- Be concise and accurate.
- When referencing specific facts, mention the source page number when available."""


def answer(
    question: str,
    chunks: list[SearchResult],
    conversation_history: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """
    Call the Claude API with context chunks and return (answer_text, sources).

    sources is a list of {chunk_id, document_id, page_number} for each chunk used.
    """
    if not chunks:
        return (
            "I couldn't find relevant information in your documents to answer this question.",
            [],
        )

    context = "\n\n---\n\n".join(
        f"[Source {i} — Document {chunk.document_id}, Page {chunk.page_number}]\n{chunk.content}"
        for i, chunk in enumerate(chunks, start=1)
    )

    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history[-6:])  # last 3 exchanges

    messages.append(
        {
            "role": "user",
            "content": f"Context from documents:\n\n{context}\n\n---\n\nQuestion: {question}",
        }
    )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    answer_text: str = response.content[0].text
    sources = [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "page_number": chunk.page_number,
        }
        for chunk in chunks
    ]

    return answer_text, sources
