from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from calcchain_backend.schemas.common import now_utc
from calcchain_backend.schemas.run import LogItem, RunDetails, RunEvent, RunStatus, RunSummary
from calcchain_backend.services.artifact_service import ArtifactService


@dataclass
class _RunState:
    id: str
    name: str | None
    build_config: dict[str, Any]
    status: RunStatus = "queued"
    created_at: datetime = field(default_factory=now_utc)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    logs: list[LogItem] = field(default_factory=list)
    events: list[RunEvent] = field(default_factory=list)
    cancel_requested: bool = False


class RunService:
    """In-memory run manager.

    The current implementation is intentionally a safe backend scaffold. It keeps
    API contracts stable and can later replace `_execute_run` with real calls to
    CalculationCore/build/run without changing routes or frontend contracts.
    """

    def __init__(self, artifact_service: ArtifactService) -> None:
        self._artifact_service = artifact_service
        self._runs: dict[str, _RunState] = {}
        self._condition = asyncio.Condition()

    async def create_run(self, build_config: dict[str, Any], run_options: dict[str, Any]) -> RunDetails:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        run = _RunState(
            id=run_id,
            name=run_options.get("name") if isinstance(run_options.get("name"), str) else build_config.get("name"),
            build_config=build_config,
        )
        self._runs[run_id] = run
        await self._append_event(run, "run_queued", {"run_id": run_id})
        asyncio.create_task(self._execute_run(run_id))
        return self.get_run(run_id)  # type: ignore[return-value]

    def list_runs(self) -> list[RunSummary]:
        return [self._summary(run) for run in sorted(self._runs.values(), key=lambda item: item.created_at, reverse=True)]

    def get_run(self, run_id: str) -> RunDetails | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        return RunDetails(
            id=run.id,
            name=run.name,
            status=run.status,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            progress=run.progress,
            build_config=run.build_config,
            error=run.error,
        )

    async def cancel_run(self, run_id: str) -> RunDetails | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        if run.status in {"success", "failed", "cancelled"}:
            return self.get_run(run_id)
        run.cancel_requested = True
        run.status = "cancelling"
        await self._append_log(run, "warning", "Cancellation requested")
        await self._append_event(run, "run_cancelling", {"run_id": run_id})
        return self.get_run(run_id)

    def get_logs(self, run_id: str) -> list[LogItem] | None:
        run = self._runs.get(run_id)
        return None if run is None else list(run.logs)

    async def iter_events(self, run_id: str):
        run = self._runs.get(run_id)
        if run is None:
            return
        sent = 0
        while True:
            while sent < len(run.events):
                event = run.events[sent]
                sent += 1
                yield self._format_sse(event)
            if run.status in {"success", "failed", "cancelled"}:
                break
            async with self._condition:
                await self._condition.wait()

    async def _execute_run(self, run_id: str) -> None:
        run = self._runs[run_id]
        try:
            run.status = "running"
            run.started_at = now_utc()
            await self._append_log(run, "info", "Run started")
            await self._append_event(run, "run_started", {"run_id": run_id})

            steps = run.build_config.get("execution_plan")
            if not isinstance(steps, list) or not steps:
                steps = ["prepare", "execute", "collect_artifacts"]

            total = len(steps)
            for index, step in enumerate(steps, start=1):
                if run.cancel_requested:
                    run.status = "cancelled"
                    run.finished_at = now_utc()
                    await self._append_log(run, "warning", "Run cancelled")
                    await self._append_event(run, "run_cancelled", {"run_id": run_id})
                    return
                run.progress = {"current_step": str(step), "completed_steps": index - 1, "total_steps": total, "percent": int(((index - 1) / total) * 100)}
                await self._append_event(run, "step_started", {"run_id": run_id, "step": str(step), "index": index, "total": total})
                await self._append_log(run, "info", f"Processing step: {step}")
                await asyncio.sleep(0.1)
                run.progress = {"current_step": str(step), "completed_steps": index, "total_steps": total, "percent": int((index / total) * 100)}
                await self._append_event(run, "progress", run.progress)

            run.status = "success"
            run.finished_at = now_utc()
            await self._append_log(run, "info", "Run finished successfully")
            manifest = {
                "run_id": run.id,
                "status": run.status,
                "name": run.name,
                "created_at": run.created_at.isoformat(),
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "build_config": run.build_config,
                "logs": [item.model_dump(mode="json") for item in run.logs],
            }
            self._artifact_service.create_run_artifacts(run.id, manifest)
            await self._append_event(run, "run_finished", {"run_id": run_id, "status": "success"})
        except Exception as exc:  # pragma: no cover - defensive fallback for API stability
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = now_utc()
            await self._append_log(run, "error", str(exc))
            await self._append_event(run, "run_failed", {"run_id": run_id, "error": str(exc)})

    async def _append_log(self, run: _RunState, level: str, message: str) -> None:
        run.logs.append(LogItem(timestamp=now_utc(), level=level, message=message))  # type: ignore[arg-type]

    async def _append_event(self, run: _RunState, event_type: str, data: dict[str, Any]) -> None:
        event = RunEvent(id=len(run.events) + 1, type=event_type, timestamp=now_utc(), data=data)
        run.events.append(event)
        async with self._condition:
            self._condition.notify_all()

    @staticmethod
    def _summary(run: _RunState) -> RunSummary:
        return RunSummary(id=run.id, name=run.name, status=run.status, created_at=run.created_at, started_at=run.started_at, finished_at=run.finished_at)

    @staticmethod
    def _format_sse(event: RunEvent) -> str:
        payload = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
        return f"id: {event.id}\nevent: {event.type}\ndata: {payload}\n\n"
