"""Append extracted rows to a Google Sheet. Flagged rows are highlighted in light red."""
from __future__ import annotations

import json
import logging
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

import config
from excel_exporter import HEADERS

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _client() -> gspread.Client:
    if not config.GOOGLE_SHEETS_CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Service account JSON missing at {config.GOOGLE_SHEETS_CREDENTIALS_PATH}"
        )
    creds = Credentials.from_service_account_file(
        str(config.GOOGLE_SHEETS_CREDENTIALS_PATH), scopes=SCOPES
    )
    return gspread.authorize(creds)


def _ensure_header(ws: gspread.Worksheet) -> None:
    head = ws.row_values(1)
    if head != HEADERS:
        ws.update("A1", [HEADERS])
        ws.format(
            f"A1:{gspread.utils.rowcol_to_a1(1, len(HEADERS))}",
            {"textFormat": {"bold": True}},
        )


def append_rows(rows: list[dict[str, Any]]) -> str:
    if not config.GOOGLE_SHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID not set in env")
    gc = _client()
    sh = gc.open_by_key(config.GOOGLE_SHEET_ID)
    try:
        ws = sh.worksheet(config.GOOGLE_SHEET_TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=config.GOOGLE_SHEET_TAB, rows=1000, cols=len(HEADERS))
    _ensure_header(ws)

    payload: list[list[Any]] = []
    for row in rows:
        payload.append(
            [
                str(row.get("received_at") or ""),
                row.get("source", "gmail"),
                row.get("email_subject", ""),
                row.get("vendor_name") or "",
                row.get("invoice_number") or "",
                row.get("invoice_date") or "",
                row.get("due_date") or "",
                row.get("currency") or "",
                row.get("subtotal"),
                row.get("tax"),
                row.get("total"),
                row.get("payment_terms") or "",
                json.dumps(row.get("line_items") or [], ensure_ascii=False),
                bool(row.get("validation_ok")),
                "; ".join(row.get("validation_issues") or []),
                row.get("attachment_file") or "",
            ]
        )

    start_row = len(ws.col_values(1)) + 1
    ws.append_rows(payload, value_input_option="USER_ENTERED")

    # Highlight flagged rows
    flag_color = {"red": 0.97, "green": 0.78, "blue": 0.78}
    for i, row in enumerate(rows):
        if not row.get("validation_ok", True):
            r = start_row + i
            ws.format(
                f"A{r}:{gspread.utils.rowcol_to_a1(r, len(HEADERS))}",
                {"backgroundColor": flag_color},
            )

    url = f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEET_ID}"
    log.info("Wrote %d rows to %s (tab %s)", len(rows), url, config.GOOGLE_SHEET_TAB)
    return url
