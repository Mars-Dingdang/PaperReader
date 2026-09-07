"""Probe the maximum sustained request rate / concurrency for the configured
OpenAI-compatible LLM endpoint.

Usage (from repo root, with the `d2l` env activated):

    python scripts/benchmark_llm_rate.py
    python scripts/benchmark_llm_rate.py --duration 20 --max-concurrency 64

The script issues short, cheap chat completions in parallel at progressively
higher concurrency levels. For each level it measures throughput, latency and
the rate of retryable / 429 errors. When error rate stays below the configured
threshold, the level is considered safe and recommended values for
`TRANSLATE_CONCURRENCY` and `LLM_RATE_LIMIT_RPS` are printed at the end.

It only depends on the `openai` package and `python-dotenv` (both already in
`requirements.txt`). It reads the same env vars the backend uses
(`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`).
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional but expected to exist
    load_dotenv = None  # type: ignore[assignment]

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    if load_dotenv is None:
        return
    for candidate in (REPO_ROOT / ".env", REPO_ROOT / ".env.example"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


@dataclass
class LevelResult:
    concurrency: int
    duration_s: float
    completed: int
    succeeded: int
    rate_limited: int
    other_errors: int
    latencies_ms: List[float] = field(default_factory=list)

    @property
    def rps(self) -> float:
        return self.succeeded / self.duration_s if self.duration_s > 0 else 0.0

    @property
    def error_rate(self) -> float:
        return 0.0 if self.completed == 0 else (self.rate_limited + self.other_errors) / self.completed

    @property
    def p50_ms(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        idx = max(0, int(0.95 * len(ordered)) - 1)
        return ordered[idx]


def _is_rate_limited(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return True
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return True
    return False


def _make_client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url)


def _one_call(client: OpenAI, model: str, prompt: str) -> float:
    start = time.perf_counter()
    client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Reply with exactly 'ok'."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=4,
    )
    return (time.perf_counter() - start) * 1000.0


def _run_level(
    client: OpenAI,
    model: str,
    concurrency: int,
    duration_s: float,
    prompt: str,
) -> LevelResult:
    stop_at = time.perf_counter() + duration_s
    result = LevelResult(concurrency=concurrency, duration_s=duration_s,
                         completed=0, succeeded=0, rate_limited=0, other_errors=0)
    lock = threading.Lock()

    def worker() -> None:
        while time.perf_counter() < stop_at:
            try:
                latency_ms = _one_call(client, model, prompt)
                with lock:
                    result.succeeded += 1
                    result.completed += 1
                    result.latencies_ms.append(latency_ms)
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    result.completed += 1
                    if _is_rate_limited(exc):
                        result.rate_limited += 1
                    else:
                        result.other_errors += 1
                # Brief pause to avoid hot loop on persistent failures.
                time.sleep(0.2)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(concurrency)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    actual_duration = time.perf_counter() - started
    result.duration_s = actual_duration
    return result


def _print_level(r: LevelResult) -> None:
    print(
        f"  concurrency={r.concurrency:>3}  "
        f"completed={r.completed:>4}  ok={r.succeeded:>4}  "
        f"429={r.rate_limited:>3}  err={r.other_errors:>3}  "
        f"rps={r.rps:6.2f}  p50={r.p50_ms:6.0f}ms  p95={r.p95_ms:6.0f}ms  "
        f"err_rate={r.error_rate*100:5.1f}%"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=12.0,
                        help="Seconds to run each concurrency level (default: 12).")
    parser.add_argument("--levels", type=str, default="1,2,4,8,16,24,32,48,64",
                        help="Comma-separated concurrency levels to probe.")
    parser.add_argument("--max-concurrency", type=int, default=None,
                        help="Cap on concurrency levels (filters --levels).")
    parser.add_argument("--error-threshold", type=float, default=0.05,
                        help="Max acceptable error rate to consider a level 'safe' (default 0.05).")
    parser.add_argument("--prompt", type=str, default="ping",
                        help="User prompt sent in each request.")
    parser.add_argument("--cooldown", type=float, default=2.0,
                        help="Seconds to sleep between levels (default 2).")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    args = parser.parse_args()

    _load_env()
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    base_url = args.base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if not api_key:
        print("ERROR: OPENAI_API_KEY is not set (check .env or pass --api-key).", file=sys.stderr)
        return 2

    print(f"Endpoint : {base_url}")
    print(f"Model    : {model}")
    print(f"Duration : {args.duration:.1f}s per level")
    print(f"Threshold: error_rate <= {args.error_threshold*100:.1f}% considered safe")
    print()

    client = _make_client(api_key, base_url)

    # Warm-up call to surface auth/model errors immediately and prime the connection pool.
    print("Warm-up call ... ", end="", flush=True)
    try:
        latency_ms = _one_call(client, model, args.prompt)
        print(f"ok ({latency_ms:.0f} ms)")
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}", file=sys.stderr)
        return 3

    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    if args.max_concurrency is not None:
        levels = [c for c in levels if c <= args.max_concurrency]
    levels = sorted(set(levels))

    print()
    print("Probing concurrency levels:", ", ".join(map(str, levels)))
    print()

    results: List[LevelResult] = []
    best_safe: LevelResult | None = None
    for c in levels:
        print(f"[level {c}] running ...")
        r = _run_level(client, model, c, args.duration, args.prompt)
        _print_level(r)
        results.append(r)
        if r.error_rate <= args.error_threshold and r.succeeded > 0:
            if best_safe is None or r.rps > best_safe.rps:
                best_safe = r
        # Stop early if we are clearly past the limit.
        if r.error_rate > 0.5 and r.rate_limited > 0:
            print("  -> error rate > 50% and 429s observed, stopping early.")
            break
        if c != levels[-1]:
            time.sleep(args.cooldown)

    print()
    print("Summary")
    print("-------")
    for r in results:
        _print_level(r)

    print()
    if best_safe is None:
        print("No level stayed under the error threshold. Lower --levels or check the endpoint.")
        return 1

    rec_concurrency = best_safe.concurrency
    # Round RPS down to one decimal, leave a small safety margin (~10%).
    rec_rps = max(1.0, round(best_safe.rps * 0.9, 1))

    print("Recommendation (with ~10% safety margin):")
    print(f"  TRANSLATE_CONCURRENCY={rec_concurrency}")
    print(f"  LLM_RATE_LIMIT_RPS={rec_rps}")
    print()
    print("Suggested .env / .env.example block:")
    print("  # Translation tuning (auto-tuned by scripts/benchmark_llm_rate.py)")
    print(f"  TRANSLATE_CONCURRENCY={rec_concurrency}")
    print(f"  TRANSLATE_MAX_RETRIES=8")
    print(f"  LLM_RATE_LIMIT_RPS={rec_rps}")
    print(f"  TRANSLATE_BATCH_MAX_CHARS=8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
