"""Debug: list semua email kandidat tanpa filter, lalu cek satu-satu kenapa
gak match. Tidak menyentuh attachment / AI / output — read-only inspection."""
from __future__ import annotations

import sys

from gmail_client import _build_service, _header, _walk_parts, INVOICE_SUBJECT_MARKER


def main():
    service = _build_service()
    # Coba berbagai query, dari paling longgar ke paling ketat
    queries = [
        ('Semua unread 50 terbaru', 'is:unread'),
        ('Unread + attachment', 'has:attachment is:unread'),
        ('Unread + attachment + [Invoice]', 'has:attachment is:unread subject:"[Invoice]"'),
        ('Subject [Invoice] (apa pun, read/unread)', 'subject:"[Invoice]"'),
    ]
    for label, q in queries:
        print(f'\n=== {label} ===')
        print(f'Query: {q}')
        resp = service.users().messages().list(userId='me', q=q, maxResults=20).execute()
        ids = [m['id'] for m in resp.get('messages', [])]
        print(f'Hits: {len(ids)}')
        for mid in ids[:10]:
            msg = service.users().messages().get(
                userId='me', id=mid, format='metadata',
                metadataHeaders=['Subject', 'From', 'Date']
            ).execute()
            headers = msg['payload'].get('headers', [])
            subj = _header(headers, 'Subject')
            sender = _header(headers, 'From')
            date = _header(headers, 'Date')
            labels = msg.get('labelIds', [])
            is_unread = 'UNREAD' in labels
            has_marker = INVOICE_SUBJECT_MARKER in subj.lower()
            print(f'  - {subj[:60]:60s} | {"UNREAD" if is_unread else "READ":6s} | [Invoice]?{has_marker}')
            print(f'    from: {sender[:50]}')
            print(f'    date: {date}')


if __name__ == '__main__':
    main()
