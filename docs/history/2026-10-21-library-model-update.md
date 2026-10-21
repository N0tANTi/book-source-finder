# 2026-10-21 · Paired-file library and optional model

The user requested a library rather than a query-form homepage, with one original and one translated book per entry. Typical inputs are an EPUB translation and PDF/EPUB original.

Implemented a book shelf, title filter, paired drag/drop/file chooser, local text extraction and independent file location records. Both documents must parse before a book is retained; duplicate pairs reuse the existing entry. Legacy page-mapped books and their nine reviewed mappings remain intact. Uploaded files, metadata, vectors, credentials and QA material remain ignored.

Added BGE-M3 through Cloudflare's OpenAI-compatible embeddings endpoint, local settings/test UI, Windows DPAPI token storage, disclosed indexing/query actions, resumable partial vectors, a per-run character cap and a bounded query cache. Matching candidates are clearly distinguished from human confirmations. No real provider call was made: user credentials are still required.

Validation: 21 automated tests pass. Synthetic EPUB/EPUB and PDF/EPUB imports, malformed/scan rejection, duplicate imports, atomic validation, Windows vault roundtrip, mocked indexing/query/cache and HTTP upload/model flows are covered. Browser QA opened the new shelf and paired-file dialog, then used an isolated synthetic book and mocked vectors to verify candidate relocation and human confirmation in both readers. The isolated QA server was stopped afterward. Live model quality is an explicit next step in [ROADMAP](../../ROADMAP.md).
