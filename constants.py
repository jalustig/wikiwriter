# ABOUTME: Shared stage metadata used by both the Streamlit and terminal interfaces.
# ABOUTME: STAGE_META maps stage name → (icon, running_label, done_label).

STAGE_META = {
    "FETCH":     ("🌐", "Reading article…",           "Read article"),
    "GATHER":    ("📊", "Gathering evidence…",         "Evidence gathered"),
    "ASSESS":    ("🧠", "Assessing what's needed…",    "Assessment complete"),
    "PLAN":      ("🗺️",  "Planning tasks…",             "Task plan ready"),
    "EXEC":      ("✏️",  "Executing task DAG…",         "Tasks complete"),
    "CRITIQUE":  ("🔬", "Critiquing sections…",        "Critique done"),
    "GRADE":     ("📈", "Scoring output…",             "Output scored"),
    "SUMMARIZE": ("📝", "Writing editorial summary…",  "Summary written"),
    "DAG":       ("⚙️",  "Running…",                   "Done"),
}
