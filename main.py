"""End-to-end pipeline.

Flow (matches the flowchart):
  1. Receive emails between time_init / time_final (Gmail)
  2. Classification + mark as read
  3. Render PDF / image → PNG pages (PyMuPDF)
  4. Vision OCR + structured extraction (lighton OR gpt-4o)
  5. Validate + write to CSV (default), optional Excel / Google Sheets

Usage examples:
    # Pull yesterday → now, use LightOn OCR, write to CSV
    python main.py --since "2026-05-17 00:00" --until "2026-05-18 23:59" --engine lighton

    # Manual fallback for a file (PDF or image)
    python main.py --file /path/to/invoice.pdf --engine gpt-4o

    # Also write Excel + push to Sheets
    python main.py --last-hours 24 --excel --sheets

    # Testing: jangan apply label processed (email tetap masuk query berikutnya)
    python main.py --last-hours 5 --no-mark-processed
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOGS_DIR / "run.log"),
    ],
)
log = logging.getLogger("invoice_automation")


def _parse_dt(s: str | None) -> datetime | None:
    """Parse user input. Naive datetime → di-attach ke timezone lokal supaya
    konversi ke epoch konsisten dengan apa yang user lihat di jam mereka."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            naive = datetime.strptime(s, fmt)
            return naive.astimezone()  # attach local tz
        except ValueError:
            continue
    raise ValueError(f"Unrecognized datetime: {s}")


def _process_attachment(
    attachment_path: Path,
    engine: str,
    email_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from pdf_to_images import to_images
    from ai_extractor import extract_structured
    from validator import validate

    log.info("Rendering %s to page images", attachment_path.name)
    image_paths = to_images(attachment_path)
    if not image_paths:
        return {
            "attachment_file": str(attachment_path),
            "validation_ok": False,
            "validation_issues": ["no pages rendered"],
            **(email_meta or {}),
        }

    log.info("Running %s OCR + extraction on %d page(s)", engine, len(image_paths))
    data = extract_structured(image_paths, engine=engine)
    ok, issues = validate(data)

    row = {
        **data,
        "validation_ok": ok,
        "validation_issues": issues,
        "attachment_file": str(attachment_path),
        "source": (email_meta or {}).get("source", "manual"),
        "email_subject": (email_meta or {}).get("email_subject", ""),
        "received_at": (email_meta or {}).get("received_at"),
    }
    log.info(
        "  vendor=%s total=%s currency=%s ok=%s",
        row.get("vendor_name"), row.get("total"), row.get("currency"), ok,
    )
    if not ok:
        log.warning("  validation issues: %s", issues)
    return row


def run_gmail(
    since: datetime | None,
    until: datetime | None,
    engine: str,
    max_results: int,
    mark_processed: bool,
) -> list[dict[str, Any]]:
    from gmail_client import fetch_invoices

    emails = fetch_invoices(
        since, until, max_results=max_results, mark_processed=mark_processed
    )
    invoice_emails = [e for e in emails if e.is_invoice and e.attachments]
    log.info("%d/%d messages classified as invoice/receipt with attachment",
             len(invoice_emails), len(emails))

    rows: list[dict[str, Any]] = []
    for em in invoice_emails:
        meta = {
            "source": "gmail",
            "email_subject": em.subject,
            "received_at": em.received_at.isoformat(),
        }
        for att in em.attachments:
            try:
                rows.append(_process_attachment(att.local_path, engine, meta))
            except Exception as exc:  # noqa: BLE001
                log.error("Failed on %s: %s", att.local_path, exc)
                log.debug(traceback.format_exc())
                rows.append({
                    "attachment_file": str(att.local_path),
                    "validation_ok": False,
                    "validation_issues": [f"pipeline error: {exc}"],
                    **meta,
                })
    return rows


def run_manual(files: list[Path], engine: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for f in files:
        if not f.exists():
            log.error("File not found: %s", f)
            continue
        try:
            rows.append(_process_attachment(f, engine, {"source": "manual"}))
        except Exception as exc:  # noqa: BLE001
            log.error("Failed on %s: %s", f, exc)
            rows.append({
                "attachment_file": str(f),
                "source": "manual",
                "validation_ok": False,
                "validation_issues": [f"pipeline error: {exc}"],
            })
    return rows


def write_outputs(
    rows: list[dict[str, Any]],
    to_csv: bool,
    to_excel: bool,
    to_sheets: bool,
) -> None:
    if not rows:
        log.info("No rows to write.")
        return
    if to_csv:
        from csv_exporter import append_rows as csv_append
        path = csv_append(rows)
        log.info("CSV updated: %s", path)
    if to_excel:
        from excel_exporter import append_rows as excel_append
        path = excel_append(rows)
        log.info("Excel updated: %s", path)
    if to_sheets:
        try:
            from sheets_exporter import append_rows as sheets_append
            url = sheets_append(rows)
            log.info("Sheet updated: %s", url)
        except Exception as exc:  # noqa: BLE001
            log.error("Google Sheets export failed: %s", exc)

    # Also dump raw JSON for inspection / Loom walkthrough
    dump_path = config.OUTPUT_DIR / f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    dump_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
    log.info("Raw rows: %s", dump_path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Automated invoice / receipt pipeline")
    p.add_argument("--since", help="time_init (e.g. '2026-05-17 00:00')")
    p.add_argument("--until", help="time_final (e.g. '2026-05-18 23:59')")
    p.add_argument(
        "--engine",
        choices=["lighton", "gpt-4o"],
        default=None,
        help="OCR/extraction engine. Defaults to DEFAULT_AI_ENGINE from .env",
    )
    p.add_argument("--max-results", type=int, default=50)
    p.add_argument(
        "--no-mark-processed",
        action="store_true",
        help=(
            "Jangan apply label 'Invoice/Processed' setelah ekstraksi. "
            "Dengan flag ini, email yang sama akan diproses ulang setiap run "
            "(berguna saat testing)."
        ),
    )
    p.add_argument(
        "--file",
        action="append",
        default=[],
        help="Manual upload: path to PDF/image. Can be repeated. Skips Gmail.",
    )
    p.add_argument("--no-csv", action="store_true", help="Skip CSV export")
    p.add_argument("--excel", action="store_true", help="Also write Excel file")
    p.add_argument("--sheets", action="store_true", help="Also push to Google Sheets")
    p.add_argument(
        "--last-hours",
        type=float,
        default=None,
        help="Shortcut: pull mail from the last N hours (overrides --since/--until)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    engine = (args.engine or config.DEFAULT_AI_ENGINE).lower()
    log.info("Engine: %s", engine)

    if args.file:
        rows = run_manual([Path(p) for p in args.file], engine)
    else:
        if args.last_hours is not None:
            until = datetime.now(timezone.utc)
            since = until - timedelta(hours=args.last_hours)
        else:
            since = _parse_dt(args.since)
            until = _parse_dt(args.until)
        rows = run_gmail(
            since=since,
            until=until,
            engine=engine,
            max_results=args.max_results,
            mark_processed=not args.no_mark_processed,
        )

    write_outputs(
        rows,
        to_csv=not args.no_csv,
        to_excel=args.excel,
        to_sheets=args.sheets,
    )
    log.info("Done. Processed %d invoice rows.", len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
