# WikiWriter Diff Philosophy

## Goal

Show a human reviewer *how much actually changed* in a Wikipedia section edit,
not just *what bytes are different*. A one-word change in a 200-word paragraph
should look small. A full rewrite should look large. Visual weight must be
proportional to semantic change.

## The core failure of naive diffs

Line-by-line or paragraph-by-paragraph diffs treat any paragraph with a single
character change as fully deleted and fully inserted. This makes minor edits
look catastrophic and obscures the actual scope of work. The reviewer cannot
quickly assess whether an edit is safe to accept.

## Design principles

### 1. Always render at the word level

The final display is always an inline word diff — struck-through deletions and
highlighted insertions within a single flow of text. Never show two separate
blocks (old block / new block) for content that is semantically related.

Old:   "Grafana is an open-source analytics and monitoring platform."
New:   "Grafana is an open-source observability platform used for analytics and monitoring."

Bad display (two blocks):
  ~~Grafana is an open-source analytics and monitoring platform.~~
  Grafana is an open-source observability platform used for analytics and monitoring.

Good display (inline):
  Grafana is an open-source ~~analytics and monitoring platform.~~ **observability
  platform used for analytics and monitoring.**

The inline form makes it immediately obvious: two words changed, one phrase was
inserted. The two-block form looks like a full replacement.

### 2. Minimise the number of distinct change blocks shown

Related changes should be grouped. If old sentence A maps to new sentence B,
they produce one inline diff, not two rows. The reviewer's eye should be able
to scan the section and see a small number of highlighted regions, each
representing one logical edit.

### 3. Alignment is a means, not an end

Sentence-level alignment (spaCy segmentation + Heckel + fuzzy pairing) exists
only to answer: "which old content corresponds to which new content?" Once that
question is answered, alignment structure is discarded and word-level diff takes
over for rendering.

Paragraph markers (¶) are shown as lightweight separators to preserve
orientation, not as structural diff units.

### 4. Similarity threshold gates word-level diff

If two sentences are paired but share almost no content (similarity < threshold),
rendering them as a word diff produces noise — spurious highlighted coincidences
like "the" and "and". In that case, show them as independent delete + insert
rather than a misleading inline diff. The threshold is currently 0.25.

Unrelated deletes are shown before unrelated inserts, grouped together, so the
reviewer sees all removals then all additions rather than interleaved noise.

### 5. Moves and merges (aspirational)

When a sentence disappears from one location and its content reappears inside
a rewritten sentence elsewhere, it has been *merged*. This is semantically
different from deletion. Detecting merges requires checking whether a deleted
sentence's content is substantially contained within a new sentence that is
already paired to a different old sentence.

This is not yet implemented. For now, merged content will appear as:
- the source sentence: deleted
- the destination sentence: an expanded rewrite (word diff shows new content
  highlighted, including the absorbed text)

This is acceptable — the reviewer can see both events and connect them.

## Architecture: three phases (after Barabucci 2018)

### Phase 1 — Alignment
- Strip Wikipedia ref tags
- Segment into sentences using spaCy en_core_web_sm
- Align old and new sentence sequences using HeckelSequenceMatcher
- Post-pass: fuzzy-pair orphaned deletes with orphaned inserts above similarity
  threshold (greedy, best-first)

### Phase 2 — Change detection
- For each aligned pair: compute word-level similarity ratio
- Classify as: equal, rewrite (similar enough for word diff), or
  unrelated (independent delete + insert)

### Phase 3 — Rendering
- equal: plain text, no markup
- rewrite: single inline word diff (struck-through deletions, highlighted
  insertions, all in one flow)
- unrelated delete: full sentence struck-through in red block
- unrelated insert: full sentence highlighted in green block
- moved (Heckel): amber block with ↕ label
- paragraph boundary: lightweight ¶ separator

## What we are NOT doing

- Line-by-line diff (obscures proportion)
- Paragraph-as-atom diff (same problem)
- LLM as diff engine (non-deterministic, can hallucinate changes)
- Tree edit distance on prose (segmentation ambiguity makes tree structure
  unreliable for free-form prose)
- Showing "old paragraph / new paragraph" as two separate blocks

## Open questions

- **Merge detection:** can we cheaply detect when a deleted sentence's content
  was absorbed into a neighbouring rewrite? Approach: after pairing, check if
  any unpaired delete has >60% token overlap with any paired new sentence.
- **Threshold calibration:** 0.25 similarity was chosen empirically. Should be
  validated against more real LLM-generated edits.
- **Sub-sentence grouping:** splitting on commas/clauses could improve word-diff
  readability for long sentences. Deferred — spaCy dependency parse would be
  needed to do this reliably.
