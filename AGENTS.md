# Project agreements

- This directory is the standalone `book-source-finder` Git repository. Do not initialize, stage, reorganize, or modify the parent OCR workspace or its other projects as part of tool maintenance.
- The public repository contains only application source, docs, and synthetic fixtures. Never commit book contents, translated passages, local configuration, absolute personal paths, SQLite databases, alignment exports, screenshots, model caches, or credentials. Use ignored `data/` and `local/` directories.
- Keep the application local and dependency-free unless requirements justify a change. Binding to a public interface or uploading books requires explicit user authorization.
- Page provenance and reviewed paragraph mappings are distinct states. Never label page guesses, sequence/length heuristics, or model scores as reviewed alignment.
- Preserve raw extracted text. Display cleanup must be deterministic and documented. Source or translation changes must invalidate obsolete confirmations.
- Context records: `CURRENT_STATE.md`, `ROADMAP.md`, reusable operations in `docs/runbooks/`, material history in `docs/history/`. Read the first two and this file before maintenance; update records at material milestones rather than every conversation.
- Run meaningful tests with `python -m unittest discover -s tests -v`; check changed browser JavaScript with `node --check source_finder/static/app.js`. For UI changes, verify the actual local interface and both reading panes when browser tools are available.
- Before pushing, inspect the staged file list and diff for accidental book text, runtime files, or sensitive paths. Preserve unrelated work.
