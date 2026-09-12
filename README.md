# PaperReader v2.1.9

English | [简体中文](docs/zh-cn/README.zh-cn.md)

[Download Windows / macOS v2.1.9](https://github.com/Mars-Dingdang/PaperReader/releases/tag/v2.1.9) · [Upgrade guide](docs/UPGRADING.md) · [Release notes](docs/releases/v2.1.9.md)

> 📖 **Please read the [User Guide (中文)](docs/user_instruction.md) before downloading.** It covers installation (including the Windows "unblock ZIP" step that prevents most launch failures), first-run provider setup, paper submission, history, artifacts, and AI chat.

v2.1.9 upgrades the reader itself: in-document search, persistent annotations with Markdown note export, reading-position memory, synced dual-pane scrolling, streamed AI answers with clickable citations, library-wide full-text search, BibTeX export, and a figure gallery — on top of a PDF renderer that now loads pages on demand. See the [release notes](docs/releases/v2.1.9.md) for details. Frontend/API package version: `2.1.9`.

![](./images/demo1.png)

PaperReader is a full-stack bilingual paper-reading app. Upload a PDF or a LaTeX source; PaperReader parses it (MinerU cloud API for PDFs), translates it with an LLM while preserving formulas, figures, and tables, compiles the result back into a PDF, and lets you read both versions side by side and chat with the paper.

## Desktop quick start

- **Windows**: download the ZIP from the release page, extract the complete archive, and run `PaperReader.exe`. If it fails to open, unblock the ZIP first — see the [User Guide](docs/user_instruction.md).
- **macOS (Apple Silicon)**: open the DMG and copy PaperReader to Applications.
- Both builds open a first-run wizard for your LLM and [MinerU](https://mineru.net/apiManage/docs) credentials; everything else is bundled.
- Translated PDF generation additionally requires [TeX Live](https://www.tug.org/texlive/) with `latexmk` installed on the host.
- Platform guides: [Windows](desktop/README_zh.md) · [macOS](desktop/README_macos_zh.md)

## Features

- Username/password accounts with remember-me sessions and a personal center (avatar, password, per-user LLM / MinerU / parser / vision settings); keys are stored encrypted and never returned to the frontend
- Persistent per-user history in local SQLite; processed files reopen after a restart
- Upload `.pdf`, single `.tex`, individual TeX project files, or a complete `.zip` / `.tar` / `.tar.gz` / `.tgz` LaTeX archive; LaTeX source is preferred for arXiv papers because it preserves structure better than PDF extraction
- PDF parsing via the MinerU cloud API — no local OCR or GPU required
- Concurrent LLM translation with validated per-chunk checkpoints and automatic retry; failed documents resume from the last checkpoint instead of starting over
- Four-layer LaTeX failure prevention: prose sanitizer → strict-then-fallback compile → bounded model repair → in-browser manual TeX editor
- Optional vision-model adversarial check on each page (auto / manual review modes, off by default)
- Side-by-side original/translated PDF reader with outlines (bookmarks or backend-parsed section structure), selectable text, trackpad zoom, on-demand page rendering, and a progress bar with stage breakdown, ETA, and failure diagnosis
- In-document search (Ctrl/Cmd+F) with match navigation across the whole file
- Persistent colored annotations with optional notes, restored on reopen, exportable as a bilingual Markdown reading-notes file
- Reading-position memory: reopen a document where you left off
- Optional synced dual-pane scrolling driven by the bilingual alignment index; counterpart highlighting lands near the passage you selected instead of always at the start of the block
- Figure gallery: every parsed figure and table as a thumbnail strip that jumps to its page
- Selection menu with "ask AI" that grounds the answer in the selected passage and its neighbors; streamed answers with clickable citation badges that jump back to the source text
- Library-wide full-text search across all parsed documents, opening the match at its location
- Paper metadata (title/authors/year/venue) via Semantic Scholar with one-click BibTeX export — or the project's own `.bib` for LaTeX submissions
- Artifact panel with reference preview and drag-into-PDF-pane, plus template prompts (Highlight / Baseline / Limitations)
- AI chat with paper context via any OpenAI-compatible API; Markdown, GitHub-flavored tables, and KaTeX math in both bubbles
- Light / dark theme persisted per account
- Native desktop apps (WebView2 on Windows, WKWebView on macOS arm64) with persistent local sessions

## Documentation

| Document | Content |
| --- | --- |
| [User Guide (中文)](docs/user_instruction.md) | Installation, setup, and usage — read before downloading |
| [Developer Docs](docs/DEVELOPMENT.md) | Building from source, packaging and release process, project structure, environment variables, API reference |
| [Upgrade Guide](docs/UPGRADING.md) | Migrating between versions |
| [Release notes](docs/releases/) ([中文](docs/zh-cn/releases/)) | Per-version changes |
