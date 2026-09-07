"""Explicitly index v1.0 output folders for an existing v2.0 account.

No files are moved, rewritten, or assigned automatically at startup. Run while
the server is stopped, using the same DATA_DIR as the v2.0 server.
"""

import argparse
import uuid
from pathlib import Path
from urllib.parse import quote

from pypdf import PdfReader

from app.core.config import settings
from app.core.database import db_cursor
from app.models.store import ArtifactEntry, DocumentRecord, save_document


def _pdf_text(path: Path) -> str | None:
    try:
        reader = PdfReader(path)
        if not reader.pages:
            return None
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return None


def import_legacy_outputs(username: str, *, apply: bool = False) -> list[dict]:
    with db_cursor() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE lower(username) = lower(?)", (username,)
        ).fetchone()
        existing = {row[0] for row in conn.execute("SELECT document_id FROM documents")}
    if user is None:
        raise ValueError("Register the destination account in v2.0 first")

    results = []
    for folder in sorted(settings.output_dir.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        try:
            uuid.UUID(folder.name)
        except ValueError:
            continue
        if folder.name in existing:
            results.append({"document_id": folder.name, "status": "already indexed"})
            continue
        original = folder / "original.pdf"
        # v1 has no persistent catalog: only folders with a readable original
        # can be recovered without guessing which separate upload they belong to.
        if original.is_symlink():
            continue
        text = _pdf_text(original)
        if text is None:
            results.append({"document_id": folder.name, "status": "no readable original.pdf"})
            continue
        translated = folder / "translated.pdf"
        translated_text = None if translated.is_symlink() else _pdf_text(translated)
        prefix = f"/data/{settings.output_dir_name}/{folder.name}"
        artifacts = []
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
                continue
            relative = path.relative_to(folder).as_posix()
            kind = {"original.pdf": "original_pdf", "translated.pdf": "translated_pdf",
                    "translated.tex": "translated_tex"}.get(relative, "legacy_output")
            if relative == "translated.pdf" and translated_text is None:
                continue
            artifacts.append(ArtifactEntry(path.name, kind, str(path), f"{prefix}/{quote(relative)}"))
        record = DocumentRecord(
            document_id=folder.name, owner_user_id=int(user["id"]),
            source_type="pdf", source_path=original,
            source_filename=f"legacy-{folder.name[:8]}.pdf", status="done",
            original_pdf_url=f"{prefix}/original.pdf",
            translated_pdf_url=f"{prefix}/translated.pdf" if translated_text is not None else None,
            extracted_text=text, translated_text=translated_text or "", artifacts=artifacts,
            size_bytes=original.stat().st_size, progress=100,
            logs=["Imported v1.0 output files; original filename and in-memory history were not persisted."],
        )
        tex = folder / "translated.tex"
        if tex.is_file() and not tex.is_symlink():
            record.translated_tex_path = tex
        if apply:
            save_document(record)
        results.append({"document_id": folder.name, "status": "imported" if apply else "would import"})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--apply", action="store_true", help="Index files; default is preview only")
    args = parser.parse_args()
    for item in import_legacy_outputs(args.username, apply=args.apply):
        print(f"{item['document_id']}: {item['status']}")


if __name__ == "__main__":
    main()
