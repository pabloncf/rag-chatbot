import logging

from celery import shared_task
from django.apps import apps

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_document(self, document_id: int) -> None:
    """Parse PDF, split into chunks, generate embeddings, and store in ChromaDB."""
    Document = apps.get_model("documents", "Document")
    DocumentChunk = apps.get_model("documents", "DocumentChunk")

    try:
        document = Document.objects.get(pk=document_id)
        document.status = Document.Status.PROCESSING
        document.save(update_fields=["status", "updated_at"])

        from .services.chunker import chunk_pages
        from .services.pdf_parser import parse_pdf

        pages, page_count = parse_pdf(document.file.path)
        document.page_count = page_count
        document.save(update_fields=["page_count", "updated_at"])

        chunks = chunk_pages(pages)
        DocumentChunk.objects.bulk_create(
            [
                DocumentChunk(
                    document=document,
                    content=chunk.content,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                )
                for chunk in chunks
            ]
        )

        from apps.embeddings.services.embedding_service import encode
        from apps.embeddings.services.vector_store import add_documents

        db_chunks = list(DocumentChunk.objects.filter(document=document).order_by("chunk_index"))
        embeddings = encode([c.content for c in db_chunks])

        add_documents(
            document_id=document.pk,
            chunks=[
                {
                    "chunk_id": db_chunk.pk,
                    "content": db_chunk.content,
                    "page_number": db_chunk.page_number,
                    "embedding": embedding,
                }
                for db_chunk, embedding in zip(db_chunks, embeddings)
            ],
        )

        document.status = Document.Status.READY
        document.save(update_fields=["status", "updated_at"])

        logger.info(
            "Document %d processed: %d chunks, %d embeddings stored.",
            document_id,
            len(db_chunks),
            len(embeddings),
        )

    except Document.DoesNotExist:
        logger.error("Document %d not found.", document_id)

    except Exception as exc:
        logger.error("Error processing document %d: %s", document_id, exc)
        try:
            document = Document.objects.get(pk=document_id)
            document.status = Document.Status.ERROR
            document.error_message = str(exc)
            document.save(update_fields=["status", "error_message", "updated_at"])
        except Document.DoesNotExist:
            pass
        raise self.retry(exc=exc, countdown=60)
