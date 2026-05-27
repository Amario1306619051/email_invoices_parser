"""Single-file entrypoint for Invoice Automation.

Run:
    python start.py

Automatically:
  - Re-execs into the project venv (even if launched with system Python)
  - Installs missing deps (streamlit, pandas, etc.)
  - Creates .env from .env.example if missing
  - Launches the Streamlit UI at http://localhost:8502

UI covers: Gmail fetch → render → vision OCR (LightOn / GPT-4o) →
validate → CSV/Excel/Sheets, plus a live BEFORE / AFTER preview per
attachment, an All-Invoices table, and a run-history browser.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PY = Path("/home/rnd/Documents/Belajar/Portofolio_tambbahan/venv/bin/python")
PORT = "8502"  # 8501 dipakai email_categorizer — biar bisa dijalanin paralel

REQUIRED_PKGS = ("streamlit", "pandas")


def ensure_venv() -> None:
    if not VENV_PY.exists():
        return
    current = Path(sys.executable).resolve()
    target = VENV_PY.resolve()
    if current != target:
        print(f"==> Re-exec via venv: {target}")
        os.execv(str(target), [str(target), str(Path(__file__).resolve()), *sys.argv[1:]])


PY = str(VENV_PY) if VENV_PY.exists() else sys.executable


def ensure_deps() -> None:
    missing = []
    for pkg in REQUIRED_PKGS:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return
    print(f"==> Installing missing deps: {', '.join(missing)} …")
    subprocess.check_call([PY, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    subprocess.check_call(
        [PY, "-m", "pip", "install", "--quiet", "-r", str(HERE / "requirements.txt")],
    )
    print("==> Done installing.")


def ensure_env() -> None:
    env = HERE / ".env"
    template = HERE / ".env.example"
    if not env.exists() and template.exists():
        env.write_bytes(template.read_bytes())
        print("==> Created .env from template.")


def main() -> int:
    ensure_venv()
    ensure_deps()
    ensure_env()
    os.chdir(HERE)
    print(f"==> Launching UI at http://localhost:{PORT}")
    print("    (Ctrl+C to stop)")
    os.execvp(PY, [
        PY, "-m", "streamlit", "run", "app.py",
        "--browser.gatherUsageStats", "false",
        "--server.port", PORT,
    ])


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
