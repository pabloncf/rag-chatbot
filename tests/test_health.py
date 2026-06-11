import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_check_returns_200(client):
    response = client.get("/api/health/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_health_check_response_structure(client):
    response = client.get("/api/health/")
    data = response.json()

    assert data["status"] == "success"
    assert data["data"]["service"] == "rag-chatbot"
    assert data["data"]["version"] == "1.0.0"
    assert "message" in data
