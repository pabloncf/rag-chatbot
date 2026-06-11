import os

from django.conf import settings
from django_ratelimit.core import is_ratelimited
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Document
from .serializers import DocumentSerializer, DocumentUploadSerializer
from .tasks import process_document

PDF_MAGIC_BYTES = b"%PDF"


def _validate_pdf(file) -> str | None:
    """Return an error message if the file is invalid, None if valid."""
    if not file.name.lower().endswith(".pdf"):
        return "Only PDF files are allowed."
    if file.content_type != "application/pdf":
        return "Invalid content type. Expected application/pdf."
    max_size = getattr(settings, "MAX_UPLOAD_SIZE", 10 * 1024 * 1024)
    if file.size > max_size:
        return f"File size exceeds the {max_size // (1024 * 1024)} MB limit."
    header = file.read(4)
    file.seek(0)
    if header != PDF_MAGIC_BYTES:
        return "File does not appear to be a valid PDF."
    return None


class DocumentUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request: Request) -> Response:
        if is_ratelimited(
            request,
            group="upload-post",
            key=lambda _g, r: str(r.user.pk),
            rate="5/m",
            method="POST",
            increment=True,
        ):
            return Response(
                {"status": "error", "data": {}, "message": "Upload rate limit exceeded. Try again in a minute."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = DocumentUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"status": "error", "data": serializer.errors, "message": "Invalid data."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file = serializer.validated_data["file"]
        error = _validate_pdf(file)
        if error:
            return Response(
                {"status": "error", "data": {}, "message": error},
                status=status.HTTP_400_BAD_REQUEST,
            )

        title = serializer.validated_data.get("title") or os.path.splitext(file.name)[0]
        document = Document.objects.create(owner=request.user, title=title, file=file)
        process_document.delay(document.pk)

        return Response(
            {
                "status": "success",
                "data": DocumentSerializer(document).data,
                "message": "Document uploaded. Processing started.",
            },
            status=status.HTTP_201_CREATED,
        )


class DocumentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        documents = Document.objects.filter(owner=request.user)
        return Response(
            {
                "status": "success",
                "data": DocumentSerializer(documents, many=True).data,
                "message": "",
            }
        )


class DocumentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: int) -> Response:
        try:
            document = Document.objects.get(pk=pk, owner=request.user)
        except Document.DoesNotExist:
            return Response(
                {"status": "error", "data": {}, "message": "Document not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "status": "success",
                "data": DocumentSerializer(document).data,
                "message": "",
            }
        )
