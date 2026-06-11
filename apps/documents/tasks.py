import logging

from celery import shared_task
from django.apps import apps

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_document(self, document_id: int) -> None:
    """Parse PDF, split into chunks, and persist to database."""
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

        document.status = Document.Status.READY
        document.save(update_fields=["status", "updated_at"])

        logger.info("Document %d processed: %d chunks created.", document_id, len(chunks))

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
