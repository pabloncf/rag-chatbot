from __future__ import annotations

import logging
from dataclasses import dataclass

import chromadb
from django.conf import settings

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        path = getattr(settings, "CHROMA_PERSIST_DIRECTORY", "/app/chroma_data")
        _client = chromadb.PersistentClient(path=path)
    return _client


def _collection_name(document_id: int) -> str:
    return f"doc_{document_id}"


@dataclass
class SearchResult:
    chunk_id: int
    document_id: int
    page_number: int
    content: str
    score: float


def add_documents(document_id: int, chunks: list[dict]) -> None:
    """
    Store chunk embeddings in ChromaDB.

    Each chunk dict requires: chunk_id, content, page_number, embedding.
    """
    client = _get_client()
    collection = client.get_or_create_collection(
        name=_collection_name(document_id),
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(
        ids=[str(c["chunk_id"]) for c in chunks],
        embeddings=[c["embedding"] for c in chunks],
        documents=[c["content"] for c in chunks],
        metadatas=[
            {
                "chunk_id": c["chunk_id"],
                "document_id": document_id,
                "page_number": c["page_number"],
            }
            for c in chunks
        ],
    )


def search(
    document_ids: list[int],
    query_embedding: list[float],
    top_k: int = 5,
) -> list[SearchResult]:
    """Search for semantically similar chunks across the given documents."""
    client = _get_client()
    results: list[SearchResult] = []

    for doc_id in document_ids:
        try:
            collection = client.get_collection(_collection_name(doc_id))
            count = collection.count()
            if count == 0:
                continue
            res = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, count),
                include=["documents", "metadatas", "distances"],
            )
            for content, metadata, distance in zip(
                res["documents"][0], res["metadatas"][0], res["distances"][0]
            ):
                results.append(
                    SearchResult(
                        chunk_id=int(metadata["chunk_id"]),
                        document_id=doc_id,
                        page_number=int(metadata["page_number"]),
                        content=content,
                        score=1.0 - distance,
                    )
                )
        except Exception as exc:
            logger.warning("Could not search collection for document %d: %s", doc_id, exc)
            continue

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def delete_collection(document_id: int) -> None:
    """Remove all embeddings for a document."""
    client = _get_client()
    try:
        client.delete_collection(_collection_name(document_id))
    except Exception as exc:
        logger.warning("Could not delete collection for document %d: %s", document_id, exc)
