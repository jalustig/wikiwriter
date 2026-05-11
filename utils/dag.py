# ABOUTME: PIL-based image renderers for the agent loop diagram and task DAG.
# ABOUTME: Used by the Streamlit sidebar to visualise agent state in real time.

import io

from PIL import Image, ImageDraw, ImageFont

from dag import dag_layers

# Pipeline layout: each entry is either a single stage name or a list of parallel stages.
# The GATHER fan-out is represented as ["CHECK_SOURCES", "GRADE_CONTENT", "REVIEW_CONTEXT"].
_PIPELINE_ROWS = [
    "FETCH",
    ["CHECK_SOURCES", "GRADE_CONTENT", "REVIEW_CONTEXT"],
    "ASSESS",
    "PLAN",
    "EXEC",
    "CRITIQUE",
    "GRADE",
    "SUMMARIZE",
    "OUTPUT",
]

# Canonical stage names used for status tracking (map parallel sub-stages to GATHER)
_GATHER_SUBSTAGES = {"CHECK_SOURCES", "GRADE_CONTENT", "REVIEW_CONTEXT"}

_STAGE_LABELS = {
    "FETCH":          "Read Article",
    "CHECK_SOURCES":  "Check Sources",
    "GRADE_CONTENT":  "Grade Content",
    "REVIEW_CONTEXT": "Review Context",
    "ASSESS":         "Assess",
    "PLAN":           "Plan",
    "EXEC":           "Execute",
    "CRITIQUE":       "Critique",
    "GRADE":          "Grade",
    "SUMMARIZE":      "Summarize",
    "OUTPUT":         "Output",
    "???":            "???",
}

# Initial rows shown before ASSESS completes (progressive reveal)
_INITIAL_ROWS = [
    "FETCH",
    ["CHECK_SOURCES", "GRADE_CONTENT", "REVIEW_CONTEXT"],
    "???",
]

_NODE_COLORS = {
    "done":    ("#DCFCE7", "#16A34A", 2),
    "active":  ("#DBEAFE", "#3B82F6", 3),
    "error":   ("#FEE2E2", "#DC2626", 2),
    "pending": ("#F1F5F9", "#CBD5E1", 1),
    "decision": ("#FEF9C3", "#CA8A04", 1),
}

_TYPE_COLORS = {
    "research_section":   ("#DBEAFE", "#3B82F6"),
    "draft_section":      ("#DCFCE7", "#16A34A"),
    "synthesize":         ("#F3E8FF", "#9333EA"),
    "draft_full_article": ("#FEF9C3", "#CA8A04"),
}
_DEFAULT_NODE_COLOR = ("#F1F5F9", "#64748B")


def _fonts():
    try:
        return (
            ImageFont.load_default(size=12),
            ImageFont.load_default(size=10),
            ImageFont.load_default(size=9),
        )
    except TypeError:
        f = ImageFont.load_default()
        return f, f, f


def _node_color(stage: str, current_stage: str | None, done_stages: set) -> tuple:
    if stage == "???":
        return _NODE_COLORS["decision"]
    # Sub-stages of GATHER inherit GATHER's status
    effective = "GATHER" if stage in _GATHER_SUBSTAGES else stage
    if effective == current_stage or stage == current_stage:
        return _NODE_COLORS["active"]
    if effective in done_stages or stage in done_stages:
        return _NODE_COLORS["done"]
    return _NODE_COLORS["pending"]


