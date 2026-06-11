import io

import fitz
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents.models import Document
from apps.embeddings.services.embedding_service import EMBEDDING_DIMENSION, encode
from apps.embeddings.services.vector_store import add_documents, delete_collection, search

User = get_user_model()


@pytest.fixture
def chroma_dir(tmp_path, settings):
    """Isolated ChromaDB instance per test."""
    settings.CHROMA_PERSIST_DIRECTORY = str(tmp_path / "chroma")
    import apps.embeddings.services.vector_store as vs
    vs._client = None
    yield str(tmp_path / "chroma")
    vs._client = None


@pytest.fixture
def sample_pdf_bytes():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Python is a high-level programming language. " * 10)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="embed@example.com", password="StrongPass123!")


# --- Embedding service ---

def test_encode_returns_correct_dimension():
    embeddings = encode(["hello world"])
    assert len(embeddings) == 1
    assert len(embeddings[0]) == EMBEDDING_DIMENSION


def test_encode_multiple_texts():
    texts = ["first sentence", "second sentence", "third sentence"]
    embeddings = encode(texts)
    assert len(embeddings) == 3
    assert all(len(e) == EMBEDDING_DIMENSION for e in embeddings)


def test_encode_returns_floats():
    embeddings = encode(["test"])
    assert all(isinstance(v, float) for v in embeddings[0])


def test_similar_texts_have_higher_score_than_dissimilar(chroma_dir):
    texts = [
        "Machine learning is a subset of artificial intelligence.",
        "Deep learning uses neural networks with many layers.",
        "The Eiffel Tower is located in Paris, France.",
    ]
    embeddings = encode(texts)

    # Cosine similarity: dot product of normalized vectors
    import numpy as np
    e = [np.array(emb) for emb in embeddings]
    sim_ml_dl = float(np.dot(e[0], e[1]))
    sim_ml_paris = float(np.dot(e[0], e[2]))
    assert sim_ml_dl > sim_ml_paris


# --- Vector store ---

def test_add_and_search_returns_relevant_result(chroma_dir):
    texts = [
        "Python is a programming language used for web development.",
        "The capital of France is Paris.",
    ]
    embeddings = encode(texts)
    chunks = [
        {"chunk_id": 1, "content": texts[0], "page_number": 1, "embedding": embeddings[0]},
        {"chunk_id": 2, "content": texts[1], "page_number": 1, "embedding": embeddings[1]},
    ]
    add_documents(document_id=1, chunks=chunks)

    query_embedding = encode(["What programming languages are used for web?"])[0]
    results = search(document_ids=[1], query_embedding=query_embedding, top_k=2)

    assert len(results) > 0
    assert results[0].content == texts[0]
    assert results[0].document_id == 1
    assert results[0].chunk_id == 1


def test_search_across_multiple_documents(chroma_dir):
    e1 = encode(["Django is a Python web framework."])[0]
    e2 = encode(["PostgreSQL is a relational database."])[0]

    add_documents(1, [{"chunk_id": 10, "content": "Django is a Python web framework.", "page_number": 1, "embedding": e1}])
    add_documents(2, [{"chunk_id": 20, "content": "PostgreSQL is a relational database.", "page_number": 1, "embedding": e2}])

    query = encode(["Python web framework"])[0]
    results = search(document_ids=[1, 2], query_embedding=query, top_k=2)

    assert len(results) == 2
    assert results[0].content == "Django is a Python web framework."


def test_delete_collection_removes_results(chroma_dir):
    embedding = encode(["some content to delete"])[0]
    add_documents(99, [{"chunk_id": 99, "content": "some content to delete", "page_number": 1, "embedding": embedding}])

    delete_collection(99)

    query = encode(["some content"])[0]
    results = search(document_ids=[99], query_embedding=query)
    assert results == []


def test_search_empty_document_ids_returns_empty(chroma_dir):
    query = encode(["anything"])[0]
    results = search(document_ids=[], query_embedding=query)
    assert results == []


def test_search_nonexistent_document_returns_empty(chroma_dir):
    query = encode(["anything"])[0]
    results = search(document_ids=[99999], query_embedding=query)
    assert results == []


# --- Full pipeline: task generates searchable embeddings ---

@pytest.mark.django_db
def test_process_document_generates_searchable_embeddings(user, tmp_path, settings, sample_pdf_bytes, chroma_dir):
    settings.MEDIA_ROOT = str(tmp_path)
    from apps.documents.tasks import process_document

    pdf_file = SimpleUploadedFile("embed_test.pdf", sample_pdf_bytes, content_type="application/pdf")
    document = Document.objects.create(owner=user, title="Embed Test", file=pdf_file)

    process_document.apply(args=[document.pk])

    document.refresh_from_db()
    assert document.status == Document.Status.READY

    query_embedding = encode(["programming language"])[0]
    results = search(document_ids=[document.pk], query_embedding=query_embedding, top_k=3)

    assert len(results) > 0
    assert results[0].document_id == document.pk
    assert results[0].page_number == 1
    assert isinstance(results[0].score, float)
