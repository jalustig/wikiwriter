# WikiWriter Diff Algorithm — Formal Specification

## Overview

A three-pass pipeline that produces an inline word-level diff of a Wikipedia
section edit. Citations are first-class elements — they participate in alignment
and are rendered as coloured superscript numbers inline, with full content shown
in a footnote list at the bottom.

```
Input: original (str), revised (str)    [Wikipedia wikitext, single section]
Output: HTML string (x2)               [superscript mode, raw wikitext mode]
```

---

## Data model

Each element in the flat sequence fed to the aligner is one of:

```python
@dataclass
class Token:
    kind: Literal["sentence", "citation"]
    text: str          # prose text (sentence) or raw wikitext (citation)
    para_idx: int      # paragraph index in the revised document
```

A `sentence` token is clean prose — no `<ref>` markup.
A `citation` token is the full raw wikitext of one `<ref>...</ref>` block.

---

## Phase 1 — Segmentation

### 1a. Paragraph splitting

Split on two or more consecutive newlines. Empty paragraphs discarded.
Each paragraph retains its index `p ∈ {0, 1, 2, ...}`.

### 1b. Citation extraction and sentence splitting

For each paragraph:

1. **Insert a space before every `<ref>`** so that citations cannot be fused
   to the preceding word after splitting:
   ```
   "Go.<ref>..." → "Go. <ref>..."
   ```

2. **Split the paragraph into alternating prose runs and citation blocks**
   using a regex that finds all `<ref>...</ref>` and `<ref.../>` spans.
   Between and around each citation block are prose runs.

3. **Feed each prose run through spaCy** (`en_core_web_sm`, NER and
   lemmatizer disabled) to get sentence boundaries. spaCy handles
   abbreviations ("U.S.", "Dr."), initials ("James O. McKinsey"), and
   Wikipedia prose edge cases. Regex splitting was rejected for brittleness.

4. **Interleave** the resulting sentence tokens and citation tokens in
   document order. A citation appears in the sequence immediately after the
   sentence token it follows in the source text:

   ```
   Input:  "Sentence A.<ref>X</ref> Sentence B.<ref>Y</ref><ref>Z</ref>"
   Output: [sentence("Sentence A."), citation(X),
            sentence("Sentence B."), citation(Y), citation(Z)]
   ```

This produces a flat list `tokens: list[Token]` for each document, preserving
both prose and citation order.

### Why citations as sequence elements?

Treating citations as first-class sequence elements means:
- A citation that moves to a different sentence → `move` opcode
- A citation whose URL or date changes → `replace` with field-level diff
- A new citation → `insert` (shown in green)
- A removed citation → `delete` (shown in red)
- An unchanged citation in the same position → `equal` (shown in grey)

This avoids the distortion problem (citation markup inflating word-level
similarity scores) while preserving citation change information that would be
lost by stripping.

---

## Phase 2 — Alignment

### 2a. Heckel alignment

`HeckelSequenceMatcher` runs on the flat token text lists (prose sentences and
citation wikitext interleaved). Heckel tracks element identity, enabling
`move`/`moved` opcodes for tokens that appear verbatim in both documents.

Opcodes produced: `equal`, `replace`, `insert`, `delete`, `move`, `moved`.

### 2b. Similarity function (kind-aware)

Similarity is computed differently depending on token kind:

**Sentence pairs:**
```
sim = SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()
```
Token unit: words. `autojunk=False` because Wikipedia sentences are short and
common words ("the", "and", "of") are semantically relevant.

**Citation pairs:**
```
1. Extract URL from both (regex on href/url= parameter)
2. If both have a URL:
     if URLs match exactly → sim = 1.0 (same source, possibly updated metadata)
     else → fall back to full-text lexical similarity
3. If no URL in either → full-text lexical similarity
```
Two citations to the same URL but different access-dates score 1.0 and align
as `equal` (or `replace` if other fields differ). Two citations to different
domains score low and are treated as independent delete + insert.

