# Full pairs and mixed-library lookup

The initial failed lookup was scoped to a legacy selection with a similar title, rather than the complete recently translated book. The local library now includes the complete *Intimacies* (Bersani/Phillips) and *Stanzas* (Agamben) PDF/Chinese-EPUB pairs. Existing selections and reviewed mappings are preserved.

- Intimacies: 134-page original; 249 extracted original units and 402 Chinese units across 9 EPUB reading sections.
- Stanzas: 203-page original with a usable text layer; 573 extracted original units and 1144 Chinese units across 48 EPUB reading sections. The alternative 183-page scan lacked a usable text layer and was not imported. No OCR or network processing was performed.
- Both imports have zero vectors and no indexing job. The user explicitly selected local import only. No actual book text or query was sent to Cloudflare for this work; model quality remains unevaluated.
- Local disk capacity before import: about 270 GB free of 476 GB. Originals were preserved, and retained copies plus SQLite metadata stay in ignored local storage. The ignored local import manifest records exact input paths; GitHub contains no book files or passages.

File books now appear before legacy selections. All-books search includes both formats and suppresses approximate results when exact matches exist. Book changes update the visible scope and model availability, and no-results messaging no longer incorrectly says every book is only a selection. An independent original-location selector permits browsing unindexed source sections through the final text-bearing pages without treating manual navigation as alignment.

Validation: 23 automated tests pass, browser JavaScript syntax checks pass, and browser checks confirmed exact lookup of the reported term in the full book and across the library. Both actual pairs open in dual readers; original navigation reaches the final PDF window while retaining the unaligned label. No Cloudflare call was made. Recovery remains the database and retained files together, as described in the [local runbook](../runbooks/local-library.md).
