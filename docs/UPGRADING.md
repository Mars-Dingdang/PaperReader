# Upgrading PaperReader

## Upgrading from v2.1.5 to v2.1.6

PaperReader v2.1.6 is backward compatible. Keep the existing `DATA_DIR`, database, `AUTH_SECRET_KEY`, and provider settings. On first start, SQLite adds nullable failure/recovery JSON columns and a retry counter; no manual migration is required. Jobs left in `processing` or `recovering` by an application exit are marked as retryable failures rather than silently remaining stuck.

PDF extraction and verified translation chunks now use atomic checkpoints under each document output directory. Failed translation can resume from the missing chunk, and failed LaTeX compilation reuses the already registered `translated.tex`. The failure panel exposes the stage, chunk, model diagnosis and exact repair history, with a guarded “retry from here” action. Automatic LaTeX repair is enabled by default, limited to two rounds, restricted to compiler-located line windows, and keeps a before-repair backup for every applied round.

Frontend, package-lock root metadata, API, desktop guides, and release notes are synchronized to `2.1.6`; the Git tag is `v2.1.6`.

## Upgrading from v2.1.4 to v2.1.5

PaperReader v2.1.5 is a backward-compatible patch release and requires no data migration. Keep the existing `DATA_DIR`, `SQLITE_DB_NAME`, `AUTH_SECRET_KEY`, account database, and user settings.

v2.1.5 fixes two regressions in the structured (MinerU) translation pipeline. First, documents whose translation reached the TeX rendering step failed with `Error: 'NoneType' object is not iterable`: `create_translated_tex_from_ir` computed OCR math-fault repair notes but returned nothing, and the pipeline's loop over those notes aborted the document right after "Saved N exact bilingual alignment segments". Second, translated PDFs could fail to compile with `Package newunicodechar Error: Invalid argument`: the Unicode sanitizer rewrote the preamble's `\newunicodechar{□}{...}` declarations — whose first argument must remain a single literal character — into e.g. `\newunicodechar{$\square$}`; sanitization is now applied only to the document body between `\begin{document}` and `\end{document}`, which also protects the manual-recompile endpoint. On top of the fixes, LaTeX compile failures now report fatal errors with source line numbers and missing glyphs with suggested replacements, MinerU `\sqrt` OCR faults (radicand swallowed into the root index) are repaired automatically with a logged audit trail, and the translated TeX can be edited in an in-app CodeMirror 6 editor with search & replace, line jumps from compile-error panels, and reveal-in-explorer / open-in-VS-Code actions.

Frontend, package-lock root metadata, API, release smoke checks, and release notes are synchronized to `2.1.5`; the Git tag is `v2.1.5`.

## Upgrading from v2.1.3 to v2.1.4

PaperReader v2.1.4 is a backward-compatible patch release and requires no data migration. Keep the existing `DATA_DIR`, `SQLITE_DB_NAME`, `AUTH_SECRET_KEY`, account database, and user settings.

v2.1.4 is the first Windows package verified to start. Earlier v2.1.x Windows ZIPs could fail before any window appeared: the build environment resolved the unpinned `pythonnet` to 3.1.0, whose `Python.Runtime.dll` the .NET Framework host cannot initialize inside a PyInstaller-frozen app (`Failed to resolve Python.Runtime.Loader.Initialize` in `PaperReader-error.log`), while the release smoke test only exercised the windowless backend (`PAPERREADER_NO_WINDOW=1`). The build now pins `pythonnet 3.0.5` + `clr-loader 0.2.7.post0`, pins `setuptools 65.5.0` for Windows builds (setuptools 80.x vendors a `jaraco.context` whose `backports.tarfile` import crashes the packaged `pkg_resources` runtime hook on Python 3.11), stops a still-running portable app and retries ZIP packaging in `build_portable.ps1` (fixing `Compress-Archive` failures on files locked by another process), saves the PowerShell packaging scripts as UTF-8 with BOM (so `使用说明.txt` and the shortcut description are no longer mojibake on Chinese-locale Windows PowerShell), and smoke-tests the packaged GUI stack via `PAPERREADER_GUI_CHECK=1`. The refreshed v2.1.4 package also bundles the PDF.js CMaps required to display CID-keyed Chinese fonts, prefers a native Windows CJK font when generating translated LaTeX, and suppresses console windows from LaTeX subprocesses. Windows users on any earlier v2.1.x build should download the current v2.1.4 ZIP.