def render_agent_loop(
    stage_history: list,
    current_stage,
    done_stages: set,
    loop_count: int,
    width: int = 210,
) -> bytes:
    """Render the agent loop diagram as PNG bytes for st.image()."""
    rows = _PIPELINE_ROWS if "ASSESS" in done_stages else _INITIAL_ROWS

    NW = width - 20   # node width
    NH = 32           # node height
    PAD = 10
    VG = 12           # vertical gap between rows
    HG = 6            # horizontal gap between parallel nodes

    f_label, _, f_small = _fonts()

    # Compute row heights and total height
    n_rows = len(rows)
    back_edge_extra = 40 if "ASSESS" in done_stages else 0
    H = PAD + n_rows * NH + (n_rows - 1) * VG + PAD + back_edge_extra

    img = Image.new("RGB", (width, H), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    cx_center = PAD + NW // 2

    # Compute center positions for each node in each row
    # pos maps stage_name -> (cx, cy)
    pos: dict[str, tuple[int, int]] = {}
    row_cy: list[int] = []

    for ri, row in enumerate(rows):
        cy = PAD + ri * (NH + VG) + NH // 2
        row_cy.append(cy)
        if isinstance(row, str):
            pos[row] = (cx_center, cy)
        else:
            # Parallel nodes: divide available width evenly
            n = len(row)
            sub_w = (NW - (n - 1) * HG) // n
            for i, stage in enumerate(row):
                node_cx = PAD + i * (sub_w + HG) + sub_w // 2
                pos[stage] = (node_cx, cy)

    # ── Draw edges ────────────────────────────────────────────────────────────
    for ri in range(len(rows) - 1):
        top_row = rows[ri]
        bot_row = rows[ri + 1]

        top_stages = [top_row] if isinstance(top_row, str) else top_row
        bot_stages = [bot_row] if isinstance(bot_row, str) else bot_row

        top_cxs = [pos[s][0] for s in top_stages]
        bot_cxs = [pos[s][0] for s in bot_stages]

        top_cy = row_cy[ri] + NH // 2
        bot_cy = row_cy[ri + 1] - NH // 2

        if len(top_stages) == 1 and len(bot_stages) == 1:
            # Simple vertical connector
            _draw_arrow(draw, top_cxs[0], top_cy, bot_cxs[0], bot_cy)
        elif len(top_stages) == 1:
            # Fan-out: one top node to many bottom nodes
            mid_y = (top_cy + bot_cy) // 2
            draw.line([(top_cxs[0], top_cy), (top_cxs[0], mid_y)], fill="#94A3B8", width=1)
            for bcx in bot_cxs:
                draw.line([(top_cxs[0], mid_y), (bcx, mid_y)], fill="#94A3B8", width=1)
                _draw_arrow(draw, bcx, mid_y, bcx, bot_cy)
        else:
            # Fan-in: many top nodes to one bottom node
            mid_y = (top_cy + bot_cy) // 2
            for tcx in top_cxs:
                draw.line([(tcx, top_cy), (tcx, mid_y)], fill="#94A3B8", width=1)
            draw.line([(top_cxs[0], mid_y), (top_cxs[-1], mid_y)], fill="#94A3B8", width=1)
            _draw_arrow(draw, bot_cxs[0], mid_y, bot_cxs[0], bot_cy)

    # ── Back-edge CRITIQUE → PLAN (always visible; red + count when loop has fired) ──
    if "PLAN" in pos and "CRITIQUE" in pos:
        _, plan_cy = pos["PLAN"]
        _, crit_cy = pos["CRITIQUE"]
        right_x = PAD + NW + 4
        edge_color = "#DC2626" if loop_count > 0 else "#94A3B8"
        pts = [
            (PAD + NW, crit_cy),
            (right_x + 2, crit_cy),
            (right_x + 2, plan_cy),
            (PAD + NW, plan_cy),
        ]
        draw.line(pts, fill=edge_color, width=2)
        ax = PAD + NW
        draw.polygon(
            [(ax + 7, plan_cy - 4), (ax + 7, plan_cy + 4), (ax, plan_cy)],
            fill=edge_color,
        )
        if loop_count > 0:
            draw.text(
                (right_x + 4, (plan_cy + crit_cy) // 2 - 5),
                f"loop {loop_count}", fill=edge_color, font=f_small,
            )

    # ── Draw nodes ────────────────────────────────────────────────────────────
    for ri, row in enumerate(rows):
        stages = [row] if isinstance(row, str) else row
        n = len(stages)
        sub_w = (NW - (n - 1) * HG) // n if n > 1 else NW

        for i, stage in enumerate(stages):
            node_cx, node_cy = pos[stage]
            x0 = node_cx - sub_w // 2
            y0 = node_cy - NH // 2
            x1 = node_cx + sub_w // 2
            y1 = node_cy + NH // 2

            fill, border, bw = _node_color(stage, current_stage, done_stages)
            draw.rounded_rectangle([x0, y0, x1, y1], radius=6, fill=fill, outline=border, width=bw)

            label = _STAGE_LABELS.get(stage, stage)
            text_color = "#CA8A04" if stage == "???" else "#1E293B"
            _draw_label(draw, node_cx, node_cy, label, text_color, f_label)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _draw_label(draw, cx: int, cy: int, label: str, color: str, font) -> None:
    """Draw a label centred at (cx, cy), splitting on the first space for two-line nodes."""
    if " " in label:
        words = label.split(" ", 1)
        draw.text((cx, cy - 7), words[0], fill=color, anchor="mm", font=font)
        draw.text((cx, cy + 7), words[1], fill=color, anchor="mm", font=font)
    else:
        draw.text((cx, cy), label, fill=color, anchor="mm", font=font)


def _draw_arrow(draw, x1: int, y1: int, x2: int, y2: int) -> None:
    """Draw a vertical downward arrow from (x1,y1) to (x2,y2)."""
    draw.line([(x1, y1), (x2, y2 - 4)], fill="#94A3B8", width=1)
    draw.polygon(
        [(x2 - 4, y2 - 7), (x2 + 4, y2 - 7), (x2, y2)],
        fill="#94A3B8",
    )


def render_task_dag(
    dag: dict,
    done_nodes: set,
    current_nodes: set,
    width: int = 210,
) -> bytes:
    """Render the task DAG as PNG bytes. Nodes highlighted by execution state."""
    if not dag:
        img = Image.new("RGB", (width, 60), "#F8FAFC")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    layers = dag_layers(dag)

    NW, NH = 190, 58
    HG, VG = 60, 12
    PAD = 10

    n_layers = len(layers)
    max_per_layer = max(len(layer) for layer in layers)

    W = n_layers * NW + (n_layers - 1) * HG + 2 * PAD
    H = max(120, max_per_layer * NH + (max_per_layer - 1) * VG + 2 * PAD)

    pos = {}
    for li, layer in enumerate(layers):
        n = len(layer)
        col_h = n * NH + (n - 1) * VG
        y0 = (H - col_h) // 2
        for i, nid in enumerate(layer):
            node_cx = PAD + li * (NW + HG) + NW // 2
            node_cy = y0 + i * (NH + VG) + NH // 2
            pos[nid] = (node_cx, node_cy)

    img = Image.new("RGB", (W, H), "#F8FAFC")
    draw = ImageDraw.Draw(img)
    f_label, f_small, f_id = _fonts()

    # Edges
    for nid, node in dag.items():
        cx2, cy2 = pos[nid]
        deps = node.get("deps", []) if isinstance(node, dict) else node.deps
        for dep in deps:
            if dep not in pos:
                continue
            cx1, cy1 = pos[dep]
            x_start = cx1 + NW // 2
            x_end = cx2 - NW // 2 - 1
            draw.line([(x_start, cy1), (x_end - 4, cy2)], fill="#94A3B8", width=2)
            draw.polygon(
                [(x_end - 9, cy2 - 5), (x_end - 9, cy2 + 5), (x_end, cy2)],
                fill="#94A3B8",
            )

    # Nodes
    for nid, node in dag.items():
        node_cx, node_cy = pos[nid]
        x0 = node_cx - NW // 2 + 1
        y0 = node_cy - NH // 2 + 1
        x1 = node_cx + NW // 2 - 1
        y1 = node_cy + NH // 2 - 1

        node_type = node.get("type", "") if isinstance(node, dict) else node.type
        params = node.get("params", {}) if isinstance(node, dict) else node.params

        if nid in done_nodes:
            fill, border, bw = "#DCFCE7", "#16A34A", 2
        elif nid in current_nodes:
            fill, border, bw = "#DBEAFE", "#3B82F6", 3
        else:
            fill, border = _TYPE_COLORS.get(node_type, _DEFAULT_NODE_COLOR)
            bw = 2

        draw.rounded_rectangle([x0, y0, x1, y1], radius=8, fill=fill, outline=border, width=bw)
        draw.text((x0 + 6, y0 + 4), f"[{nid}]", fill=border, font=f_id)

        type_label = node_type.replace("_", " ")
        has_params = bool(params)
        draw.text(
            (node_cx, node_cy - 6 if has_params else node_cy),
            type_label, fill="#1E293B", anchor="mm", font=f_label,
        )
        if has_params:
            pstr = "  ".join(str(v) for v in params.values())
            if len(pstr) > 28:
                pstr = pstr[:26] + "…"
            draw.text((node_cx, node_cy + 8), pstr, fill="#475569", anchor="mm", font=f_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
