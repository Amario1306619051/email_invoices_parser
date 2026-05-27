# Invoice Automation

Otomatisasi end-to-end: dari email Gmail → klasifikasi → render PDF/image → vision OCR (LightOn OCR atau GPT-4o) → validasi → CSV.

## Tampilan UI

Streamlit UI di `http://localhost:8502` (jalankan via `python start.py`).

**All Invoices — tabel hasil ekstraksi + validation flag:**

![All Invoices view](docs/ui-with-data.png)

**Empty state — sidebar Run Settings (Source / Engine / Outputs):**

![Run Settings sidebar](docs/ui-main.png)

Sesuai flowchart:

```
Gmail (time_init, time_final)
        ↓
Klasifikasi + Mark as read
        ↓
Render PDF/image → PNG (PyMuPDF)
        ↓
Pilih engine: LightOn OCR  ATAU  GPT-4o (vision)
        ↓
Validasi → CSV (default)  [Excel + Google Sheet opsional]
```

> **Catatan**: Pipeline ini **image-first**. PDF native pun di-render ke PNG dulu, bukan ekstrak teks layer-nya. Ini supaya engine pilihan (LightOn OCR / GPT-4o) selalu lihat dokumen yang sama dengan mata-nya sendiri.

## Struktur

```
invoice_automation/
├── main.py              # orchestrator (CLI)
├── gmail_client.py      # Gmail API monitor + classify + mark read
├── pdf_to_images.py     # PDF/image → list of PNG (PyMuPDF + Pillow)
├── ai_extractor.py      # engine switch: lighton | gpt-4o  (schema = source of truth)
├── validator.py         # cross-check line items
├── csv_exporter.py      # CSV (default) — kolom otomatis ikut EXTRACTION_SCHEMA
├── excel_exporter.py    # openpyxl, opsional (--excel)
├── sheets_exporter.py   # gspread, opsional (--sheets)
├── config.py            # env loader
├── requirements.txt
├── install.sh
├── .env.example
├── credentials/         # OAuth + service-account JSON (gitignored)
├── downloads/           # attachment + rendered pages
└── output/              # CSV + JSON dump + (opsional) xlsx
```

## Setup

### 1. Install Python deps

```bash
cd /home/rnd/Documents/Belajar/Portofolio_tambbahan/invoice_automation
./install.sh
```

Atau manual:

```bash
/home/rnd/Documents/Belajar/Portofolio_tambbahan/venv/bin/pip install -r requirements.txt
```

> Tidak butuh Tesseract lagi — OCR dilakukan oleh LightOn / GPT-4o.

### 2. Isi `.env`

```bash
cp .env.example .env && nano .env
```

Minimal yang harus diisi:

```env
DEFAULT_AI_ENGINE=lighton          # atau gpt-4o

# kalau pakai LightOn:
LIGHTON_API_KEY=<your key>
LIGHTON_BASE_URL=https://api.lighton.ai/v1   # atau endpoint vLLM lokal
LIGHTON_MODEL=lighton-ocr

# kalau pakai GPT-4o:
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

### 3. Kredensial Google

- **Gmail OAuth client**: Google Cloud Console → APIs & Services → Credentials → Create OAuth client ID (Desktop) → simpan JSON ke `credentials/gmail_credentials.json`.
- Run pertama akan membuka browser untuk OAuth Gmail, token disimpan ke `credentials/gmail_token.json`.
- *(opsional)* **Service Account untuk Sheets**: kalau Anda butuh `--sheets`, buat service account, taruh JSON di `credentials/sheets_service_account.json`, lalu share Sheet target ke email service account-nya.

## Pemakaian

```bash
source /home/rnd/Documents/Belajar/Portofolio_tambbahan/venv/bin/activate

# Default: ambil email kemarin pukul 00:00 sampai sekarang, pakai LightOn → tulis CSV
python main.py --since "2026-05-17 00:00" --until "2026-05-18 23:59" --engine lighton

# Shortcut: 24 jam terakhir, pakai GPT-4o
python main.py --last-hours 24 --engine gpt-4o

# Fallback manual untuk file dari luar email (bisa diulang)
python main.py --file /path/to/invoice1.pdf --file /path/to/receipt.jpg

# Tambahkan Excel
python main.py --last-hours 6 --excel

# Tambahkan Google Sheets (perlu service account JSON + SHEET_ID di .env)
python main.py --last-hours 6 --sheets

# Testing: jangan apply label processed (email akan dipick lagi run berikutnya)
python main.py --last-hours 24 --no-mark-processed
```

Hasil:

- `output/invoices.csv` — satu baris per invoice, append-mode (default).
- `output/invoices.xlsx` — opsional via `--excel`, baris ber-flag disorot merah.
- Google Sheet — opsional via `--sheets`.
- `output/run_*.json` — dump JSON mentah untuk debugging / Loom walkthrough.
- `downloads/pages/` — PNG hasil render per halaman (berguna saat debugging).
- `logs/run.log` — log per eksekusi.

## Kolom CSV (auto-derived)

Kolom otomatis ngambil dari `EXTRACTION_SCHEMA` di [ai_extractor.py](ai_extractor.py#L17). Tambah/hapus field di dict itu — prompt ke AI **dan** kolom CSV langsung ikut.

Urutan saat ini:

1. **Metadata**: `received_at`, `source` (gmail/manual), `email_subject`, `attachment_file`
2. **Dari AI**: `vendor_name`, `invoice_number`, `invoice_date`, `due_date`, `subtotal`, `tax`, `total`, `currency`, `payment_terms`
3. **Turunan**: `line_items_json`, `line_items_count`, `validation_ok`, `validation_issues`

## Validasi

Otomatis flag baris jika:

- Field wajib hilang (`vendor_name`, `invoice_number`, `invoice_date`, `total`)
- Σ `quantity × unit_price` per line ≠ `amount`
- Σ line item ≠ `subtotal`
- `subtotal + tax` ≠ `total`

Tolerance: 0.02 (rounding).

## Catatan engine

| Engine | API spec | Cocok kalau... |
|---|---|---|
| **lighton** | OpenAI-compatible (`/v1/chat/completions`) | Pakai layanan LightOn cloud, atau host LightOnOCR-1B sendiri via vLLM |
| **gpt-4o** | OpenAI native | Akurasi tinggi out-of-the-box, butuh credit OpenAI |

**Klasifikasi email**: hanya email yang subject-nya **mengandung `[Invoice]`** (di mana saja — depan, tengah, belakang; case-insensitive) + ada attachment + status unread + **belum punya label `Invoice/Processed`**. Filter ini diterapkan sekaligus di Gmail query supaya server-side, lebih cepat. Edit `INVOICE_SUBJECT_MARKER` di [gmail_client.py](gmail_client.py) kalau mau ganti penanda.

**Tracking sudah-diproses**: Setelah ekstraksi sukses, pipeline apply label Gmail **`Invoice/Processed`** ke email. Status email **tetap UNREAD** (boleh dicek manual oleh tim Anda di inbox), tapi run berikutnya akan skip email tsb otomatis. Mau reproses paksa? Hapus label `Invoice/Processed` di Gmail UI.
