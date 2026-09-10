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

=== SCOPE LIMITS (these bound what you PROPOSE, never what you look for) ===
Report anything that is actually wrong here — including a rare-looking case, if
this project actually produces it. Then keep the fix in scope:
1. This is not a security paper. Verification is welcome; over-defense is not.
   Unless this project states otherwise, assume a cooperating operator on their
   own machine; if it has a real adversary, it will say so and that scope wins.
2. Do not add hashes, checksums or fingerprints unless the hash replaces a
   materially more expensive operation AND its result changes what happens next.
3. No defensive scaffolding: no feature flags, migration frameworks, compat
   layers or wrappers for cases that do not occur here.
4. No corner-case obsession: exotic encodings, symlink races, RTL text and
   millisecond races are out of scope unless the case is reachable through this
   project's supported use — its documented inputs, its published interface, its
   real data. Reachable is enough; you do not need a reproduction. Constructible
   in principle is not enough.
5. Where judgement is needed, judge. Do not replace it with a scoring table, a
   checklist, or a re-verification loop over something already settled.
6. None of this overrides security, migration, verification or review that the
   user, this project's own conventions, or a higher-priority rule asked for.
   Those were requested; they are the work, not scope creep.
7. Deliverable text is not a defense transcript. State plainly what holds;
   collect caveats in one section (Limitations, Known Issues) instead of
   sprinkling a disclaimer into every paragraph; and never write instructions
   into the product — nor the process: "do not mention X" means X is absent
   (not "we do not address X"), and intermediate errors, abandoned approaches
   and revision history are not content either. Lead with the strongest
   result — a paper is a launch, not a progress report. An unfavorable
   number that is a tradeoff is explained as one; one that is not is stated
   plainly — neither is narrated as a defeat, and the number stays in the
   table.
8. Momentum is part of the deliverable. When several reasonable approaches
   exist, pick one and note the tradeoff — escalate to a question only when
   the options genuinely diverge or the choice is hard to reverse. A detail
   that does not block the goal gets recorded, not solved first. Stalling to
   avoid picking wrong is itself a wrong pick.
9. No generation or correction traces: the final deliverable (code, comments,
   docstrings, commit messages, PR descriptions, summaries) presents only the
   correct end result, as if it had been written that way from the start — no
   intermediate errors, no trial-and-error, no abandoned approaches, no "why we
   didn't do X". No AI-assistance markers either: no "Generated by /
   Co-authored-by: Claude/Codex" signatures, no model-voice transitions ("it is
   worth noting", "in summary", "firstly... secondly... finally"), no "here
   is..." openers. Match the wording and level of detail to the project's
   existing style.
Shapes already seen, for calibration. Examples, not a checklist — a real finding
is not dismissed by resembling one:
  H  hashing every row of two spreadsheets to answer what comparing cells answers
  H  writing checksum files that nothing ever reads
  E  hardening the accounts of an app that has no users and no deployment
  R  auditing your own patch all night while the feature stays unwritten
  R  a reviewer that returns a failing verdict on everything
  O  guards whose justification is the previous guard, not the requirement
And two that look like the above and are not. Report these:
  ✓  a digest that lets you skip re-reading a large file you already have
  ✓  a rare-looking input this project's own documentation example produces
Before running any check, answer: what specific failure would this detect, and
what would I do differently if it occurred? No answer means do not run it.
Say plainly when something is correct. Do not manufacture findings.