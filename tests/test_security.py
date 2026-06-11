import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.chat.models import Conversation, Message
from apps.documents.models import Document

User = get_user_model()

METRICS_URL = "/api/metrics/"
HEALTH_URL = "/api/health/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="sec@example.com", password="StrongPass123!")


@pytest.fixture
def auth_client(api_client, user):
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return api_client


# --- Security Headers ---

@pytest.mark.django_db
def test_csp_header_present(api_client):
    response = api_client.get(HEALTH_URL)
    assert "Content-Security-Policy" in response


@pytest.mark.django_db
def test_csp_blocks_inline_scripts(api_client):
    csp = api_client.get(HEALTH_URL)["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp


@pytest.mark.django_db
def test_referrer_policy_header(api_client):
    response = api_client.get(HEALTH_URL)
    assert response["Referrer-Policy"] == "strict-origin-when-cross-origin"


@pytest.mark.django_db
def test_permissions_policy_header(api_client):
    response = api_client.get(HEALTH_URL)
    assert "geolocation=()" in response["Permissions-Policy"]


@pytest.mark.django_db
def test_x_content_type_options_header(api_client):
    response = api_client.get(HEALTH_URL)
    assert response["X-Content-Type-Options"] == "nosniff"


# --- Metrics endpoint ---

@pytest.mark.django_db
def test_metrics_requires_auth(api_client):
    response = api_client.get(METRICS_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_metrics_returns_zero_counts_for_new_user(auth_client):
    response = auth_client.get(METRICS_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["documents"] == 0
    assert data["conversations"] == 0
    assert data["messages"] == 0


@pytest.mark.django_db
def test_metrics_counts_only_own_resources(auth_client, user, db):
    other = User.objects.create_user(email="other@sec.com", password="StrongPass123!")
    Document.objects.create(owner=user, title="Mine", file="a.pdf")
    Document.objects.create(owner=other, title="Theirs", file="b.pdf")
    conv = Conversation.objects.create(owner=user, title="My conv")
    Message.objects.create(conversation=conv, role="user", content="Hi")

    response = auth_client.get(METRICS_URL)
    data = response.json()["data"]
    assert data["documents"] == 1
    assert data["conversations"] == 1
    assert data["messages"] == 1
