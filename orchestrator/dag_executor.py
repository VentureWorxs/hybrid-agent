"""
Simple DAG executor for parallel subtask execution.
Tasks with no unmet dependencies run concurrently via asyncio.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

log = logging.getLogger(__name__)


@dataclass
class SubTask:
    task_id: str
    action: str
    fn: Callable[..., Coroutine]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


async def execute_dag(subtasks: list[SubTask]) -> dict[str, Any]:
    """
    Execute subtasks respecting dependency order.
    Independent subtasks run concurrently.
    Returns {task_id: result}.
    """
    index = {t.task_id: t for t in subtasks}
    results: dict[str, Any] = {}
    pending = set(t.task_id for t in subtasks)

    while pending:
        runnable = [
            tid for tid in pending
            if all(dep in results for dep in index[tid].depends_on)
        ]
        if not runnable:
            unmet = {tid: index[tid].depends_on for tid in pending}
            raise RuntimeError(f"DAG deadlock — circular dependency or missing tasks: {unmet}")

        batch = [index[tid] for tid in runnable]
        log.debug("Running batch: %s", [t.task_id for t in batch])

        batch_results = await asyncio.gather(
            *(t.fn(*t.args, **t.kwargs) for t in batch),
            return_exceptions=True,
        )

        for task, result in zip(batch, batch_results):
            results[task.task_id] = result
            pending.discard(task.task_id)

    return results