**Cross-kind pairs (sentence vs citation):** sim = 0.0 always. A sentence and
a citation are never paired.

### 2c. Similarity-gated replace expansion

For each `replace` opcode, Heckel pairs elements positionally. Each positional
pair is tested:

- `sim >= MIN_SIMILARITY`: accept → emit `replace`
- `sim < MIN_SIMILARITY`: reject → emit `delete` + `insert` (both become orphans)

Thresholds:
- Prose sentences: `MIN_SIMILARITY = 0.25`
- Citations: `MIN_CITATION_SIMILARITY = 0.5` (higher because citation text is
  formulaic; a low score means a genuinely different source)

### 2d. Fuzzy orphan pairing

Greedy best-first pass over unmatched `delete` and `insert` orphans of the
same kind:

```
for each delete orphan d (in order):
    find insert orphan i* = argmax sim(d, i) over unused same-kind insert orphans
    if sim(d, i*) >= threshold:
        pair (d, i*) → replace
        mark i* as used
```

Sentences are only paired with sentences; citations only with citations.

---

## Phase 3 — Rendering

Two output modes share the same diff ops but differ in how citations are shown.

### Citation numbering

Before rendering, assign a display number to every citation token that appears
in the **revised** document sequence (equal, replace-new, insert, moved-new),
in document order: [1], [2], [3], ...

Old-only citations (delete, replace-old) share a number with their paired new
citation if one exists, otherwise get a number from the old document sequence.

### Mode A — Superscript mode (focus on prose)

**Prose tokens** render exactly as in the prose-only algorithm (equal/replace/
delete/insert inline word diff).

**Citation tokens** render as a coloured superscript immediately after the
preceding prose token:

| Op | Superscript style |
|----|-------------------|
| `equal` | `[N]` grey |
| `replace` | `[N]` amber (modified) |
| `insert` | `[N]` green (added) |
| `delete` | `[N]` red, strikethrough (removed) |
| `move`/`moved` | `[N]` blue (repositioned) |

At the bottom of the diff, a **footnote list** shows the full citation content
with the same colour coding. For `replace` citations, the footnote shows a
field-level diff of the wikitext (which field changed: URL, title, access-date).

### Mode B — Raw wikitext mode

**Prose tokens** render as in Mode A.

**Citation tokens** render inline as their full raw wikitext, highlighted with
the same colour scheme as Mode A but shown in a monospace `<code>` block
instead of a superscript.

---

## Similarity metrics summary

| Context | Tokenisation | Threshold |
|---------|-------------|-----------|
| Prose sentence pairs | words | 0.25 |
| Citation pairs | words (full wikitext) | 0.50 |
| Cross-kind pairs | — | 0.0 (never paired) |

---

## Known limitations

### Merge detection not implemented
When old sentence A is absorbed into a rewrite of new sentence B, old sentence
A appears as `delete` and the absorbed content as highlighted `insert` within
B's word diff. The reviewer sees both events but no explicit "merged" label.
Detection approach (deferred): check if any `delete` orphan has >60% token
overlap with the inserted portion of any `replace` op.

### Greedy pairing suboptimal for large orphan pools
For typical section sizes (3–8 sentences) greedy is correct in practice.
Optimal bipartite matching (O(n³)) is not warranted until we see evidence of
systematic mismatch.

### MIN_SIMILARITY thresholds are empirically chosen
0.25 (prose) and 0.50 (citation) need validation against a labelled set of
real LLM-generated edits.

### Named back-references (`<ref name="foo"/>`)
These are self-closing refs that point to a citation defined elsewhere in the
article. They contain no content. They are treated as citation tokens with text
equal to their raw wikitext. If the named citation they point to is not in
scope (defined in another section), we cannot resolve their content for display.
Shown as `[ref:foo]` in superscript mode.
