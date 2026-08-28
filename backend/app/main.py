from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_auth import router as auth_router
from app.api.routes_chat import router as chat_router
from app.api.routes_document import router as document_router
from app.api.routes_project import router as project_router
from app.api.routes_recompile import router as recompile_router
from app.api.routes_review import router as review_router
from app.api.routes_upload import router as upload_router
from app.core.config import settings
from app.core.database import init_database


app = FastAPI(title="Paper Reader MVP", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_database()

app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(upload_router, prefix="/api", tags=["upload"])
app.include_router(document_router, prefix="/api", tags=["document"])
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(project_router, prefix="/api", tags=["project"])
app.include_router(review_router, prefix="/api", tags=["review"])
app.include_router(recompile_router, prefix="/api", tags=["recompile"])

app.mount("/data", StaticFiles(directory=str(settings.data_dir)), name="data")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
