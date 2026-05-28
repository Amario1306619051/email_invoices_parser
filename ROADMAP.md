# Roadmap / Notes

Planned future work. Each item is written issue-style so it can be copy-pasted into GitHub Issues.

---

## LLM-based invoice classification (replace `[Invoice]` subject marker)

**Status:** planned

**Current behavior**

Email classification is purely a subject-line filter: only emails whose subject **contains `[Invoice]`** (case-insensitive, anywhere in the subject) + has an attachment + is unread + does not yet have the `Invoice/Processed` label are picked up. The marker is `INVOICE_SUBJECT_MARKER` in [gmail_client.py](gmail_client.py), pushed into the Gmail query so it runs server-side.

**Limitation**

This depends on the sender (or a mail rule) tagging the subject with `[Invoice]`. Real invoices that don't follow this convention are silently skipped, and non-invoices that happen to contain the marker get processed.

**Proposed**

Use an LLM to decide whether an email actually *is* an invoice, based on its content (subject + body + attachment metadata, or a cheap first-page render), instead of relying on the subject marker.

- Keep a cheap pre-filter (has attachment + unread + not yet processed) to limit how many emails hit the LLM.
- Add a classification step before extraction: feed subject/body (and optionally the first rendered page) to an LLM → `is_invoice: bool` + confidence + reason.
- Reuse the existing engine switch (LightOn / GPT-4o) so the classifier shares config with the extractor.
- Make the threshold/behavior configurable; fall back to the `[Invoice]` marker when the LLM is unavailable or low-confidence.

**Open questions**

- Cost: classifying every candidate email vs. only ambiguous ones.
- Whether to classify on text only (cheap) or also vision (first page render) for image-only emails.
- How to handle false negatives without a human-in-the-loop review step.
