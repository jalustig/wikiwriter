# ABOUTME: Pure data helpers for computing chart inputs from source/section data.
# ABOUTME: Separated from app.py so tests can import without Streamlit side effects.


def source_chart_data(audit: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    """Return (status_counts, type_counts) from a list of source evaluation dicts."""
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for s in audit:
        status = s.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
        dtype = s.get("domain_type", "unknown")
        type_counts[dtype] = type_counts.get(dtype, 0) + 1
    return status_counts, type_counts


def section_score_data(
    section_grades: dict[str, float],
    section_order: list[str] | None = None,
) -> tuple[list[str], list[float]]:
    """Return (sections, scores) in article order (falling back to score-ascending)."""
    if section_order:
        ordered = [(s, section_grades[s]) for s in section_order if s in section_grades]
        remainder = [(s, v) for s, v in section_grades.items() if s not in set(section_order)]
        pairs = ordered + sorted(remainder, key=lambda x: x[1])
    else:
        pairs = sorted(section_grades.items(), key=lambda x: x[1])
    return [p[0] for p in pairs], [p[1] for p in pairs]
