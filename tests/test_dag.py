# ABOUTME: Tests for the DAG executor — pure asyncio logic, no LLM calls.
# ABOUTME: Verifies task ordering, parallel execution, failure propagation.

import asyncio
import pytest

from dag import DAGExecutor, build_dag
from models import TaskNode


def _node(id, type="noop", deps=None, params=None):
    return TaskNode(id=id, type=type, params=params or {}, deps=deps or [])


# --- build_dag ---

def test_build_dag_empty():
    nodes = build_dag([])
    assert nodes == {}


def test_build_dag_creates_index():
    raw = [{"id": "t1", "type": "research_section", "params": {"section": "Lead"}, "deps": []}]
    nodes = build_dag(raw)
    assert "t1" in nodes
    assert nodes["t1"].type == "research_section"
    assert nodes["t1"].params == {"section": "Lead"}


def test_build_dag_preserves_deps():
    raw = [
        {"id": "t1", "type": "research_section", "params": {}, "deps": []},
        {"id": "t2", "type": "draft_section", "params": {}, "deps": ["t1"]},
    ]
    nodes = build_dag(raw)
    assert nodes["t2"].deps == ["t1"]


# --- DAGExecutor ---

@pytest.mark.asyncio
async def test_single_node_executes():
    called = []

    async def noop_handler(params, dep_results, ctx):
        called.append(params)
        return "result"

    node = _node("t1")
    executor = DAGExecutor({"noop": noop_handler})
    events = []
    async for event in executor.run({"t1": node}, ctx={}):
        events.append(event)

    assert called == [{}]
    assert any(e.status == "done" and "t1" in e.message for e in events)


@pytest.mark.asyncio
async def test_dependency_respected():
    order = []

    async def slow_handler(params, dep_results, ctx):
        order.append("slow")
        return "slow_result"

    async def fast_handler(params, dep_results, ctx):
        order.append("fast")
        assert dep_results.get("t1") == "slow_result"
        return "fast_result"

    nodes = {
        "t1": _node("t1", type="slow"),
        "t2": _node("t2", type="fast", deps=["t1"]),
    }
    executor = DAGExecutor({"slow": slow_handler, "fast": fast_handler})
    async for _ in executor.run(nodes, ctx={}):
        pass

    assert order == ["slow", "fast"]


@pytest.mark.asyncio
async def test_independent_nodes_run_concurrently():
    started = []
    barrier = asyncio.Event()

    async def barrier_handler(params, dep_results, ctx):
        started.append(params["id"])
        await barrier.wait()
        return "done"

    nodes = {
        "t1": _node("t1", type="barrier", params={"id": "t1"}),
        "t2": _node("t2", type="barrier", params={"id": "t2"}),
    }
    executor = DAGExecutor({"barrier": barrier_handler})

    run_task = asyncio.create_task(_collect(executor.run(nodes, ctx={})))
    # Give the coroutines a moment to start
    await asyncio.sleep(0.01)
    assert len(started) == 2  # both started before barrier released
    barrier.set()
    await run_task


async def _collect(agen):
    async for _ in agen:
        pass


@pytest.mark.asyncio
async def test_failed_node_marks_dependents_failed():
    async def fail_handler(params, dep_results, ctx):
        raise ValueError("intentional failure")

    async def downstream_handler(params, dep_results, ctx):
        return "should not run"

    nodes = {
        "t1": _node("t1", type="fail"),
        "t2": _node("t2", type="downstream", deps=["t1"]),
    }
    executor = DAGExecutor({"fail": fail_handler, "downstream": downstream_handler})
    events = []
    async for e in executor.run(nodes, ctx={}):
        events.append(e)

    error_events = [e for e in events if e.status == "error"]
    assert len(error_events) >= 1

    # t2 should be failed, never ran
    assert nodes["t2"].status == "failed"


@pytest.mark.asyncio
async def test_dep_results_passed_correctly():
    async def producer(params, dep_results, ctx):
        return {"value": 42}

    async def consumer(params, dep_results, ctx):
        assert dep_results["producer"]["value"] == 42
        return "consumed"

    nodes = {
        "producer": _node("producer", type="producer"),
        "consumer": _node("consumer", type="consumer", deps=["producer"]),
    }
    executor = DAGExecutor({"producer": producer, "consumer": consumer})
    async for _ in executor.run(nodes, ctx={}):
        pass

    assert nodes["consumer"].status == "done"
    assert nodes["consumer"].result == "consumed"
