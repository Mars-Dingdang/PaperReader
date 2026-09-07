# Upgrading to PaperReader v2.0

## Version boundaries

- `v1.0` freezes the previous `main` at `dd21e24438b11844e964e2ad038b1917c3b835c3`. Its source is preserved unchanged on `release/v1.0`.
- `v2.0` includes the authenticated/persistent `feat_fix` baseline and the compatible translation, reader AI, and Windows changes from PRs #4, #5, and #6. The reverted first translation attempt is not reapplied.
- Frontend/package and API versions are `2.0.0`; the Git tag and release are named `v2.0`.

## Before upgrading

Stop the backend and optional worker. Copy the entire existing data directory and `.env` somewhere safe. `DATA_DIR` is resolved relative to the repository root, not the backend working directory. The historical default without a `.env` was `../data`; an existing `.env` can point elsewhere. Preserve the actual directory, including `uploads`, `outputs`, `paperreader.db` (if present), and `chat_sessions.json` (if present).

Keep the same `DATA_DIR`, `SQLITE_DB_NAME`, and `AUTH_SECRET_KEY` when upgrading an authenticated `feat_fix` installation. The database schema and encrypted settings format are unchanged. Changing the secret makes stored API keys unreadable. Source and generated TeX paths can be absolute, so keep the original data location when reusing an existing SQLite database. Do not merely copy that database to a different OS or folder and expect its absolute paths to be rewritten.

## Source / web installation

Use Python 3.11 (3.12 is also checked in CI), Node.js 20, and the existing TeX Live / XeLaTeX / latexmk installation. After switching to v2.0:

```sh
conda activate d2l
python -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

Keep your existing `.env`; add desired new options from `.env.example` instead of overwriting credentials or paths. An old configuration with `MINERU_API_KEY` and no `PDF_PARSER` retains MinerU parsing. New installations explicitly use `PDF_PARSER=local`. Set `PDF_PARSER=mineru` to opt into cloud layout parsing.

`make backend` / `make frontend` remain supported. A built frontend is also served by FastAPI at port 8000. Production builds use same-origin API and file URLs by default, including `127.0.0.1` in the Windows app. For a separately hosted UI, set `VITE_BACKEND_URL` at frontend build time and configure `CORS_ORIGINS` on the backend. Keep UI and API on the same site for the existing SameSite=Lax cookie policy.

## Moving from the anonymous v1.0 release

v2.0 requires an account. Existing API clients must log in at `/api/auth/login` and retain the session cookie. Upload/document/project routes and the legacy `{document_id, message}` chat request remain supported after authentication. `/data/...` URLs retain their form but require the owning account's cookie; PDF.js clients on a separate origin must enable `withCredentials`.

v1.0 kept its document/project catalog in Python memory. It did **not** persist usernames, original filename mappings, chat history, or task state. Information already lost at shutdown cannot be recovered automatically. Existing uploaded/generated files remain usable and are never deleted by the upgrade.

To restore readable old `outputs/<document UUID>/original.pdf` and `translated.pdf` pairs into a new account:

1. Start v2.0 with the existing `DATA_DIR`, register the destination account, then stop the server.
2. From `backend`, preview the import and then apply it:

   ```sh
   python -m app.services.legacy_import --username YOUR_ACCOUNT
   python -m app.services.legacy_import --username YOUR_ACCOUNT --apply
   ```

The importer only adds database records. It keeps existing files and URLs, skips all already-indexed IDs (including deleted records), and never reassigns another user's document. Recovered names are `legacy-<id>.pdf` because v1.0 did not save the original mapping; rename them in the reader. PDFs with no readable original are reported and left untouched. Uploads that never produced an original PDF and multi-file TeX project metadata must be uploaded again. The importer does not resume interrupted translations or recreate missing chat history.

## Windows portable application

Download `PaperReader-v2.0.0-Windows-x64.zip` and its `.sha256` file from the v2.0 release. Compare the hash with `Get-FileHash -Algorithm SHA256`. Extract the **whole** ZIP to a writable folder and run `PaperReader.exe`; Python and Node.js are bundled/not needed on the recipient's computer.

Windows 10/11 x64 is the target. Microsoft Edge supplies the app window; otherwise the default browser opens. TeX Live with `latexmk` and `xelatex` remains an external requirement for translated PDF generation. Cloud translation/online retrieval requires connectivity and your own provider credentials. The EXE is unsigned and the release does not claim an Authenticode signature.

For upgrades between portable builds, keep the application/data location stable and preserve `config.env` and `data/`. Extract into a separate staging directory, then replace only application files after closing PaperReader. Do not overwrite your configuration with the new sample. Each recipient must use their own local data and credentials.

## Rollback

Stop v2.0, switch to `v1.0` or `release/v1.0`, and restore the matching pre-upgrade `.env` and data backup. v1.0 does not understand the authenticated v2.0 catalog; its original in-memory behavior is retained. Keep the v2.0 data copy if you may return to v2.0.

## Verification scope

CI runs backend regression checks on Linux, macOS, and Windows with Python 3.11, plus Linux with Python 3.12. The Windows job builds a fresh frontend and executable, extracts the ZIP to a path containing spaces/Chinese characters, then checks HTML/JS, PDF-worker MIME, cookies, upload/read, account isolation, settings, chat persistence, login/logout and process restart. It publishes only after those jobs succeed.

The private `homework7.mmd` regression is skipped when unavailable. External MinerU/LLM calls, human review of real-paper translation quality, the interactive Edge taskbar icon and Windows 10 specifically are not exercised by the headless packaged smoke test. Existing unit tests cover translation splitting/retry, layout conversion and failed-PDF compilation safety.
