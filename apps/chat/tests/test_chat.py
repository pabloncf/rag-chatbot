import io
from unittest.mock import MagicMock, patch

import fitz
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.chat.models import Conversation, Message
from apps.embeddings.services.vector_store import SearchResult

User = get_user_model()

CHAT_URL = "/api/chat/"
CONVERSATIONS_URL = "/api/chat/conversations/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="chat@example.com", password="StrongPass123!")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(email="other@example.com", password="StrongPass123!")


@pytest.fixture
def auth_client(api_client, user):
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return api_client


@pytest.fixture
def mock_search_result():
    return SearchResult(
        chunk_id=1,
        document_id=1,
        page_number=2,
        content="Python is a high-level programming language.",
        score=0.95,
    )


@pytest.fixture
def mock_rag(mock_search_result):
    """Mock retrieve + answer so tests don't touch ChromaDB or Anthropic."""
    with patch("apps.chat.views.retrieve") as mock_ret, \
         patch("apps.chat.views.answer") as mock_ans:
        mock_ret.return_value = [mock_search_result]
        mock_ans.return_value = (
            "Python is a high-level programming language.",
            [{"chunk_id": 1, "document_id": 1, "page_number": 2}],
        )
        yield mock_ret, mock_ans


@pytest.fixture
def chroma_dir(tmp_path, settings):
    settings.CHROMA_PERSIST_DIRECTORY = str(tmp_path / "chroma")
    import apps.embeddings.services.vector_store as vs
    vs._client = None
    yield str(tmp_path / "chroma")
    vs._client = None


# --- Chat endpoint ---

