"""Vision-based structured extraction. Dua engine:
  - lighton  → LightOn OCR (OpenAI-compatible endpoint)
  - gpt-4o   → OpenAI GPT-4o (vision)

Input selalu berupa list of PNG path (hasil dari pdf_to_images.to_images()).
Output: dict yang nge-mirror EXTRACTION_SCHEMA."""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

import config

log = logging.getLogger(__name__)

EXTRACTION_SCHEMA = {
    "nomor_rekening": "string — nomor rekening yang tampak di dokumen (digit saja, tanpa spasi/strip)",
    "saldo_akhir": "number — saldo akhir / ending balance / closing balance (angka saja, tanpa simbol mata uang & pemisah ribuan)",
}

SYSTEM_PROMPT = f"""You are a bank statement / invoice OCR + data extraction engine.

You receive one or more page images of a single document.
Read the visible text and return a single JSON object matching this schema:

{json.dumps(EXTRACTION_SCHEMA, indent=2)}

Rules:
- Output ONLY valid JSON, no prose, no markdown fences.
- Use null when a field is genuinely absent. Don't invent values.
- nomor_rekening: angka saja (strip spasi/dash). Kalau ada beberapa rekening,
  ambil rekening utama / pemilik dokumen.
- saldo_akhir: angka tanpa simbol mata uang dan tanpa pemisah ribuan (titik/koma).
  Cari label seperti "Saldo Akhir", "Ending Balance", "Closing Balance",
  "Saldo Penutup", atau saldo pada baris terakhir tabel mutasi.
- Indonesian dan English document sama-sama bisa diproses.
- Kalau multi-page, perlakukan sebagai satu dokumen.
"""


# ---------- helpers ----------

def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _coerce_json(raw: str) -> dict[str, Any]:
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _encode_image_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _build_messages(image_paths: list[Path]) -> list[dict[str, Any]]:
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Document has {len(image_paths)} page(s). "
                "Extract the structured fields per the schema. Return JSON only."
            ),
        }
    ]
    for p in image_paths:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": _encode_image_data_url(p)},
            }
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ---------- engines ----------

def _extract_with_lighton(image_paths: list[Path]) -> dict[str, Any]:
    if not config.LIGHTON_API_KEY:
        raise RuntimeError("LIGHTON_API_KEY not set in .env")
    client = OpenAI(
        api_key=config.LIGHTON_API_KEY,
        base_url=config.LIGHTON_BASE_URL,
    )
    resp = client.chat.completions.create(
        model=config.LIGHTON_MODEL,
        temperature=0,
        max_tokens=2048,
        messages=_build_messages(image_paths),
    )
    body = resp.choices[0].message.content or ""
    log.debug("LightOn raw response: %s", body[:300])
    return _coerce_json(body)


def _extract_with_gpt(image_paths: list[Path]) -> dict[str, Any]:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set in .env")
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=_build_messages(image_paths),
    )
    body = resp.choices[0].message.content or ""
    log.debug("GPT-4o raw response: %s", body[:300])
    return _coerce_json(body)


def extract_structured(image_paths: list[Path], engine: str | None = None) -> dict[str, Any]:
    engine = (engine or config.DEFAULT_AI_ENGINE).lower()
    if engine in {"lighton", "lighton-ocr", "lightonocr"}:
        return _extract_with_lighton(image_paths)
    if engine in {"gpt-4o", "gpt", "openai", "gpt4o"}:
        return _extract_with_gpt(image_paths)
    raise ValueError(
        f"Unknown engine: {engine!r}. Choose 'lighton' or 'gpt-4o'."
    )
