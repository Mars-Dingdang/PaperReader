# Repository Guidelines

## Project Structure & Module Organization
`backend/app` contains the FastAPI service. Keep API routes in `backend/app/api`, shared settings and DB bootstrapping in `backend/app/core`, persistence models in `backend/app/models`, and pipeline logic in `backend/app/services`. Put Python tests in `backend/tests` using the existing `test_*.py` pattern. `frontend/src` contains the React/Vite app: page-level containers live in `pages`, reusable UI in `components`, and HTTP helpers in `lib`. Runtime data and generated artifacts are stored under `data/`; do not commit temporary outputs from local runs.

## Build, Test, and Development Commands
Use the project environment first: `conda activate d2l`.

- `make backend`: run FastAPI with reload from `backend/`.
- `make frontend`: start the Vite dev server from `frontend/`.
- `make worker`: start the optional Celery worker.
- `pytest`: run backend tests in `backend/tests`.
- `python -m compileall backend/app`: quick Python syntax check.
- `npm --prefix frontend install`: install frontend dependencies.
- `npm --prefix frontend run build`: type-check and build the frontend bundle.

## Coding Style & Naming Conventions
Follow the style already in the touched files. Python uses 4-space indentation, `snake_case` modules, and typed functions where practical. React/TypeScript uses 2-space indentation, `PascalCase` component files such as `ReaderPage.tsx`, and colocated imports from `./components`, `./pages`, and `./lib`. Keep route modules named `routes_*.py` and prefer small service helpers over adding logic directly inside route handlers.

## Testing Guidelines
Backend changes should ship with `pytest` coverage when behavior changes or regressions are possible. Add tests beside related backend behavior, for example `backend/tests/test_mineru_service.py`. Frontend has no first-party test runner configured, so at minimum run `npm --prefix frontend run build` for UI changes and include manual verification notes for upload, reader, chat, or profile flows you touched.

## Commit & Pull Request Guidelines
Recent history uses short, direct messages such as `fixed upload problems` and `enabled dark mode`. Prefer concise, imperative commits focused on one change set. PRs should include a summary, affected areas (`backend`, `frontend`, or both), test evidence, linked issues if any, and screenshots for visible UI updates.

## Security & Configuration Tips
Copy `.env.example` to `.env` and keep secrets out of Git. Validate `OPENAI_*`, `MINERU_API_KEY`, and `AUTH_SECRET_KEY` before local runs. Treat files under `data/uploads` and `data/outputs` as user data, not sample assets.
