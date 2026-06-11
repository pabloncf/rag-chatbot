from rest_framework import serializers

from .models import Document


class DocumentSerializer(serializers.ModelSerializer):
    chunk_count = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ("id", "title", "status", "page_count", "chunk_count", "created_at", "updated_at")
        read_only_fields = ("id", "title", "status", "page_count", "chunk_count", "created_at", "updated_at")

    def get_chunk_count(self, obj: Document) -> int:
        return obj.chunks.count()


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
