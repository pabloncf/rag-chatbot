from __future__ import annotations

from apps.documents.models import Document
from apps.embeddings.services.embedding_service import encode
from apps.embeddings.services.vector_store import SearchResult, search


def retrieve(
    question: str,
    user,
    document_ids: list[int] | None = None,
    top_k: int = 5,
) -> list[SearchResult]:
    """
    Encode the question and retrieve the top-K most relevant chunks.

    If document_ids is None, searches across all READY documents owned by the user.
    Provided IDs are validated against the user's ownership before searching.
    """
    if document_ids is None:
        valid_ids = list(
            Document.objects.filter(owner=user, status=Document.Status.READY)
            .values_list("id", flat=True)
        )
    else:
        valid_ids = list(
            Document.objects.filter(pk__in=document_ids, owner=user, status=Document.Status.READY)
            .values_list("id", flat=True)
        )

    if not valid_ids:
        return []

    query_embedding = encode([question])[0]
    return search(document_ids=valid_ids, query_embedding=query_embedding, top_k=top_k)
