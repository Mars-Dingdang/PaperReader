from celery import Celery

from app.core.config import settings
from app.models.store import get_document
from app.services.document_pipeline import process_document
from app.services.auth_service import ensure_user_settings


celery_app = Celery("paper_reader", broker=settings.redis_url, backend=settings.redis_url)


@celery_app.task(name="process_document_task")
def process_document_task(document_id: str) -> None:
    record = get_document(document_id)
    if not record:
        return
    process_document(record, provider_settings=ensure_user_settings(record.owner_user_id))
