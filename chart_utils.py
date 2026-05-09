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


def section_score_data(section_grades: dict[str, float]) -> tuple[list[str], list[float]]:
    """Return (sections, scores) sorted by score ascending for a horizontal bar chart."""
    pairs = sorted(section_grades.items(), key=lambda x: x[1])
    return [p[0] for p in pairs], [p[1] for p in pairs]
