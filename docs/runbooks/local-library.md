# Local operation and recovery

Prerequisites: Python 3.10+, UTF-8 original and translated files with explicit page markers; Node only for JS development checks. Run commands in this repository.

## Run and import

1. Keep source texts and import specs in ignored `local/` or an existing local book workspace. Do not move or modify originals merely to import.
2. Import with `python -m source_finder import-book local/book.json`, or use the workspace adapter documented in [README](../../README.md).
3. Run `python -m source_finder serve`. The service listens only on loopback; use its printed URL. Stop foreground execution with Ctrl+C. `start.cmd` offers the Windows entry point.
4. Check the library counts, search a known Chinese passage, verify print/PDF page numbers, then read both panes. Sample at least one page crossing and distinguish reviewed snippets from page-only locations.

Same-version reimports preserve confirmations. Modified chapter source/translation or page-parsing configuration clears that chapter's confirmations. Removing a chapter from a spec removes it from the local index. Inspect the intended import scope and export confirmations first.

## Mapping snapshots and recovery

- Destination: ignored `data/backups/YYYY-MM-DD/alignments.json`; add a distinct timestamp for another snapshot on the same day. No automatic schedule is installed.
- Export: `python -m source_finder export-alignments data/backups/YYYY-MM-DD/alignments.json`.
- Preserve original/translation files and the local spec alongside the mapping snapshot in a user-selected backup location. The mapping export contains book text; never add it to GitHub. No off-host destination is currently configured.
- Default retention for a future scheduled producer: seven verified daily sets. Do not delete existing snapshots without verifying scope, recoverability, and authorization.
- Verify recovery against a separate temporary database: `python -m source_finder --db data/recovery-check.sqlite3 import-book local/book.json`, followed by `python -m source_finder --db data/recovery-check.sqlite3 restore-alignments data/backups/YYYY-MM-DD/alignments.json`. Compare mapping count and at least one quoted source. Use the workspace adapter instead when that was the original import path.
- Matching source/translation/configuration versions are required. A mismatch must fail rather than force old mappings into new text. Recreating a library requires the book files as well as this code.

Avoid copying a database during active writes as a backup. Stop the app before taking a full database copy; mapping exports are read through SQLite and can be made while the service runs. For a bad import, reimport the preserved original versions into a separate database, restore the verified mappings there, validate, then stop the app and switch databases. Retain the previous database until the replacement is checked.
