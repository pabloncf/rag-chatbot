from rest_framework import serializers

from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ("id", "role", "content", "sources", "created_at")
        read_only_fields = ("id", "role", "content", "sources", "created_at")


class ConversationSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ("id", "title", "message_count", "created_at", "updated_at")
        read_only_fields = ("id", "title", "message_count", "created_at", "updated_at")

    def get_message_count(self, obj: Conversation) -> int:
        return obj.messages.count()


class ChatRequestSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000)
    document_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_null=True,
        default=None,
    )
    conversation_id = serializers.IntegerField(required=False, allow_null=True, default=None)
