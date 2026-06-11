from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import RedirectView, TemplateView

from config.metrics import MetricsView


def health_check(request):
    return JsonResponse(
        {
            "status": "success",
            "data": {"service": "rag-chatbot", "version": "1.0.0"},
            "message": "Service is healthy",
        }
    )


urlpatterns = [
    # UI pages
    path("", RedirectView.as_view(url="/chat/", permanent=False), name="home"),
    path("login/", TemplateView.as_view(template_name="login.html"), name="login"),
    path("chat/", TemplateView.as_view(template_name="chat/index.html"), name="chat-ui"),
    # API
    path("api/health/", health_check, name="health-check"),
    path("api/metrics/", MetricsView.as_view(), name="metrics"),
    path("api/auth/", include("apps.users.urls")),
    path("api/documents/", include("apps.documents.urls")),
    path("api/chat/", include("apps.chat.urls")),
]
