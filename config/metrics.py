from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat.models import Conversation, Message
from apps.documents.models import Document


class MetricsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        user = request.user
        return Response(
            {
                "status": "success",
                "data": {
                    "documents": Document.objects.filter(owner=user).count(),
                    "conversations": Conversation.objects.filter(owner=user).count(),
                    "messages": Message.objects.filter(conversation__owner=user).count(),
                },
                "message": "",
            }
        )
