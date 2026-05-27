"""CSV exporter. Kolom otomatis mengikuti EXTRACTION_SCHEMA dari ai_extractor.py
ditambah kolom metadata + validasi. Append-mode."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import config
from ai_extractor import EXTRACTION_SCHEMA

log = logging.getLogger(__name__)

META_COLUMNS = [
    "received_at",
    "source",
    "email_subject",
    "attachment_file",
]

AI_COLUMNS = list(EXTRACTION_SCHEMA.keys())

TAIL_COLUMNS = [
    "validation_ok",
    "validation_issues",
]

HEADERS = META_COLUMNS + AI_COLUMNS + TAIL_COLUMNS


def _row_to_record(row: dict[str, Any]) -> dict[str, Any]:
    rec: dict[str, Any] = {}
    for k in META_COLUMNS:
        rec[k] = row.get(k, "")
    for k in AI_COLUMNS:
        v = row.get(k)
        rec[k] = "" if v is None else v
    rec["validation_ok"] = row.get("validation_ok")
    rec["validation_issues"] = "; ".join(row.get("validation_issues") or [])
    return rec


def append_rows(rows: list[dict[str, Any]], output_path: Path | None = None) -> Path:
    target = Path(output_path) if output_path else config.CSV_OUTPUT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    write_header = not target.exists()

    with target.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_record(row))

    log.info("Wrote %d rows to %s", len(rows), target)
    return target