Frontend, package-lock root metadata, API, release smoke checks, and release notes are synchronized to `2.1.4`; the Git tag is `v2.1.4`.

## Upgrading from v2.1.2 to v2.1.3

PaperReader v2.1.3 is a backward-compatible patch release and requires no data migration. Keep the existing `DATA_DIR`, `SQLITE_DB_NAME`, `AUTH_SECRET_KEY`, account database, and user settings.

v2.1.2 could fail the translated-PDF build for projects whose source declares `pdflatex` (for example via arXiv `00README.json`): the declaration was also applied to the translated document, which always requires XeLaTeX because Chinese support (`xeCJK`/`ctex`) is injected into its preamble. v2.1.3 applies declared compilers to the original document only and always compiles translated documents with XeLaTeX. When an arXiv source preamble contains pdfLaTeX-only `\DeclareUnicodeCharacter` directives, PaperReader now adds a native-Unicode XeLaTeX compatibility definition before the first directive; this fixes the remaining failure reproduced by arXiv `2605.18309`. Stale `latexmk` databases (`.fdb_latexmk`) from earlier failed attempts are cleared before each compile pass, and failure messages now report the original strict-pass error instead of the unhelpful `Nothing to do ... gave an error in previous invocation` summary.

Frontend, package-lock root metadata, API, release smoke checks, and release notes are synchronized to `2.1.3`; the Git tag is `v2.1.3`. Original-source compilation behavior is unchanged from v2.1.2.

## Upgrading from v2.1.1 to v2.1.2

PaperReader v2.1.2 is a backward-compatible patch release and requires no data migration. Keep the existing `DATA_DIR`, `SQLITE_DB_NAME`, `AUTH_SECRET_KEY`, account database, and user settings.

The LaTeX compiler selector now respects supported project declarations instead of always forcing XeLaTeX. arXiv source archives may declare `00README.json` → `process.compiler`, and standalone TeX sources may use `% !TeX program = ...`. Supported values are `pdflatex`, `xelatex`, `lualatex`, and `latex`; unsupported or malformed declarations are ignored and fall back to the previous XeLaTeX default. TeX Live, `latexmk`, and whichever selected engine is needed by the source project must be installed on the host.

Frontend, package-lock root metadata, API, release smoke checks, desktop documentation, and release notes are synchronized to `2.1.2`; the Git tag is `v2.1.2`. Existing v2.1.1 behavior is unchanged for projects without compiler declarations.

## Upgrading from v2.1 to v2.1.1

PaperReader v2.1.1 is an additive update and requires no data migration. Keep the existing `DATA_DIR`, `SQLITE_DB_NAME`, and `AUTH_SECRET_KEY`. Existing accounts retain their saved visual-check choice; only newly created accounts and documents now default to visual checking off.

The main upload entry and TeX project dialog now accept `.zip`, `.tar`, `.tar.gz`, and `.tgz` LaTeX projects. Archives are extracted locally with a 20 MB per-file limit, a 200 MB project limit, and a 2,000-member limit. Unsafe paths, links, special files, encrypted ZIP entries, collisions, damage, and packages without `.tex` files are rejected without partial import. Importing only stages files: select and confirm the proposed main `.tex` before building.

The desktop reader now opens PDF HTTP(S) links in the system browser, restores PDF text selection/copy, increases trackpad pinch sensitivity, and generates a section outline when a PDF has text but no native bookmarks. Scanned PDFs without a text layer show an explicit empty outline state.

Release, frontend, API, and desktop versions are `2.1.1`; the Git tag and release notes use the full SemVer tag `v2.1.1`.

## Upgrading from v2.0 to v2.1

PaperReader v2.1 moves desktop state to a per-user application directory and adds account-scoped MinerU/parser/vision settings. The first launch copies a legacy Windows portable `config.env` and `data` directory into `%LOCALAPPDATA%\PaperReader` without deleting the originals. After the first successful login, provider keys are encrypted in that account’s SQLite row and removed from the hidden `.config.env` bootstrap file.

On macOS, state is stored under `~/Library/Application Support/PaperReader`. The first macOS release targets Apple Silicon and macOS 13 or newer. It is ad-hoc signed, not notarized.

For source installations, keep the same `AUTH_SECRET_KEY` and `DATA_DIR`; the additive database migration runs automatically. `.env` remains available for deployment defaults, but personal-center settings take precedence for uploads, project builds, chat, MinerU, and visual checking.

Release versions are `2.1.0`; the Git tag is `v2.1`.

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
