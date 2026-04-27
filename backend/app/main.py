from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_chat import router as chat_router
from app.api.routes_document import router as document_router
from app.api.routes_upload import router as upload_router
from app.core.config import settings


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

app.mount("/data", StaticFiles(directory=str(settings.data_dir)), name="data")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
