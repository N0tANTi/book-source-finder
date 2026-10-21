# Current state

Verified on 2026-10-21 (America/Los_Angeles).

- First local implementation: Python standard library + SQLite + buildless HTML/CSS/JS. Starts with `python -m source_finder serve`; Windows launcher `start.cmd`.
- Query copied Chinese text, ignore punctuation/spacing, offer labeled lexical near matches, filter by book/chapter, and display source print/PDF page numbers.
- Two continuous chapter readers, independent scrolling, clickable translation paragraphs, original highlighting for reviewed mappings, expanded reading, and horizontal/vertical layout switching.
- Imports paired text with explicit page markers. Includes an adapter for two existing workspace book datasets. Each book is validated before one transaction; changed chapter files/configurations invalidate confirmations.
- Human review saves contiguous source selections of up to four pages; exports can be restored only against matching versions.
- Local trial library: two books, 15 selected chapters, 521 Chinese paragraphs, 217 original pages. Nine reviewed mappings in the trial chapter. All actual book data, paths, and mapping exports are ignored and are absent from the public repository. A fresh clone starts empty.
- Automated and browser validation details are recorded in [initial implementation history](docs/history/2026-10-21-initial-implementation.md).

Limitations: most paragraphs have page provenance only; no automatic cross-language semantic alignment, semantic query, direct PDF/EPUB import, original PDF page-image reader, or cross-chapter reading navigation. Existing OCR errors and split words remain visible. Only selected chapters are imported. The initial trial confirms correspondence to extracted source text, not a fresh visual check of every original PDF page.

GitHub holds source code, not a backup of the local library. Independent off-host backup for books/configuration has not been configured by this tool. See [local operations](docs/runbooks/local-library.md) and [roadmap](ROADMAP.md).
