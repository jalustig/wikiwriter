# ABOUTME: Tests for PIL-based agent loop and task DAG image renderers.
# ABOUTME: Checks output is valid PNG bytes and responds to state changes.

import io

from PIL import Image

from dag_image import render_agent_loop, render_task_dag

PNG_MAGIC = b"\x89PNG"


def _png_height(data: bytes) -> int:
    return Image.open(io.BytesIO(data)).size[1]


def test_agent_loop_returns_png():
    png = render_agent_loop([], None, set(), 0)
    assert png[:4] == PNG_MAGIC


def test_agent_loop_with_active_stage():
    png = render_agent_loop(["FETCH"], "FETCH", set(), 0)
    assert png[:4] == PNG_MAGIC
    assert len(png) > 1000


def test_agent_loop_with_done_stages():
    png = render_agent_loop(["FETCH", "GATHER"], "GATHER", {"FETCH"}, 0)
    assert png[:4] == PNG_MAGIC


def test_agent_loop_with_back_edge():
    png_no_loop = render_agent_loop(["FETCH"], "PLAN", {"FETCH", "GATHER", "ASSESS"}, 0)
    png_loop = render_agent_loop(
        ["FETCH", "GATHER", "ASSESS", "PLAN", "EXEC", "CRITIQUE", "PLAN"],
        "PLAN",
        {"FETCH", "GATHER", "ASSESS", "EXEC", "CRITIQUE"},
        1,
    )
    assert png_loop[:4] == PNG_MAGIC
    assert png_loop != png_no_loop


def test_task_dag_returns_png():
    dag = {
        "t1": {"type": "research_section", "params": {"section": "History"}, "deps": []},
        "t2": {"type": "draft_section", "params": {"section": "History"}, "deps": ["t1"]},
    }
    png = render_task_dag(dag, set(), set())
    assert png[:4] == PNG_MAGIC


def test_task_dag_done_nodes():
    dag = {
        "t1": {"type": "research_section", "params": {}, "deps": []},
        "t2": {"type": "draft_section", "params": {}, "deps": ["t1"]},
    }
    png_none_done = render_task_dag(dag, set(), set())
    png_t1_done = render_task_dag(dag, {"t1"}, set())
    assert png_none_done != png_t1_done


def test_task_dag_current_nodes():
    dag = {"t1": {"type": "research_section", "params": {}, "deps": []}}
    png_idle = render_task_dag(dag, set(), set())
    png_active = render_task_dag(dag, set(), {"t1"})
    assert png_idle != png_active


def test_agent_loop_pre_assess_shorter_than_post():
    """Before ASSESS completes, only the initial pipeline is shown (fewer nodes)."""
    png_pre = render_agent_loop(["FETCH"], "FETCH", set(), 0)
    png_post = render_agent_loop(["FETCH", "GATHER", "ASSESS"], "PLAN", {"FETCH", "GATHER", "ASSESS"}, 0)
    assert _png_height(png_pre) < _png_height(png_post)


def test_agent_loop_pre_assess_differs_from_post():
    """After ASSESS the full pipeline appears, making a visually different image."""
    png_pre = render_agent_loop([], None, set(), 0)
    png_post = render_agent_loop([], None, {"FETCH", "GATHER", "ASSESS"}, 0)
    assert png_pre != png_post


def test_task_dag_empty():
    png = render_task_dag({}, set(), set())
    assert isinstance(png, bytes)
    assert len(png) > 0
