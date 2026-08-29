"""Pipeline stage tracking + ETA helpers.

Stages are declared up-front (per source_type) so the frontend can render a
deterministic progress bar.  Per-stage durations are persisted in a small
JSON cache (sliding average) under ``data/cache/stage_stats.json`` so future
runs can compute a meaningful ETA.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.models.store import DocumentRecord, StageEntry


# stage_key -> (label, weight)
PDF_STAGES: list[tuple[str, str, float]] = [
    ("upload", "接收文件", 1.0),
    ("parse", "解析 PDF", 45.0),
    ("clean", "清洗与对齐", 3.0),
    ("vision_check", "视觉模型校验", 10.0),
    ("translate", "翻译", 35.0),
    ("latex_build", "LaTeX 编译", 6.0),
]

TEX_STAGES: list[tuple[str, str, float]] = [
    ("upload", "接收文件", 1.0),
    ("compile_original", "编译原始 TeX", 15.0),
    ("translate", "翻译", 60.0),
    ("vision_check", "视觉模型校验", 15.0),
    ("compile_translated", "编译译文 TeX", 9.0),
]


_CACHE_LOCK = threading.Lock()


def _stats_path() -> Path:
    cache_dir = settings.data_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "stage_stats.json"


def _load_stats() -> dict:
    path = _stats_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_stats(data: dict) -> None:
    path = _stats_path()
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _record_stage_duration(source_type: str, stage_key: str, seconds: float) -> None:
    with _CACHE_LOCK:
        data = _load_stats()
        bucket = data.setdefault(source_type, {})
        prev = bucket.get(stage_key)
        if prev is None:
            bucket[stage_key] = {"avg": seconds, "n": 1}
        else:
            n = prev.get("n", 1) + 1
            # cap at 20 samples for a sliding-ish average
            n = min(n, 20)
            new_avg = prev["avg"] + (seconds - prev["avg"]) / n
            bucket[stage_key] = {"avg": new_avg, "n": n}
        _save_stats(data)


def _stage_avg(source_type: str, stage_key: str) -> float | None:
    data = _load_stats()
    val = data.get(source_type, {}).get(stage_key)
    if val is None:
        return None
    try:
        return float(val.get("avg"))
    except Exception:
        return None


def stages_for(source_type: str) -> list[tuple[str, str, float]]:
    if source_type == "pdf":
        return PDF_STAGES
    # tex and tex_project share the same stage table
    return TEX_STAGES


def init_stages(record: DocumentRecord, *, vision_check_enabled: bool = True) -> None:
    """Populate record.stages with declared stages (status=pending)."""
    plan = stages_for(record.source_type)
    if not vision_check_enabled:
        plan = [s for s in plan if s[0] != "vision_check"]
    record.stages = [
        StageEntry(key=key, label=label, weight=weight, status="pending")
        for (key, label, weight) in plan
    ]
    record.progress = 0
    record.current_stage = None
    record.current_stage_label = None
    record.stage_started_at = None
    record.eta_seconds = None
    _recompute_eta(record)


def _total_weight(record: DocumentRecord) -> float:
    return sum(s.weight for s in record.stages) or 1.0


def _completed_weight(record: DocumentRecord) -> float:
    return sum(s.weight for s in record.stages if s.status == "done")


def _recompute_eta(record: DocumentRecord) -> None:
    total_w = _total_weight(record)
    done_w = _completed_weight(record)
    record.progress = int(round(100 * done_w / total_w))

    remaining: float = 0.0
    has_history = False
    now = time.time()
    for s in record.stages:
        if s.status == "done":
            continue
        if s.status == "running" and s.started_at is not None:
            avg = _stage_avg(record.source_type, s.key)
            if avg is not None:
                has_history = True
                elapsed = max(0.0, now - s.started_at)
                remaining += max(0.0, avg - elapsed)
            else:
                remaining += s.weight  # fallback per-weight seconds
            continue
        avg = _stage_avg(record.source_type, s.key)
        if avg is not None:
            has_history = True
            remaining += avg
        else:
            remaining += s.weight
    record.eta_seconds = int(remaining) if has_history or record.stages else None


def set_stage_progress(
    record: DocumentRecord, stage_key: str, fraction: float, label: str | None = None
) -> None:
    """Advance the overall progress bar *within* a running stage.

    The default progress only moves when a whole stage transitions to ``done``,
    which leaves the bar pinned near 0% during long stages (e.g. a large PDF
    uploading to MinerU for ~40s). Callers inside a stage body pass a ``fraction``
    in [0, 1] to reflect sub-stage progress so the bar keeps moving and the label
    can explain what is happening.
    """
    entry = next((s for s in record.stages if s.key == stage_key), None)
    if entry is None:
        return
    fraction = max(0.0, min(1.0, float(fraction)))
    total_w = _total_weight(record)
    done_w = _completed_weight(record)
    running_w = entry.weight * fraction if entry.status == "running" else 0.0
    record.progress = int(round(100 * (done_w + running_w) / total_w))
    if label:
        entry.label = label
        record.current_stage_label = label


@contextmanager
def with_stage(record: DocumentRecord, stage_key: str, label: str | None = None):
    entry = next((s for s in record.stages if s.key == stage_key), None)
    if entry is None:
        # not declared; just yield without tracking
        yield
        return
    if label:
        entry.label = label
    entry.status = "running"
    started = time.time()
    entry.started_at = started
    record.current_stage = stage_key
    record.current_stage_label = entry.label
    record.stage_started_at = started
    _recompute_eta(record)
    try:
        yield entry
    except Exception:
        entry.status = "failed"
        entry.ended_at = time.time()
        entry.duration_ms = int((entry.ended_at - started) * 1000)
        _recompute_eta(record)
        raise
    else:
        ended = time.time()
        entry.status = "done"
        entry.ended_at = ended
        entry.duration_ms = int((ended - started) * 1000)
        _record_stage_duration(record.source_type, stage_key, ended - started)
        _recompute_eta(record)


def stage_dicts(record: DocumentRecord) -> list[dict]:
    return [asdict(s) for s in record.stages]


def remaining_keys(record: DocumentRecord) -> Iterable[str]:
    return (s.key for s in record.stages if s.status != "done")
