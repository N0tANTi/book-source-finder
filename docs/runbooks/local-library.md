# Local operation and recovery

Prerequisites: Python 3.10+ and the installed package (`pip install -e .`, including `pypdf`); Node only for JS development checks. GUI imports support EPUB/PDF/UTF-8 text with no manual page markers. Legacy CLI page imports still require explicit markers. Run commands in this repository.

## File-library storage and model state

- Original and translation copies: ignored `data/books/<book-id>/source.*` and `translation.*`. Keep indefinitely while the entry is used; no automatic book deletion or retention cleanup is installed. New books get unique directories, existing files are never overwritten. Exact pair hashes deduplicate reimports.
- Extracted units, human pair confirmations, per-model vectors, progress and query-vector cache: `data/library.sqlite3`. Per-book model vectors are reusable derived data; query-vector cache is disposable and limited to the latest 500 entries. There is no on-server build or model-weight cache.
- Upload limits: 80 MB per file, 200 MB expanded EPUB content, 3000 PDF pages and 30000 text units per document. Import checks local free space for a bounded projected peak and 10% headroom before retaining files. Text/EPUB extraction is local; no network OCR is performed.
- Credentials: `data/cloudflare.protected.json` uses current-user Windows DPAPI; it cannot simply be decrypted under a different OS account. Other platforms keep UI-entered tokens only in the running process. Environment variables are also supported. Do not include the vault in logs, screenshots or public Git.
- Indexing explicitly transmits the selected book's extracted original/translation to Cloudflare. One book at a time, 24 units per batch, 2 million input characters maximum per run. Completed vectors survive quota/network errors. On restart, jobs become paused; continue from the shelf. This bounds requests but is not a provider billing-limit setting.
- Test the configured account with the constant-text connection test, then index one actual book and verify candidates against reviewed text. Existing synthetic tests do not establish real-account connectivity or model quality.
- For a full new-format library backup, stop the service and preserve the database, `data/books/` and applicable import settings together in a user-selected secure destination. The legacy alignment JSON export does not include new-format book-pair confirmations. Copying only code or only vectors does not restore the books. Use the full SQLite database plus files for new-format recovery; reconfigure cloud credentials after restoring under another Windows account.
- No off-host backup destination or recurring backup producer is configured. Do not delete QA libraries, books or existing backup sets to enforce a new retention default without explicit scope and recovery validation.
- Diagnostic-only material is kept in ignored `data/qa/` (synthetic book database/files) and `screenshots/` (UI captures); default retention is 14 days, with no automatic deletion installed. Verify that a diagnostic directory contains only intended disposable material before removing it. These directories are not part of library recovery.
- A locally launched background service records its process ID in ignored `data/server.pid`; startup/error output goes to `data/server.log` and `data/server-error.log`. Before stopping a stored PID, inspect the live process and verify it is this repository's Python service, since PIDs can be reused. Logs are disposable diagnostics with 14-day retention; no scheduled cleanup is installed, and the launcher reuses its two log paths. No automatic login/startup registration is installed.

## Run and import

1. Keep source texts and import specs in ignored `local/` or an existing local book workspace. Do not move or modify originals merely to import.
2. Import with `python -m source_finder import-book local/book.json`, or use the workspace adapter documented in [README](../../README.md).
3. Run `python -m source_finder serve`. The service listens only on loopback; use its printed URL. Stop foreground execution with Ctrl+C. `start.cmd` offers the Windows entry point.
4. Check the library counts, search a known Chinese passage, verify print/PDF page numbers, then read both panes. Sample at least one page crossing and distinguish reviewed snippets from page-only locations.

For file pairs, choose the translation chapter from the top selector and browse the original independently with its location selector. PDFs use windows of up to 12 document pages; blank/image-only pages have no extracted text. A manual original-location change without an index remains unaligned, with no confirmation claim. Text search across all books includes both full file imports and legacy selections. Importing a file pair does not create a model job or vectors; check its shelf status before starting an explicitly authorized indexing action.

The reading page now uses a compact toolbar and two viewport-height panes. Its default automatic search uses exact Chinese lookup first; for a single indexed book, an unmatched description is sent to Cloudflare. Existing query vectors are cached locally. The settings menu offers text-only mode and chapter filtering; the result count opens the collapsed result list. Use the Chinese pane's chapter selector to navigate reading chapters, and the original pane's candidate selector or More menu to browse/copy original text. All-books lookup remains local text search. Semantic search prefers units with at least 60 normalized characters when available; exact text results still include titles and short passages. Opening a selected chapter prefers its first prose unit so a heading alone does not drive the original match.

Display-only cleanup omits repeated units exactly matching the current EPUB section title and a first unit consisting solely of an XHTML filename. Section labels remain in navigation; raw extracted units and their vectors are unchanged. PDF excerpts retain extraction/OCR artifacts. A candidate highlights the retrieved original unit, which may contain several sentences or cover only part of a translated paragraph.

Same-version reimports preserve confirmations. Modified chapter source/translation or page-parsing configuration clears that chapter's confirmations. Removing a chapter from a spec removes it from the local index. Inspect the intended import scope and export confirmations first.

## Mapping snapshots and recovery

- Destination: ignored `data/backups/YYYY-MM-DD/alignments.json`; add a distinct timestamp for another snapshot on the same day. No automatic schedule is installed.
- Export: `python -m source_finder export-alignments data/backups/YYYY-MM-DD/alignments.json`.
- Preserve original/translation files and the local spec alongside the mapping snapshot in a user-selected backup location. The mapping export contains book text; never add it to GitHub. No off-host destination is currently configured.
- Default retention for a future scheduled producer: seven verified daily sets. Do not delete existing snapshots without verifying scope, recoverability, and authorization.
- Verify recovery against a separate temporary database: `python -m source_finder --db data/recovery-check.sqlite3 import-book local/book.json`, followed by `python -m source_finder --db data/recovery-check.sqlite3 restore-alignments data/backups/YYYY-MM-DD/alignments.json`. Compare mapping count and at least one quoted source. Use the workspace adapter instead when that was the original import path.
- Matching source/translation/configuration versions are required. A mismatch must fail rather than force old mappings into new text. Recreating a library requires the book files as well as this code.

Avoid copying a database during active writes as a backup. Stop the app before taking a full database copy; mapping exports are read through SQLite and can be made while the service runs. For a bad import, reimport the preserved original versions into a separate database, restore the verified mappings there, validate, then stop the app and switch databases. Retain the previous database until the replacement is checked.
