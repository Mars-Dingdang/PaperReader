import mimetypes
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_auth import router as auth_router
from app.api.routes_chat import router as chat_router
from app.api.routes_data import router as data_router
from app.api.routes_document import router as document_router
from app.api.routes_project import router as project_router
from app.api.routes_recompile import router as recompile_router
from app.api.routes_review import router as review_router
from app.api.routes_upload import router as upload_router
from app.core.config import settings
from app.core.database import init_database


# Windows' MIME registry can classify ES module files as text/plain. PDF.js
# loads its worker from a bundled .mjs asset, and Chromium rejects module
# workers unless they are served with a JavaScript MIME type.
mimetypes.add_type("text/javascript", ".mjs")


app = FastAPI(title="PaperReader", version="2.0.0")

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

app.include_router(data_router, tags=["data"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": "PaperReader", "version": app.version}


# The development UI is served by Vite on port 5173.  A packaged desktop build
# points PAPERREADER_FRONTEND_DIR at the compiled frontend and serves it from
# the same process, removing the Node.js runtime requirement for end users.
_frontend_override = os.environ.get("PAPERREADER_FRONTEND_DIR", "").strip()
_frontend_dir = (
    Path(_frontend_override)
    if _frontend_override
    else Path(__file__).resolve().parents[3] / "frontend" / "dist"
)
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
