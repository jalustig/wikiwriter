# Notes: "diffi: diff improved; a preview" (Barabucci, 2018)

**Citation:** Barabucci, G. DocEng '18, ACM Symposium on Document Engineering, August 28–31, 2018, Halifax, NS, Canada. https://doi.org/10.1145/3209280.3229084

## What it is

A prototype tool (`diffi`) built on top of the 2016 metrics paper. Its goal is format-agnostic document comparison — comparing documents at multiple levels of abstraction simultaneously, including across different formats (e.g. ODT vs HTML).

## Core concept: documents as stacks of abstraction levels

Documents are modelled as stacks: bitstream → encoding → Unicode → XML → paragraphs → etc. `diffi` finds which levels of two documents are comparable (share the same model), runs an appropriate diff algorithm at each level, and reports differences at all levels simultaneously.

The key claim: most diff tools are locked to one level (e.g. GNU diff at the line/byte level). `diffi` lets users choose which level they care about.

## The three-phase comparison model

Every diff algorithm can be described as:
1. **Structural alignment** — find what corresponds to what
2. **Change detection** — identify what differs in aligned pairs  
3. **Delta refinement** — group/elevate atomic changes into meaningful complex ones

This three-phase framing is useful. Phase 3 (delta refinement) is exactly what our fuzzy sentence-pairing pass does.

## Output format: Extended Unified Patch (EUP)

Extends the standard unified diff format to describe changes at multiple abstraction levels and include model-specific operations (MOVE, SPLIT, WRAP, etc.). Not directly relevant to our HTML rendering, but the idea of named operations beyond insert/delete is useful.

## What's NOT relevant

- The tool is a research prototype focused on format interoperability (ODT vs HTML, etc.) — not a problem we have.
- The implementation uses XSLT transformations and XML-centric infrastructure throughout.
- The cross-format comparison capability is irrelevant — we're always comparing wikitext to wikitext.

## Relevance to WikiWriter diff work

**The three-phase model is a clean mental framework** for what we're building:
- Phase 1 (alignment): our spaCy sentence splitter + Heckel/SequenceMatcher
- Phase 2 (change detection): word-level SequenceMatcher within matched pairs
- Phase 3 (refinement): fuzzy pairing of orphaned deletes/inserts into REWRITE operations

**The paragraph-as-abstraction-level idea** supports our current architecture: treat paragraphs as rendering containers, sentences as the alignment unit, words as the diff unit. Each is a different abstraction level. `diffi` would say we're comparing at the "sentence sequence" level and refining down to the word level.

**Named operations matter:** The paper argues that labelling a change as MOVE or REWRITE (rather than just delete+insert) is what makes a delta useful to human reviewers. This is the theoretical justification for our "↕ moved" and word-level-diff-within-replace rendering.

## Relationship to 2016 paper

This is the implementation companion to the 2016 metrics paper — same author, same UniDM foundation. Where the 2016 paper asks "how do we measure diff quality?", this paper asks "how do we build a diff tool that scores well on those metrics?". Together they form a consistent framework.

## Bottom line

More implementation-oriented than the 2016 paper but still XML/format-agnostic research infrastructure. The three-phase model (align → detect → refine) is the most directly applicable idea. Confirms we're on the right track architecturally.
