# ABOUTME: Lightweight asyncio DAG executor for the v2 agent architecture.
# ABOUTME: Runs task nodes in dependency order, yielding ProgressEvents as each completes.

import asyncio
from typing import Any, AsyncGenerator, Callable

from models import ProgressEvent, TaskNode


def build_dag(raw_tasks: list[dict]) -> dict[str, TaskNode]:
    """Convert edit_planner JSON output into a dict of TaskNode objects."""
    return {
        t["id"]: TaskNode(
            id=t["id"],
            type=t["type"],
            params=t.get("params", {}),
            deps=t.get("deps", []),
        )
        for t in raw_tasks
    }


class DAGExecutor:
    """
    Executes a set of TaskNodes respecting dependency order.

    Handlers are async callables: async def handler(params, dep_results, ctx) -> result
    dep_results is a dict of {dep_id: result} for this node's direct dependencies.
    ctx is passed through unchanged to every handler.
    """

    def __init__(self, handlers: dict[str, Callable]):
        self.handlers = handlers

    async def run(
        self,
        nodes: dict[str, TaskNode],
        ctx: Any,
    ) -> AsyncGenerator[ProgressEvent, None]:
        running: dict[str, asyncio.Task] = {}

        def _ready() -> list[str]:
            return [
                nid for nid, node in nodes.items()
                if node.status == "pending"
                and all(nodes[d].status == "done" for d in node.deps)
                and not any(nodes[d].status == "failed" for d in node.deps)
            ]

        def _has_failed_dep(node: TaskNode) -> bool:
            return any(nodes[d].status == "failed" for d in node.deps)

        async def _run_node(node_id: str) -> tuple[str, Any, Exception | None]:
            node = nodes[node_id]
            node.status = "running"
            dep_results = {d: nodes[d].result for d in node.deps}
            handler = self.handlers.get(node.type)
            if handler is None:
                return node_id, None, ValueError(f"No handler for task type '{node.type}'")
            try:
                result = await handler(node.params, dep_results, ctx)
                return node_id, result, None
            except Exception as exc:
                return node_id, None, exc

        # Use an event to signal when any task finishes
        done_event = asyncio.Event()
        finished: list[tuple[str, Any, Exception | None]] = []

        async def _wrap(node_id: str):
            result = await _run_node(node_id)
            finished.append(result)
            done_event.set()

        while True:
            # Mark nodes with failed deps as failed
            for nid, node in nodes.items():
                if node.status == "pending" and _has_failed_dep(node):
                    node.status = "failed"
                    yield ProgressEvent(
                        stage="DAG",
                        status="error",
                        message=f"{nid}: skipped (dependency failed)",
                    )

            # Launch all ready nodes
            for nid in _ready():
                nodes[nid].status = "running"
                task = asyncio.create_task(_wrap(nid))
                running[nid] = task
                yield ProgressEvent(
                    stage="DAG",
                    status="running",
                    message=f"{nid}: starting",
                )

            # Check if we're done
            all_terminal = all(n.status in ("done", "failed") for n in nodes.values())
            if all_terminal and not running:
                break

            # Wait for at least one task to finish
            if running:
                done_event.clear()
                await done_event.wait()

            # Process finished tasks
            while finished:
                nid, result, exc = finished.pop(0)
                running.pop(nid, None)
                node = nodes[nid]
                if exc is not None:
                    node.status = "failed"
                    node.result = None
                    yield ProgressEvent(
                        stage="DAG",
                        status="error",
                        message=f"{nid}: failed — {exc}",
                    )
                else:
                    node.status = "done"
                    node.result = result
                    yield ProgressEvent(
                        stage="DAG",
                        status="done",
                        message=f"{nid}: done",
                    )
