import io
from unittest.mock import patch

import fitz
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.documents.models import Document, DocumentChunk
from apps.documents.services.chunker import chunk_pages
from apps.documents.services.pdf_parser import ParsedPage, parse_pdf

User = get_user_model()

UPLOAD_URL = "/api/documents/upload/"
LIST_URL = "/api/documents/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="docuser@example.com", password="StrongPass123!")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(email="other@example.com", password="StrongPass123!")


@pytest.fixture
def auth_client(api_client, user):
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return api_client


@pytest.fixture
def sample_pdf_bytes():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello World. " * 60)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# --- Upload endpoint ---

@pytest.mark.django_db
def test_upload_valid_pdf(auth_client, sample_pdf_bytes):
    with patch("apps.documents.views.process_document.delay") as mock_delay:
        pdf_file = SimpleUploadedFile("test.pdf", sample_pdf_bytes, content_type="application/pdf")
        response = auth_client.post(UPLOAD_URL, {"file": pdf_file}, format="multipart")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["status"] == "pending"
    mock_delay.assert_called_once()


@pytest.mark.django_db
def test_upload_non_pdf_extension(auth_client):
    txt_file = SimpleUploadedFile("test.txt", b"hello world", content_type="text/plain")
    response = auth_client.post(UPLOAD_URL, {"file": txt_file}, format="multipart")
    assert response.status_code == 400


@pytest.mark.django_db
def test_upload_fake_pdf_magic_bytes(auth_client):
    fake_file = SimpleUploadedFile("fake.pdf", b"FAKE content here", content_type="application/pdf")
    response = auth_client.post(UPLOAD_URL, {"file": fake_file}, format="multipart")
    assert response.status_code == 400
    assert "valid PDF" in response.json()["message"]


@pytest.mark.django_db
def test_upload_oversized_pdf(auth_client):
    big_content = b"%PDF" + b"x" * (10 * 1024 * 1024 + 1)
    big_file = SimpleUploadedFile("big.pdf", big_content, content_type="application/pdf")
    response = auth_client.post(UPLOAD_URL, {"file": big_file}, format="multipart")
    assert response.status_code == 400
    assert "10 MB" in response.json()["message"]


@pytest.mark.django_db
def test_upload_requires_auth(api_client, sample_pdf_bytes):
    pdf_file = SimpleUploadedFile("test.pdf", sample_pdf_bytes, content_type="application/pdf")
    response = api_client.post(UPLOAD_URL, {"file": pdf_file}, format="multipart")
    assert response.status_code == 401


# --- List / Detail endpoints ---

@pytest.mark.django_db
def test_list_documents(auth_client, user):
    Document.objects.create(owner=user, title="Doc A", file="a.pdf")
    Document.objects.create(owner=user, title="Doc B", file="b.pdf")
    response = auth_client.get(LIST_URL)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert len(response.json()["data"]) == 2


@pytest.mark.django_db
def test_list_documents_isolation(auth_client, user, other_user):
    Document.objects.create(owner=user, title="Mine", file="mine.pdf")
    Document.objects.create(owner=other_user, title="Theirs", file="theirs.pdf")
    response = auth_client.get(LIST_URL)
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Mine"


@pytest.mark.django_db
def test_document_detail_not_found(auth_client):
    response = auth_client.get("/api/documents/9999/")
    assert response.status_code == 404


# --- Rate limit ---

@pytest.mark.django_db
def test_upload_rate_limit_blocks_after_threshold(auth_client, sample_pdf_bytes, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    from django.core.cache import cache
    cache.clear()

    with patch("apps.documents.views.process_document.delay"):
        for _ in range(5):
            pdf_file = SimpleUploadedFile("test.pdf", sample_pdf_bytes, content_type="application/pdf")
            resp = auth_client.post(UPLOAD_URL, {"file": pdf_file}, format="multipart")
            assert resp.status_code == 201

        pdf_file = SimpleUploadedFile("test.pdf", sample_pdf_bytes, content_type="application/pdf")
        resp = auth_client.post(UPLOAD_URL, {"file": pdf_file}, format="multipart")

    assert resp.status_code == 429
    assert "rate limit" in resp.json()["message"].lower()


# --- Service unit tests ---

def test_pdf_parser(tmp_path, sample_pdf_bytes):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(sample_pdf_bytes)
    pages, total_pages = parse_pdf(str(pdf_path))
    assert total_pages == 1
    assert len(pages) == 1
    assert "Hello World" in pages[0].text
    assert pages[0].page_number == 1


def test_chunker_produces_multiple_chunks():
    pages = [ParsedPage(page_number=1, text="word " * 600)]
    chunks = chunk_pages(pages, chunk_size=500, overlap=50)
    assert len(chunks) >= 2
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1


def test_chunker_overlap_is_applied():
    words = [f"w{i}" for i in range(600)]
    pages = [ParsedPage(page_number=1, text=" ".join(words))]
    chunks = chunk_pages(pages, chunk_size=500, overlap=50)
    # With step=450, chunk 1 starts at word 450, overlapping 50 words with chunk 0
    chunk0_last_word = chunks[0].content.split()[-1]
    chunk1_first_word = chunks[1].content.split()[0]
    assert chunk1_first_word == "w450"
    assert chunk0_last_word == "w499"


def test_chunker_short_text_single_chunk():
    pages = [ParsedPage(page_number=1, text="short text here")]
    chunks = chunk_pages(pages)
    assert len(chunks) == 1
    assert chunks[0].content == "short text here"


def test_chunker_preserves_page_number():
    pages = [
        ParsedPage(page_number=1, text="first page " * 10),
        ParsedPage(page_number=2, text="second page " * 10),
    ]
    chunks = chunk_pages(pages, chunk_size=100, overlap=10)
    page_numbers = {c.page_number for c in chunks}
    assert 1 in page_numbers
    assert 2 in page_numbers


# --- Task integration test ---

@pytest.mark.django_db
def test_process_document_task(user, tmp_path, settings, sample_pdf_bytes):
    settings.MEDIA_ROOT = str(tmp_path)
    from apps.documents.tasks import process_document

    pdf_file = SimpleUploadedFile("task_test.pdf", sample_pdf_bytes, content_type="application/pdf")
    document = Document.objects.create(owner=user, title="Task Test", file=pdf_file)

    process_document.apply(args=[document.pk])

    document.refresh_from_db()
    assert document.status == Document.Status.READY
    assert document.page_count == 1
    assert document.chunks.count() > 0
