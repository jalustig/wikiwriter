# ABOUTME: PIL-based image renderers for the agent loop diagram and task DAG.
# ABOUTME: Used by the Streamlit sidebar to visualise agent state in real time.

import io

from PIL import Image, ImageDraw, ImageFont

from dag import dag_layers

STAGES = ["FETCH", "GATHER", "ASSESS", "PLAN", "EXEC", "CRITIQUE", "GRADE"]
_STAGE_LABELS = {
    "FETCH":    "Fetch",
    "GATHER":   "Gather",
    "ASSESS":   "Assess",
    "PLAN":     "Plan",
    "EXEC":     "Execute",
    "CRITIQUE": "Critique",
    "GRADE":    "Grade",
}

_NODE_COLORS = {
    "done":    ("#DCFCE7", "#16A34A", 2),
    "active":  ("#DBEAFE", "#3B82F6", 3),
    "error":   ("#FEE2E2", "#DC2626", 2),
    "pending": ("#F1F5F9", "#CBD5E1", 1),
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


def render_agent_loop(
    stage_history: list,
    current_stage,
    done_stages: set,
    loop_count: int,
    width: int = 210,
) -> bytes:
    """Render the agent loop diagram as PNG bytes for st.image()."""
    NW = width - 20
    NH = 34
    PAD = 10
    VG = 14
    n = len(STAGES)
    back_edge_extra = 40 if loop_count > 0 else 0
    H = PAD + n * NH + (n - 1) * VG + PAD + back_edge_extra

    img = Image.new("RGB", (width, H), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    f_label, _, f_small = _fonts()

    cx = PAD + NW // 2
    positions = {}
    for i, stage in enumerate(STAGES):
        cy = PAD + i * (NH + VG) + NH // 2
        positions[stage] = (cx, cy)

    # Draw forward edges
    for i in range(len(STAGES) - 1):
        s1, s2 = STAGES[i], STAGES[i + 1]
        _, y1 = positions[s1]
        _, y2 = positions[s2]
        mid_y1 = y1 + NH // 2
        mid_y2 = y2 - NH // 2
        draw.line([(cx, mid_y1), (cx, mid_y2 - 4)], fill="#94A3B8", width=1)
        draw.polygon(
            [(cx - 4, mid_y2 - 7), (cx + 4, mid_y2 - 7), (cx, mid_y2)],
            fill="#94A3B8",
        )

    # Draw back-edge if loop occurred (CRITIQUE → PLAN)
    if loop_count > 0:
        _, plan_cy = positions["PLAN"]
        _, crit_cy = positions["CRITIQUE"]
        right_x = PAD + NW + 4
        pts = [
            (PAD + NW, crit_cy),
            (right_x + 2, crit_cy),
            (right_x + 2, plan_cy),
            (PAD + NW, plan_cy),
        ]
        draw.line(pts, fill="#DC2626", width=2)
        ax = PAD + NW
        draw.polygon(
            [(ax + 7, plan_cy - 4), (ax + 7, plan_cy + 4), (ax, plan_cy)],
            fill="#DC2626",
        )
        label = f"loop {loop_count}"
        draw.text(
            (right_x + 4, (plan_cy + crit_cy) // 2 - 5),
            label, fill="#DC2626", font=f_small,
        )

    # Draw nodes
    for stage in STAGES:
        cx_node, cy_node = positions[stage]
        x0 = PAD
        y0 = cy_node - NH // 2
        x1 = PAD + NW
        y1 = cy_node + NH // 2

        if stage == current_stage:
            state = "active"
        elif stage in done_stages:
            state = "done"
        else:
            state = "pending"

        fill, border, bw = _NODE_COLORS[state]
        draw.rounded_rectangle([x0, y0, x1, y1], radius=6, fill=fill, outline=border, width=bw)

        label = _STAGE_LABELS.get(stage, stage)
        draw.text((cx_node, cy_node), label, fill="#1E293B", anchor="mm", font=f_label)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
