# Current state

Verified on 2026-10-21 (America/Los_Angeles).

- Version 0.2: local book-library homepage, paired EPUB/PDF/Markdown/TXT import by file chooser or drag/drop, plus the existing legacy page-aligned datasets. Python + SQLite + `pypdf` + buildless HTML/CSS/JS. Windows launcher prefers the repository `.venv` when present.
- Query copied Chinese text, ignore punctuation/spacing, offer labeled lexical near matches, filter by book/chapter, and display source print/PDF page numbers.
- Two continuous chapter readers, independent scrolling, clickable translation paragraphs, original highlighting for reviewed mappings, expanded reading, and horizontal/vertical layout switching.
- Imports paired text with explicit page markers. Includes an adapter for two existing workspace book datasets. Each book is validated before one transaction; changed chapter files/configurations invalidate confirmations.
- Human review saves contiguous source selections of up to four pages; exports can be restored only against matching versions.
- New file-library mode preserves uploaded files under ignored `data/books/<id>/`, extracts independent source/translation locations without requiring matching page numbers, and deduplicates identical file pairs. PDF scans without text require prior OCR. EPUB chapters and PDF document pages retain their own location labels.
- Cloudflare BGE-M3 integration: local settings/test-connection UI, Windows DPAPI credential storage (session-only on other OSes), resumable batch indexing, local cross-language vector candidate lookup, optional semantic query and candidate confirmation. Cloud calls require user-entered credentials; indexing and semantic search disclose the transmitted texts.
- Local trial library: two books, 15 selected chapters, 521 Chinese paragraphs, 217 original pages. Nine reviewed mappings in the trial chapter. All actual book data, paths, and mapping exports are ignored and are absent from the public repository. A fresh clone starts empty.
- Validation: 21 automated tests pass, including real synthetic EPUB/PDF upload and simulated model indexing/query. Browser checks confirm library/import/settings interfaces and a new-file dual-reader candidate/confirmation flow in an isolated QA database. No real Cloudflare request has been verified without user credentials. Details: [library update](docs/history/2026-10-21-library-model-update.md).

Limitations: legacy books remain page-based unless manually reviewed and are not automatically vector indexed. New model matches are candidates, not verified sentence/word alignments. No automatic OCR, DRM removal, original PDF page-image reader, or exact bilingual word selection. Mixed scanned/text PDFs only index extractable text; original layout/order can differ after extraction. Live Cloudflare availability and quality on these actual books remain unverified until credentials are configured and a reviewed sample is evaluated.

GitHub holds source code, not a backup of the local library. Independent off-host backup for books/configuration has not been configured by this tool. See [local operations](docs/runbooks/local-library.md) and [roadmap](ROADMAP.md).
