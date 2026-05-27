"""Streamlit UI for Invoice Automation.

Run:
    python start.py
    # or
    streamlit run app.py

Mirrors main.py: fetch Gmail (or upload PDF/image manually) → render to PNG
pages → vision OCR (LightOn / GPT-4o) → validate → CSV (+ optional Excel /
Sheets), with a live BEFORE / AFTER preview per attachment.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import traceback
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

import config

st.set_page_config(
    page_title="Invoice Automation",
    page_icon="🧾",
    layout="wide",
)


# ---------- helpers ----------

@st.cache_data(ttl=5)
def load_csv() -> pd.DataFrame:
    path = config.CSV_OUTPUT_PATH
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def list_run_dumps() -> list[Path]:
    return sorted(
        config.OUTPUT_DIR.glob("run_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def to_int_or_none(s: str) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


VALIDATION_BADGE = {True: "✅ ok", False: "❌ flagged"}


# ---------- Sidebar form ----------

st.sidebar.title("⚙️ Run Settings")

with st.sidebar.form("run_form"):
    st.subheader("Source")
    mode = st.radio(
        "Where do invoices come from?",
        ["Gmail", "Upload files"],
        horizontal=True,
        index=0,
    )

    if mode == "Gmail":
        time_mode = st.radio(
            "Time window",
            ["Last N hours", "Since / Until"],
            horizontal=True,
            index=0,
        )
        if time_mode == "Last N hours":
            last_hours = st.number_input(
                "Last N hours", min_value=0.5, max_value=720.0, value=24.0, step=0.5,
            )
            since_dt = until_dt = None
        else:
            last_hours = None
            c1, c2 = st.columns(2)
            with c1:
                since_d = st.date_input(
                    "Since date", value=date.today() - timedelta(days=1)
                )
                since_t = st.time_input("Since time", value=time(0, 0))
            with c2:
                until_d = st.date_input("Until date", value=date.today())
                until_t = st.time_input("Until time", value=time(23, 59))
            since_dt = datetime.combine(since_d, since_t).astimezone()
            until_dt = datetime.combine(until_d, until_t).astimezone()

        max_results = st.slider("Max emails", 1, 200, 50)
        mark_processed = st.checkbox(
            "Apply 'Invoice/Processed' label after extraction",
            value=True,
            help="Skip these emails in subsequent runs. Uncheck while testing.",
        )
        uploaded_files = None
    else:
        last_hours = since_dt = until_dt = max_results = None
        mark_processed = False
        uploaded_files = st.file_uploader(
            "PDF / image files",
            accept_multiple_files=True,
            type=["pdf", "png", "jpg", "jpeg", "tiff", "tif"],
        )

    st.subheader("Engine")
    engine = st.radio(
        "Vision OCR engine",
        ["lighton", "gpt-4o"],
        index=0 if config.DEFAULT_AI_ENGINE == "lighton" else 1,
        horizontal=True,
    )

    st.subheader("Outputs")
    to_csv = st.checkbox("CSV (default)", value=True)
    to_excel = st.checkbox("Excel (.xlsx)", value=False)
    to_sheets = st.checkbox(
        "Google Sheets",
        value=False,
        help="Needs credentials/sheets_service_account.json + GOOGLE_SHEET_ID in .env",
    )

    show_demo = st.checkbox(
        "Show BEFORE / AFTER per attachment",
        value=True,
        help="Render the page image (BEFORE) next to the extracted JSON (AFTER).",
    )

    submitted = st.form_submit_button("▶️ Run Extraction", type="primary")


# ---------- Header ----------

st.title("🧾 Invoice Automation")
st.caption(
    f"Engine: `{engine}` · "
    f"Gmail label gate: `{config.GMAIL_PROCESSED_LABEL}`"
)


# ---------- Run handler ----------

def _process_attachment_ui(path: Path, engine_choice: str, meta: dict) -> dict:
    """Per-attachment pipeline that also returns rendered page paths for preview."""
    from pdf_to_images import to_images
    from ai_extractor import extract_structured
    from validator import validate

    pages = to_images(path)
    if not pages:
        return {
            "attachment_file": str(path),
            "validation_ok": False,
            "validation_issues": ["no pages rendered"],
            "pages": [],
            **meta,
        }
    data = extract_structured(pages, engine=engine_choice)
    ok, issues = validate(data)
    return {
        **data,
        "validation_ok": ok,
        "validation_issues": issues,
        "attachment_file": str(path),
        "pages": [str(p) for p in pages],
        **meta,
    }


if submitted:
    storage_ok = True

    if mode == "Upload files":
        if not uploaded_files:
            st.error("Upload at least one PDF or image first.")
            st.stop()
        # Persist uploads to a tmp dir under downloads/ so paths stick for previews
        upload_dir = config.DOWNLOADS_DIR / f"uploads_{datetime.now():%Y%m%dT%H%M%S}"
        upload_dir.mkdir(parents=True, exist_ok=True)
        attachment_paths = []
        for uf in uploaded_files:
            dest = upload_dir / uf.name
            dest.write_bytes(uf.getbuffer())
            attachment_paths.append(dest)
        attachments_meta = [
            (p, {"source": "manual", "email_subject": "", "received_at": None})
            for p in attachment_paths
        ]
    else:
        from gmail_client import fetch_invoices

        if last_hours is not None:
            until_dt_local = datetime.now(timezone.utc)
            since_dt_local = until_dt_local - timedelta(hours=last_hours)
        else:
            since_dt_local, until_dt_local = since_dt, until_dt

        with st.status("Fetching invoices from Gmail…", expanded=True) as s_fetch:
            try:
                emails = fetch_invoices(
                    since_dt_local, until_dt_local,
                    max_results=max_results,
                    mark_processed=mark_processed,
                )
            except Exception as exc:  # noqa: BLE001
                s_fetch.update(label=f"Gmail fetch failed: {exc}", state="error")
                st.exception(exc)
                st.stop()

            invoice_emails = [e for e in emails if e.is_invoice and e.attachments]
            st.write(
                f"Found **{len(emails)}** message(s), "
                f"**{len(invoice_emails)}** classified as invoice with attachment."
            )
            attachments_meta = []
            for em in invoice_emails:
                for att in em.attachments:
                    attachments_meta.append(
                        (
                            att.local_path,
                            {
                                "source": "gmail",
                                "email_subject": em.subject,
                                "received_at": em.received_at.isoformat(),
                            },
                        )
                    )
            s_fetch.update(
                label=f"Fetched {len(attachments_meta)} attachment(s).",
                state="complete",
            )

    if not attachments_meta:
        st.warning("Nothing to process.")
        st.stop()

    st.subheader(f"Processing {len(attachments_meta)} attachment(s)…")
    progress = st.progress(0.0, text="Starting…")
    demo_area = st.container() if show_demo else None
    compact_log = None if show_demo else st.empty()
    log_lines: list[str] = []

    rows: list[dict] = []
    n_ok, n_err = 0, 0
    for i, (path, meta) in enumerate(attachments_meta, 1):
        t0 = datetime.now()
        try:
            row = _process_attachment_ui(Path(path), engine, meta)
            err = None
        except Exception as exc:  # noqa: BLE001
            err = exc
            row = {
                "attachment_file": str(path),
                "validation_ok": False,
                "validation_issues": [f"pipeline error: {exc}"],
                "pages": [],
                **meta,
            }
        rows.append(row)
        ms = int((datetime.now() - t0).total_seconds() * 1000)

        if err is None and row.get("validation_ok"):
            n_ok += 1
        else:
            n_err += 1

        if show_demo:
            with demo_area:
                icon = "✅" if err is None and row.get("validation_ok") else "⚠️"
                if err is not None:
                    icon = "❌"
                title = (
                    f"{icon} [{i}/{len(attachments_meta)}] "
                    f"{Path(path).name} · "
                    f"{row.get('vendor_name') or row.get('nomor_rekening') or '—'} "
                    f"· {ms} ms"
                )
                with st.expander(title, expanded=(i == 1)):
                    col_b, col_a = st.columns([1, 1])
                    with col_b:
                        st.markdown("**📥 BEFORE — rendered page(s)**")
                        st.caption(f"`{Path(path).name}`")
                        pages = row.get("pages") or []
                        if not pages:
                            st.info("No pages rendered.")
                        else:
                            for p in pages[:3]:
                                st.image(p, use_container_width=True)
                            if len(pages) > 3:
                                st.caption(f"+ {len(pages) - 3} more page(s) hidden")
                    with col_a:
                        if err is None:
                            st.markdown(f"**🤖 AFTER — {engine} ({ms} ms)**")
                            extracted = {
                                k: v for k, v in row.items()
                                if k not in {
                                    "pages", "attachment_file", "source",
                                    "email_subject", "received_at",
                                    "validation_ok", "validation_issues",
                                }
                            }
                            st.json(extracted)
                            st.markdown(
                                f"**Validation:** "
                                f"{VALIDATION_BADGE.get(row.get('validation_ok'), '?')}"
                            )
                            if row.get("validation_issues"):
                                for iss in row["validation_issues"]:
                                    st.warning(iss)
                            if meta.get("source") == "gmail":
                                st.caption(f"📧 {meta.get('email_subject', '')}")
                        else:
                            st.markdown(f"**❌ AFTER — ERROR ({ms} ms)**")
                            st.error(f"{type(err).__name__}: {err}")
        else:
            line = (
                f"[{i}/{len(attachments_meta)}] "
                f"{'✅' if err is None else '❌'} "
                f"{Path(path).name} · {ms} ms"
            )
            log_lines.append(line)
            compact_log.markdown("\n\n".join(log_lines[-12:]))

        progress.progress(
            i / len(attachments_meta),
            text=f"Processed {i}/{len(attachments_meta)}",
        )

    # Persist outputs (mirror main.write_outputs)
    if rows:
        write_summary = []
        if to_csv:
            from csv_exporter import append_rows as csv_append
            p = csv_append(rows)
            write_summary.append(f"CSV → `{p}`")
        if to_excel:
            try:
                from excel_exporter import append_rows as excel_append
                p = excel_append(rows)
                write_summary.append(f"Excel → `{p}`")
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Excel export failed: {exc}")
        if to_sheets:
            try:
                from sheets_exporter import append_rows as sheets_append
                url = sheets_append(rows)
                write_summary.append(f"Sheets → {url}")
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Sheets export failed: {exc}")

        dump_path = config.OUTPUT_DIR / (
            f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
        )
        # `pages` contains absolute paths; keep them out of the persisted dump
        clean_rows = [{k: v for k, v in r.items() if k != "pages"} for r in rows]
        dump_path.write_text(
            json.dumps(clean_rows, indent=2, ensure_ascii=False, default=str)
        )
        write_summary.append(f"Raw JSON → `{dump_path.name}`")

        load_csv.clear()
        st.success(
            f"Done. ✅ {n_ok} ok · ⚠️ {n_err} flagged/error · "
            + " · ".join(write_summary)
        )


# ---------- Tabs ----------

df = load_csv()
runs = list_run_dumps()

tab_invoices, tab_runs, tab_logs = st.tabs(["📋 All Invoices", "📦 Run history", "📜 Logs"])

with tab_invoices:
    if df.empty:
        st.info("No invoices in CSV yet. Click **Run Extraction** in the sidebar to start.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total rows", len(df))
        ok_n = int((df.get("validation_ok", pd.Series(dtype=bool)) == True).sum())
        c2.metric("✅ Validated", ok_n)
        c3.metric("⚠️ Flagged", len(df) - ok_n)

        f1, f2, f3 = st.columns([1, 1, 2])
        sources = sorted({s for s in df.get("source", []) if isinstance(s, str) and s})
        with f1:
            src_filter = st.multiselect("Source", options=sources, default=[])
        with f2:
            ok_filter = st.selectbox(
                "Validation", ["(all)", "✅ ok only", "⚠️ flagged only"]
            )
        with f3:
            search = st.text_input("Search (subject / filename)")

        view = df.copy()
        if src_filter and "source" in view.columns:
            view = view[view["source"].isin(src_filter)]
        if ok_filter == "✅ ok only" and "validation_ok" in view.columns:
            view = view[view["validation_ok"] == True]
        elif ok_filter == "⚠️ flagged only" and "validation_ok" in view.columns:
            view = view[view["validation_ok"] != True]
        if search:
            s = search.lower()
            mask = pd.Series(False, index=view.index)
            for col in ("email_subject", "attachment_file"):
                if col in view.columns:
                    mask = mask | view[col].fillna("").astype(str).str.lower().str.contains(s)
            view = view[mask]

        st.caption(f"Showing **{len(view)}** of {len(df)} rows")
        st.dataframe(view, width="stretch", height=520, hide_index=True)

        st.download_button(
            "⬇️ Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="invoices.csv",
            mime="text/csv",
        )

with tab_runs:
    if not runs:
        st.info("No run dumps yet. Each extraction writes `output/run_<timestamp>.json`.")
    else:
        labels = [
            f"{p.stem.replace('run_', '')} · {p.stat().st_size // 1024} KB"
            for p in runs
        ]
        idx = st.selectbox("Pick a run", range(len(runs)), format_func=lambda i: labels[i])
        chosen = runs[idx]
        try:
            payload = json.loads(chosen.read_text())
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to read {chosen.name}: {exc}")
            payload = []
        st.caption(f"`{chosen.name}` — {len(payload)} row(s)")
        if payload:
            st.dataframe(pd.DataFrame(payload), width="stretch", height=420, hide_index=True)
            with st.expander("Raw JSON"):
                st.json(payload)

with tab_logs:
    log_file = config.LOGS_DIR / "run.log"
    if not log_file.exists():
        st.info("No log file yet.")
    else:
        n = st.slider("Tail lines", 20, 1000, 200, step=20)
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-n:]
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to read log: {exc}")
            tail = []
        st.code("".join(tail) or "(empty)", language="log")
