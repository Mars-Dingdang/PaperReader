from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_chat import router as chat_router
from app.api.routes_document import router as document_router
from app.api.routes_project import router as project_router
from app.api.routes_recompile import router as recompile_router
from app.api.routes_review import router as review_router
from app.api.routes_upload import router as upload_router
from app.core.config import settings
from app.models.store import load_records


app = FastAPI(title="Paper Reader MVP", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router, prefix="/api", tags=["upload"])
app.include_router(document_router, prefix="/api", tags=["document"])
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(project_router, prefix="/api", tags=["project"])
app.include_router(review_router, prefix="/api", tags=["review"])
app.include_router(recompile_router, prefix="/api", tags=["recompile"])

app.mount("/data", StaticFiles(directory=str(settings.data_dir)), name="data")

# Rebuild the in-memory document list from persisted metadata so previously
# uploaded/processed documents survive a backend restart.
load_records()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
