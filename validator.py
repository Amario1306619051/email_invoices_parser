"""Validasi sederhana untuk schema {nomor_rekening, saldo_akhir}."""
from __future__ import annotations

import re
from typing import Any


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace(" ", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def validate(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (ok, list_of_issues). ok=False -> baris di-flag."""
    issues: list[str] = []

    rek = data.get("nomor_rekening")
    if not rek:
        issues.append("missing field: nomor_rekening")
    else:
        digits = re.sub(r"\D", "", str(rek))
        if len(digits) < 6:
            issues.append(f"nomor_rekening terlalu pendek: {rek!r}")

    saldo = _to_float(data.get("saldo_akhir"))
    if saldo is None:
        issues.append("missing field: saldo_akhir")

    return len(issues) == 0, issues
