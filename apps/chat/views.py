from django_ratelimit.core import is_ratelimited
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Conversation, Message
from .serializers import ChatRequestSerializer, ConversationSerializer, MessageSerializer
from .services.llm_service import answer
from .services.retriever import retrieve


def _check_rate_limit(request: Request) -> bool:
    return is_ratelimited(
        request,
        group="chat-post",
        key=lambda _group, r: str(r.user.pk),
        rate="10/m",
        method="POST",
        increment=True,
    )


class ChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        if _check_rate_limit(request):
            return Response(
                {"status": "error", "data": {}, "message": "Rate limit exceeded. Try again in a minute."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"status": "error", "data": serializer.errors, "message": "Invalid data."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        question: str = serializer.validated_data["question"]
        document_ids: list[int] | None = serializer.validated_data.get("document_ids")
        conversation_id: int | None = serializer.validated_data.get("conversation_id")

        chunks = retrieve(question=question, user=request.user, document_ids=document_ids)

        if not chunks and document_ids is not None:
            return Response(
                {"status": "error", "data": {}, "message": "No ready documents found for the provided IDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if conversation_id:
            try:
                conversation = Conversation.objects.get(pk=conversation_id, owner=request.user)
            except Conversation.DoesNotExist:
                return Response(
                    {"status": "error", "data": {}, "message": "Conversation not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            conversation = Conversation.objects.create(
                owner=request.user,
                title=question[:100],
            )

        history = [
            {"role": msg.role, "content": msg.content}
            for msg in conversation.messages.order_by("created_at")
        ]

        answer_text, sources = answer(
            question=question,
            chunks=chunks,
            conversation_history=history,
        )

        Message.objects.create(conversation=conversation, role=Message.Role.USER, content=question)
        assistant_msg = Message.objects.create(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content=answer_text,
            sources=sources,
        )

        return Response(
            {
                "status": "success",
                "data": {
                    "conversation_id": conversation.pk,
                    "answer": answer_text,
                    "sources": sources,
                    "message_id": assistant_msg.pk,
                },
                "message": "",
            }
        )


class ConversationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        conversations = Conversation.objects.filter(owner=request.user)
        return Response(
            {
                "status": "success",
                "data": ConversationSerializer(conversations, many=True).data,
                "message": "",
            }
        )


class MessageListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, conversation_id: int) -> Response:
        try:
            conversation = Conversation.objects.get(pk=conversation_id, owner=request.user)
        except Conversation.DoesNotExist:
            return Response(
                {"status": "error", "data": {}, "message": "Conversation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "status": "success",
                "data": MessageSerializer(conversation.messages.all(), many=True).data,
                "message": "",
            }
        )
