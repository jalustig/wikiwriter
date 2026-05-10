# Notes: "Measuring the quality of diff algorithms: a formalization" (Barabucci et al., 2016)

**Citation:** Barabucci, G., Ciancarini, P., Di Iorio, A., Vitali, F. Computer Standards & Interfaces 46 (2016) 52–65.

## What it is

A formal framework for evaluating diff algorithms using objective metrics, built on top of the Universal Delta Model (UniDM). Applied experimentally to three XML diff tools: JNDiff, XyDiff, and Faxma.

## Core idea

There is no single best diff algorithm. Quality depends on who reads the diff and why. The paper proposes five metrics to characterise a delta:

- **Length** — number of top-level changes (fewer = more concise)
- **Terseness** — ratio of modified elements to touched elements (higher = less redundant context)
- **Conciseness** — ratio of complex changes to all changes (higher = more grouped/meaningful)
- **Compositeness** — how much of the delta's length is due to complex changes
- **Deep compositeness** — how deeply changes are nested inside other changes

## The scenario taxonomy (most useful part)

They define 8 scenarios (S1–S8). The one directly relevant to WikiWriter:

**S5 — Author revising literary documents:** high conciseness and high (deep) compositeness desired. The reviewer wants high-level changes ("this sentence was rewritten"), not atomic operations ("this word was deleted, this word was inserted"). Verbose low-level deltas are explicitly called out as harmful here.

This is exactly our use case.

## Key insight: atomic vs complex changes

A delta contains *atomic* changes (irreducible) and *complex* changes (aggregations of atomics into meaningful operations like MOVE, WRAP, REWRITE). The quality of a diff for human readers is largely determined by how well it groups atomic changes into complex ones — i.e., conciseness and compositeness.

This is the theoretical grounding for what we're building: our fuzzy sentence-pairing pass is manually implementing complex change detection, recognising that DEL(sentence A) + INS(sentence B) is actually one complex REWRITE operation.

## What's NOT relevant

- The paper works entirely on XML tree structures. The algorithms and metrics don't translate directly to plain prose.
- The experimental results (JNDiff vs XyDiff vs Faxma) are specific to XML and not applicable to wikitext.
- The UniDM formalism is heavyweight — useful as a mental model, not as implementation guidance.

## Relevance to WikiWriter diff work

**Validates the approach:** High compositeness/conciseness is the right target for our use case. Showing a word-level diff inside a matched sentence pair is a complex change; showing raw delete+insert for unrelated sentences is atomic noise.

**The fuzzy pairing pass** we implemented is essentially a heuristic complex change detector — recognising that two atomic ops belong together as a single rewrite. The paper would call this good: we're increasing compositeness.

**Threshold tuning:** Their metrics could theoretically be used to evaluate our `_MIN_SIMILARITY` threshold — lower threshold = more pairs treated as rewrites = higher compositeness, but potentially false groupings. We're currently at 0.25, which seems reasonable but is not formally grounded.

## Bottom line

Useful as conceptual validation and vocabulary. The scenario taxonomy (especially S5) is a good reference when making design decisions. Not a source of algorithms or implementation patterns.
