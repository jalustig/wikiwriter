# ABOUTME: Shared stage metadata used by both the Streamlit and terminal interfaces.
# ABOUTME: STAGE_META maps stage name → (icon, running_label, done_label).

STAGE_META = {
    "FETCH":    ("🌐", "Reading article…",        "Read article"),
    "INTAKE":   ("📊", "Assessing quality…",       "Quality assessed"),
    "PLAN":     ("🗺️",  "Planning edits…",          "Edit plan ready"),
    "CLAIMS":   ("🔎", "Tagging claims…",          "Claims tagged"),
    "SOURCES":  ("🔍", "Evaluating sources…",      "Sources evaluated"),
    "DRAFT":    ("✏️",  "Writing drafts…",          "Drafts written"),
    "CRITIQUE": ("🔬", "Reviewing draft…",         "Draft reviewed"),
    "GRADE":    ("📈", "Scoring output…",          "Output scored"),
}