@pytest.mark.django_db
def test_chat_returns_answer(auth_client, mock_rag):
    response = auth_client.post(CHAT_URL, {"question": "What is Python?"}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "answer" in body["data"]
    assert len(body["data"]["sources"]) > 0
    assert "conversation_id" in body["data"]


@pytest.mark.django_db
def test_chat_creates_conversation_and_messages(auth_client, mock_rag):
    response = auth_client.post(CHAT_URL, {"question": "What is Python?"}, format="json")
    assert response.status_code == 200
    assert Conversation.objects.count() == 1
    assert Message.objects.count() == 2
    messages = list(Message.objects.order_by("created_at"))
    assert messages[0].role == Message.Role.USER
    assert messages[1].role == Message.Role.ASSISTANT
    assert messages[1].sources != []


@pytest.mark.django_db
def test_chat_continues_existing_conversation(auth_client, user, mock_rag):
    conv = Conversation.objects.create(owner=user, title="Existing conv")
    response = auth_client.post(
        CHAT_URL,
        {"question": "Follow-up question", "conversation_id": conv.pk},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["data"]["conversation_id"] == conv.pk
    assert Message.objects.filter(conversation=conv).count() == 2


@pytest.mark.django_db
def test_chat_invalid_conversation_id(auth_client, mock_rag):
    response = auth_client.post(
        CHAT_URL,
        {"question": "Q", "conversation_id": 9999},
        format="json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_chat_no_documents_with_explicit_ids(auth_client):
    with patch("apps.chat.views.retrieve") as mock_ret:
        mock_ret.return_value = []
        response = auth_client.post(
            CHAT_URL,
            {"question": "What is Python?", "document_ids": [999]},
            format="json",
        )
    assert response.status_code == 400
    assert "No ready documents" in response.json()["message"]


@pytest.mark.django_db
def test_chat_no_documents_without_explicit_ids_still_answers(auth_client):
    """When no document_ids provided and user has no docs, answer is still returned (empty context)."""
    with patch("apps.chat.views.retrieve") as mock_ret, \
         patch("apps.chat.views.answer") as mock_ans:
        mock_ret.return_value = []
        mock_ans.return_value = ("I couldn't find relevant information.", [])
        response = auth_client.post(CHAT_URL, {"question": "Q"}, format="json")
    assert response.status_code == 200


@pytest.mark.django_db
def test_chat_requires_auth(api_client):
    response = api_client.post(CHAT_URL, {"question": "Q"}, format="json")
    assert response.status_code == 401


# --- Conversation list ---

@pytest.mark.django_db
def test_conversation_list(auth_client, user):
    Conversation.objects.create(owner=user, title="Conv A")
    Conversation.objects.create(owner=user, title="Conv B")
    response = auth_client.get(CONVERSATIONS_URL)
    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


@pytest.mark.django_db
def test_conversation_list_isolation(auth_client, user, other_user):
    Conversation.objects.create(owner=user, title="Mine")
    Conversation.objects.create(owner=other_user, title="Theirs")
    response = auth_client.get(CONVERSATIONS_URL)
    assert len(response.json()["data"]) == 1


# --- Message list ---

@pytest.mark.django_db
def test_message_list_returns_ordered_messages(auth_client, user):
    conv = Conversation.objects.create(owner=user, title="T")
    Message.objects.create(conversation=conv, role="user", content="Hello")
    Message.objects.create(conversation=conv, role="assistant", content="Hi!")
    response = auth_client.get(f"/api/chat/conversations/{conv.pk}/messages/")
    assert response.status_code == 200
    msgs = response.json()["data"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


@pytest.mark.django_db
def test_message_list_not_found(auth_client):
    response = auth_client.get("/api/chat/conversations/9999/messages/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_message_list_isolation(auth_client, other_user):
    other_conv = Conversation.objects.create(owner=other_user, title="Other")
    response = auth_client.get(f"/api/chat/conversations/{other_conv.pk}/messages/")
    assert response.status_code == 404


# --- Retriever service (real embeddings + ChromaDB) ---

@pytest.mark.django_db
def test_retriever_returns_relevant_chunks(user, tmp_path, settings, chroma_dir):
    settings.MEDIA_ROOT = str(tmp_path)
    from apps.chat.services.retriever import retrieve
    from apps.documents.models import Document, DocumentChunk
    from apps.embeddings.services.embedding_service import encode
    from apps.embeddings.services.vector_store import add_documents

    doc = Document.objects.create(
        owner=user, title="Python Guide", file="guide.pdf",
        status=Document.Status.READY, page_count=1,
    )
    content = "Python is a high-level, general-purpose programming language."
    chunk = DocumentChunk.objects.create(document=doc, content=content, chunk_index=0, page_number=1)
    add_documents(doc.pk, [{"chunk_id": chunk.pk, "content": content, "page_number": 1, "embedding": encode([content])[0]}])

    results = retrieve(question="What is Python?", user=user)

    assert len(results) > 0
    assert results[0].document_id == doc.pk
    assert "Python" in results[0].content


@pytest.mark.django_db
def test_retriever_filters_by_owner(user, other_user, tmp_path, settings, chroma_dir):
    settings.MEDIA_ROOT = str(tmp_path)
    from apps.chat.services.retriever import retrieve
    from apps.documents.models import Document

    Document.objects.create(owner=other_user, title="Other's Doc", file="other.pdf", status=Document.Status.READY)
    results = retrieve(question="anything", user=user)
    assert results == []


# --- LLM service (mocked Anthropic) ---

def test_llm_service_calls_claude_and_returns_sources():
    from apps.chat.services.llm_service import answer

    chunks = [
        SearchResult(chunk_id=1, document_id=1, page_number=3, content="Python is great.", score=0.9)
    ]
    with patch("apps.chat.services.llm_service.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value.content = [MagicMock(text="Great answer!")]

        answer_text, sources = answer(question="What is Python?", chunks=chunks)

    assert answer_text == "Great answer!"
    assert len(sources) == 1
    assert sources[0] == {"chunk_id": 1, "document_id": 1, "page_number": 3}
    mock_client.messages.create.assert_called_once()


def test_llm_service_empty_chunks_skips_api():
    from apps.chat.services.llm_service import answer

    with patch("apps.chat.services.llm_service.anthropic.Anthropic") as mock_cls:
        answer_text, sources = answer(question="Q", chunks=[])
        mock_cls.assert_not_called()

    assert sources == []
    assert "couldn't find" in answer_text.lower()


def test_llm_service_includes_conversation_history():
    from apps.chat.services.llm_service import answer

    chunks = [SearchResult(chunk_id=1, document_id=1, page_number=1, content="Context.", score=0.9)]
    history = [
        {"role": "user", "content": "Previous Q"},
        {"role": "assistant", "content": "Previous A"},
    ]
    with patch("apps.chat.services.llm_service.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value.content = [MagicMock(text="Answer")]

        answer(question="Follow-up", chunks=chunks, conversation_history=history)

    call_kwargs = mock_client.messages.create.call_args
    messages_sent = call_kwargs.kwargs["messages"]
    assert messages_sent[0]["role"] == "user"
    assert messages_sent[0]["content"] == "Previous Q"
    assert messages_sent[1]["role"] == "assistant"


# --- Rate limit ---

@pytest.mark.django_db
def test_rate_limit_blocks_after_threshold(auth_client, mock_rag, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    from django.core.cache import cache
    cache.clear()

    for _ in range(10):
        resp = auth_client.post(CHAT_URL, {"question": "Q"}, format="json")
        assert resp.status_code == 200

    resp = auth_client.post(CHAT_URL, {"question": "Q"}, format="json")
    assert resp.status_code == 429
    assert "Rate limit" in resp.json()["message"]
