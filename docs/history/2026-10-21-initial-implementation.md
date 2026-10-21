# 2026-10-21 · Initial local implementation

Implemented Chinese excerpt lookup and provenance-based original retrieval. The user requested two reader views for surrounding context, so results now open continuous chapter readers with independent scrolling, click-to-position behavior, reviewed-original highlighting, expanded reading, and horizontal/vertical layouts.

Trial import: two existing paired datasets, 15 selected chapters, 521 Chinese paragraphs and 217 extracted original pages. Nine passages in one trial chapter were reviewed against extracted source, including page crossings. Books and mapping exports remain local and ignored.

Validation: all 12 synthetic unit/integration tests passed. They cover normalization, filters, lexical near matches, cross-paragraph queries, full chapter reading data, missing-page rejection, atomic imports, reviewed quotes, noncontiguous-page rejection, version invalidation, running-header cleanup and local HTTP restrictions. JavaScript syntax checks passed. Nine local mappings were exported and restored successfully against the same versions. Browser checks verified a Chinese query, original highlighting, expanded reading at a narrow viewport, clicking a different Chinese paragraph to relocate the original, horizontal/vertical switching, and saving an existing reviewed mapping through the UI.

Source management: a standalone repository was established in the tool's own subdirectory; the parent OCR workspace and existing book files were left intact. The user authorized a new public GitHub repository. Operational guidance is in [local-library.md](../runbooks/local-library.md).
