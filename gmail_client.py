"""Gmail integration: list emails within a time window, classify as invoice/receipt,
download PDF/image attachments, and mark messages as read."""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config

log = logging.getLogger(__name__)

SUPPORTED_MIMES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/tiff",
}


@dataclass
class EmailAttachment:
    message_id: str
    filename: str
    mime_type: str
    local_path: Path


@dataclass
class EmailRecord:
    message_id: str
    thread_id: str
    subject: str
    sender: str
    received_at: datetime
    snippet: str
    is_invoice: bool
    attachments: list[EmailAttachment] = field(default_factory=list)


def _build_service():
    creds: Credentials | None = None
    if config.GMAIL_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(
            str(config.GMAIL_TOKEN_PATH), config.GMAIL_SCOPES
        )
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not config.GMAIL_CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Gmail OAuth client file missing at {config.GMAIL_CREDENTIALS_PATH}. "
                    "Download it from Google Cloud Console → OAuth 2.0 Client IDs."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.GMAIL_CREDENTIALS_PATH), config.GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)
        config.GMAIL_TOKEN_PATH.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


INVOICE_SUBJECT_MARKER = "[invoice]"


def _classify(subject: str, snippet: str, has_attachment: bool) -> bool:
    if not has_attachment:
        return False
    return INVOICE_SUBJECT_MARKER in subject.lower()


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _parse_date(raw: str) -> datetime:
    # Gmail "internalDate" is more reliable, but the header is human readable
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw)
    except Exception:
        return datetime.utcnow()


def _gmail_query(time_init: datetime | None, time_final: datetime | None) -> str:
    parts = [
        'has:attachment',
        'is:unread',
        'subject:"[Invoice]"',
        f'-label:"{config.GMAIL_PROCESSED_LABEL}"',  # skip yang sudah diproses
    ]
    if time_init:
        parts.append(f"after:{int(time_init.timestamp())}")
    if time_final:
        parts.append(f"before:{int(time_final.timestamp())}")
    return " ".join(parts)


def _get_or_create_label(service, name: str) -> str:
    """Cari label by name, buat kalau belum ada. Return label ID."""
    resp = service.users().labels().list(userId="me").execute()
    for lbl in resp.get("labels", []):
        if lbl["name"] == name:
            return lbl["id"]
    log.info("Creating Gmail label: %s", name)
    created = service.users().labels().create(
        userId="me",
        body={
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    return created["id"]


def _walk_parts(parts: Iterable[dict]):
    for part in parts:
        if "parts" in part:
            yield from _walk_parts(part["parts"])
        else:
            yield part


def _download_attachment(service, message_id: str, part: dict, target_dir: Path) -> Path | None:
    filename = part.get("filename") or ""
    mime = part.get("mimeType", "")
    if mime not in SUPPORTED_MIMES:
        return None
    body = part.get("body", {})
    att_id = body.get("attachmentId")
    if not att_id:
        return None
    data = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=att_id)
        .execute()
    )
    raw = base64.urlsafe_b64decode(data["data"])
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename) or f"att_{att_id[:10]}"
    out_path = target_dir / f"{message_id}_{safe_name}"
    out_path.write_bytes(raw)
    log.info("Saved attachment %s (%d bytes)", out_path.name, len(raw))
    return out_path


def fetch_invoices(
    time_init: datetime | None = None,
    time_final: datetime | None = None,
    max_results: int = 50,
    mark_processed: bool = True,
) -> list[EmailRecord]:
    service = _build_service()
    query = _gmail_query(time_init, time_final)
    log.info("Gmail query: %s", query)
    processed_label_id = _get_or_create_label(service, config.GMAIL_PROCESSED_LABEL) if mark_processed else None

    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    msg_ids = [m["id"] for m in listing.get("messages", [])]
    log.info("Found %d candidate messages", len(msg_ids))

    records: list[EmailRecord] = []
    for mid in msg_ids:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=mid, format="full")
            .execute()
        )
        headers = msg["payload"].get("headers", [])
        subject = _header(headers, "Subject")
        sender = _header(headers, "From")
        date_header = _header(headers, "Date")
        snippet = msg.get("snippet", "")

        parts = []
        payload = msg.get("payload", {})
        if "parts" in payload:
            parts = list(_walk_parts(payload["parts"]))
        elif payload.get("filename"):
            parts = [payload]

        has_att = any(p.get("filename") for p in parts)
        is_inv = _classify(subject, snippet, has_att)

        record = EmailRecord(
            message_id=mid,
            thread_id=msg.get("threadId", ""),
            subject=subject,
            sender=sender,
            received_at=_parse_date(date_header),
            snippet=snippet,
            is_invoice=is_inv,
        )

        if is_inv:
            for part in parts:
                path = _download_attachment(service, mid, part, config.DOWNLOADS_DIR)
                if path:
                    record.attachments.append(
                        EmailAttachment(
                            message_id=mid,
                            filename=path.name,
                            mime_type=part.get("mimeType", ""),
                            local_path=path,
                        )
                    )

        if is_inv and record.attachments and mark_processed and processed_label_id:
            service.users().messages().modify(
                userId="me",
                id=mid,
                body={"addLabelIds": [processed_label_id]},
            ).execute()
            log.info("Labeled %s as processed (subject: %s) — tetap UNREAD",
                     mid, subject[:60])

        records.append(record)
    return records
