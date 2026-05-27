"""Centralized configuration loaded from environment variables."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ---- AI / OCR engines ----
DEFAULT_AI_ENGINE = os.getenv("DEFAULT_AI_ENGINE", "lighton").lower()

# LightOn OCR (OpenAI-compatible endpoint)
LIGHTON_API_KEY = os.getenv("LIGHTON_API_KEY", "")
LIGHTON_BASE_URL = os.getenv("LIGHTON_BASE_URL", "https://api.lighton.ai/v1")
LIGHTON_MODEL = os.getenv("LIGHTON_MODEL", "lighton-ocr")

# OpenAI GPT-4o (vision)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# ---- Gmail ----
GMAIL_CREDENTIALS_PATH = BASE_DIR / os.getenv(
    "GMAIL_CREDENTIALS_PATH", "credentials/gmail_credentials.json"
)
GMAIL_TOKEN_PATH = BASE_DIR / os.getenv(
    "GMAIL_TOKEN_PATH", "credentials/gmail_token.json"
)
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# ---- Sheets (opsional) ----
GOOGLE_SHEETS_CREDENTIALS_PATH = BASE_DIR / os.getenv(
    "GOOGLE_SHEETS_CREDENTIALS_PATH", "credentials/sheets_service_account.json"
)
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SHEET_TAB = os.getenv("GOOGLE_SHEET_TAB", "Invoices")

# ---- Folders ----
DOWNLOADS_DIR = BASE_DIR / "downloads"
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"
CSV_OUTPUT_PATH = BASE_DIR / os.getenv("CSV_OUTPUT_PATH", "output/invoices.csv")
EXCEL_OUTPUT_PATH = BASE_DIR / os.getenv("EXCEL_OUTPUT_PATH", "output/invoices.xlsx")

for d in (DOWNLOADS_DIR, OUTPUT_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---- Classification ----
# Hanya email dengan subject mengandung "[Invoice]" yang diproses.
# Lihat gmail_client.INVOICE_SUBJECT_MARKER kalau mau ubah.

# Label Gmail yang diterapkan ke email yang sudah diproses (tetap unread,
# tapi di-exclude dari query berikutnya supaya gak diproses dua kali).
GMAIL_PROCESSED_LABEL = os.getenv("GMAIL_PROCESSED_LABEL", "Invoice/Processed")
