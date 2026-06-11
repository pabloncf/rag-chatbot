from django.http import JsonResponse
from django.urls import path


def health_check(request):
    return JsonResponse(
        {
            "status": "success",
            "data": {"service": "rag-chatbot", "version": "1.0.0"},
            "message": "Service is healthy",
        }
    )


urlpatterns = [
    path("api/health/", health_check, name="health-check"),
]
