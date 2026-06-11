import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()

REGISTER_URL = "/api/auth/register/"
LOGIN_URL = "/api/auth/login/"
REFRESH_URL = "/api/auth/refresh/"
ME_URL = "/api/auth/me/"

VALID_PASSWORD = "StrongPass123!"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def registered_user(db):
    return User.objects.create_user(email="existing@example.com", password=VALID_PASSWORD)


@pytest.fixture
def auth_client(api_client, registered_user):
    response = api_client.post(
        LOGIN_URL,
        {"email": "existing@example.com", "password": VALID_PASSWORD},
        format="json",
    )
    token = response.json()["data"]["tokens"]["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client, response.json()["data"]["tokens"]


# --- Registration ---

@pytest.mark.django_db
def test_register_valid_data(api_client):
    response = api_client.post(
        REGISTER_URL,
        {"email": "new@example.com", "password": VALID_PASSWORD, "password_confirm": VALID_PASSWORD},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "success"
    assert "access" in body["data"]["tokens"]
    assert "refresh" in body["data"]["tokens"]
    assert body["data"]["user"]["email"] == "new@example.com"


@pytest.mark.django_db
def test_register_duplicate_email(api_client, registered_user):
    response = api_client.post(
        REGISTER_URL,
        {"email": "existing@example.com", "password": VALID_PASSWORD, "password_confirm": VALID_PASSWORD},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["status"] == "error"


@pytest.mark.django_db
def test_register_password_mismatch(api_client):
    response = api_client.post(
        REGISTER_URL,
        {"email": "new@example.com", "password": VALID_PASSWORD, "password_confirm": "DifferentPass456!"},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["status"] == "error"


# --- Login ---

@pytest.mark.django_db
def test_login_valid_credentials(api_client, registered_user):
    response = api_client.post(
        LOGIN_URL,
        {"email": "existing@example.com", "password": VALID_PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "access" in body["data"]["tokens"]
    assert "refresh" in body["data"]["tokens"]


@pytest.mark.django_db
def test_login_invalid_credentials(api_client):
    response = api_client.post(
        LOGIN_URL,
        {"email": "nobody@example.com", "password": "wrongpassword"},
        format="json",
    )
    assert response.status_code == 401
    assert response.json()["status"] == "error"


# --- Me endpoint ---

@pytest.mark.django_db
def test_me_with_valid_token(auth_client):
    client, _ = auth_client
    response = client.get(ME_URL)
    assert response.status_code == 200
    assert response.json()["data"]["email"] == "existing@example.com"


@pytest.mark.django_db
def test_me_without_token(api_client):
    response = api_client.get(ME_URL)
    assert response.status_code == 401


# --- Rate limits ---

@pytest.mark.django_db
def test_login_rate_limit_blocks_after_threshold(api_client, registered_user, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    from django.core.cache import cache
    cache.clear()

    for _ in range(10):
        resp = api_client.post(
            LOGIN_URL,
            {"email": "existing@example.com", "password": VALID_PASSWORD},
            format="json",
        )
        assert resp.status_code == 200

    resp = api_client.post(
        LOGIN_URL,
        {"email": "existing@example.com", "password": VALID_PASSWORD},
        format="json",
    )
    assert resp.status_code == 429
    assert "login attempts" in resp.json()["message"].lower()


@pytest.mark.django_db
def test_register_rate_limit_blocks_after_threshold(api_client, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    from django.core.cache import cache
    cache.clear()

    for i in range(5):
        resp = api_client.post(
            REGISTER_URL,
            {"email": f"new{i}@example.com", "password": VALID_PASSWORD, "password_confirm": VALID_PASSWORD},
            format="json",
        )
        assert resp.status_code == 201

    resp = api_client.post(
        REGISTER_URL,
        {"email": "blocked@example.com", "password": VALID_PASSWORD, "password_confirm": VALID_PASSWORD},
        format="json",
    )
    assert resp.status_code == 429
    assert "registration attempts" in resp.json()["message"].lower()


# --- Token refresh ---

@pytest.mark.django_db
def test_token_refresh(api_client, auth_client):
    _, tokens = auth_client
    response = api_client.post(REFRESH_URL, {"refresh": tokens["refresh"]}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "access" in body["data"]
