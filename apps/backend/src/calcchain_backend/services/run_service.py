from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from calcchain_core import CalculationCore
from calcchain_core.capabilities import RuntimeCapabilities
from calcchain_core.run import CancelToken
from calcchain_core.utils.json import write_json as write_core_json
from calcchain_core.utils.toml import write_toml

from calcchain_backend.schemas.common import now_utc
from calcchain_backend.schemas.run import LogItem, RunDetails, RunEvent, RunStatus, RunSummary
from calcchain_backend.services.artifact_service import ArtifactService
from calcchain_backend.services.plugin_service import PluginService
from calcchain_backend.services.secret_service import SecretService
from calcchain_backend.services.secrets_adapter import runtime_with_backend_secrets


@dataclass
class _RunState:
    id: str
    name: str | None
    build_config: dict[str, Any]
    session_key: str
    run_options: dict[str, Any] = field(default_factory=dict)
    run_config: dict[str, Any] | None = None
    publish_config: dict[str, Any] | None = None
    rules_config: dict[str, Any] | None = None
    graph_config: dict[str, Any] | None = None
    job_dir: Path | None = None
    status: RunStatus = "queued"
    created_at: datetime = field(default_factory=now_utc)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    logs: list[LogItem] = field(default_factory=list)
    events: list[RunEvent] = field(default_factory=list)
    cancel_requested: bool = False


class _BackendCancelToken(CancelToken):
    def __init__(self, run: _RunState) -> None:
        self._run = run

    def is_cancelled(self) -> bool:
        return self._run.cancel_requested


class _RunCancelled(Exception):
    pass


class RunService:
    """In-memory run manager backed by CalculationCore."""

    def __init__(
        self,
        artifact_service: ArtifactService,
        secret_service: SecretService | None = None,
        plugin_service: PluginService | None = None,
    ) -> None:
        self._artifact_service = artifact_service
        self._secret_service = secret_service
        self._plugin_service = plugin_service
        self._runs: dict[str, _RunState] = {}
        self._condition = asyncio.Condition()

    async def create_run(
        self,
        build_config: dict[str, Any],
        run_options: dict[str, Any],
        *,
        run_config: dict[str, Any] | None = None,
        publish_config: dict[str, Any] | None = None,
        rules_config: dict[str, Any] | None = None,
        graph_config: dict[str, Any] | None = None,
        session_key: str = "local-dev-session",
    ) -> RunDetails:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        run = _RunState(
            id=run_id,
            name=run_options.get("name") if isinstance(run_options.get("name"), str) else _build_name(build_config),
            build_config=build_config,
            run_options=dict(run_options),
            run_config=run_config,
            publish_config=publish_config,
            rules_config=rules_config,
            graph_config=graph_config,
            session_key=session_key,
            job_dir=self._artifact_service.job_dir(run_id),
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
            run_config=run.run_config,
            publish_config=run.publish_config,
            rules_config=run.rules_config,
            graph_config=run.graph_config,
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

    def runtime_for_run(self, run_id: str) -> RuntimeCapabilities | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        return self._runtime_for_run(run)

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

            job_dir = _required_job_dir(run)
            core_holder: dict[str, CalculationCore] = {}
            phases: list[tuple[str, Callable[[], object]]] = [
                ("write_configs", lambda: self._write_core_configs(run, job_dir)),
                ("create_build_lock", lambda: self._core(run, core_holder).create_build_lock()),
                ("validate_build", lambda: self._core(run, core_holder).validate_build()),
                ("build", lambda: self._core(run, core_holder).build()),
            ]
            if run.run_config is not None:
                phases.append(("run", lambda: self._core(run, core_holder).run(cancel_token=_BackendCancelToken(run))))
            if run.publish_config is not None:
                phases.append(("publish", lambda: self._core(run, core_holder).publish()))

            total = len(phases) + 1
            for index, (step, action) in enumerate(phases, start=1):
                await self._run_phase(run, step, index, total, action)

            final_status: RunStatus
            if run.status == "cancelling":
                final_status = "cancelled"
                await self._append_log(run, "warning", "Run cancelled")
            else:
                final_status = _status_from_core_manifest(job_dir)
                if final_status == "success":
                    await self._append_log(run, "info", "Run finished successfully")
                elif final_status == "cancelled":
                    await self._append_log(run, "warning", "Run cancelled")
                else:
                    run.error = "Core run finished with failed status"
                    await self._append_log(run, "error", run.error)
            run.finished_at = now_utc()
            await self._run_phase(
                run,
                "collect_artifacts",
                total,
                total,
                lambda: self._collect_artifacts(run, status=final_status),
            )
            run.status = final_status
            await self._append_event(run, _final_event_type(run.status), {"run_id": run_id, "status": run.status})
        except Exception as exc:
            run.status = "cancelled" if run.cancel_requested else "failed"
            run.error = None if run.status == "cancelled" else str(exc)
            run.finished_at = now_utc()
            await self._append_log(run, "warning" if run.status == "cancelled" else "error", str(exc))
            await self._append_event(run, "run_failed" if run.status == "failed" else "run_cancelled", {"run_id": run_id, "error": str(exc)})
            if run.job_dir is not None:
                self._collect_artifacts(run)

    async def _run_phase(
        self,
        run: _RunState,
        step: str,
        index: int,
        total: int,
        action: Callable[[], object],
    ) -> object:
        if run.cancel_requested:
            raise _RunCancelled("run cancellation requested")
        run.progress = {"current_step": step, "completed_steps": index - 1, "total_steps": total, "percent": int(((index - 1) / total) * 100)}
        await self._append_event(run, "step_started", {"run_id": run.id, "step": step, "index": index, "total": total})
        await self._append_log(run, "info", f"Processing step: {step}")
        result = await asyncio.to_thread(action)
        run.progress = {"current_step": step, "completed_steps": index, "total_steps": total, "percent": int((index / total) * 100)}
        await self._append_event(run, "progress", run.progress)
        return result

    def _core(self, run: _RunState, holder: dict[str, CalculationCore]) -> CalculationCore:
        core = holder.get("core")
        if core is None:
            core = CalculationCore(_required_job_dir(run), runtime=self._runtime_for_run(run))
            holder["core"] = core
        return core

    def _runtime_for_run(self, run: _RunState) -> RuntimeCapabilities:
        runtime = self._plugin_service.runtime_or_empty() if self._plugin_service is not None else RuntimeCapabilities()
        if self._secret_service is None:
            return runtime
        return runtime_with_backend_secrets(self._secret_service, run.session_key, base_runtime=runtime)

    def _write_core_configs(self, run: _RunState, job_dir: Path) -> None:
        job_dir.mkdir(parents=True, exist_ok=True)
        write_toml(_toml_safe(run.build_config), job_dir / "build.toml")
        if run.run_config is not None:
            write_toml(_toml_safe(run.run_config), job_dir / "run.toml")
        if run.publish_config is not None:
            write_toml(_toml_safe(run.publish_config), job_dir / "publish.toml")
        if run.rules_config is not None:
            write_core_json(run.rules_config, job_dir / "rules.json")
        if run.graph_config is not None:
            write_core_json(run.graph_config, job_dir / "graph.json")

    def _collect_artifacts(self, run: _RunState, *, status: RunStatus | None = None) -> None:
        job_dir = _required_job_dir(run)
        metadata = {
            "run_id": run.id,
            "status": status or run.status,
            "name": run.name,
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "job_dir": str(job_dir),
            "error": run.error,
            "logs": [item.model_dump(mode="json") for item in run.logs],
        }
        self._artifact_service.collect_core_artifacts(run.id, job_dir, metadata)

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


def _required_job_dir(run: _RunState) -> Path:
    if run.job_dir is None:
        raise RuntimeError("run job directory is not initialized")
    return run.job_dir


def _status_from_core_manifest(job_dir: Path) -> RunStatus:
    manifest_path = job_dir / ".calcchain" / "manifest.json"
    if not manifest_path.is_file():
        return "success"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "failed"
    status = data.get("job", {}).get("status") if isinstance(data.get("job"), dict) else None
    if status in {None, "Built", "Succeeded", "Published"}:
        return "success"
    if status == "Cancelled":
        return "cancelled"
    return "failed"


def _final_event_type(status: RunStatus) -> str:
    if status == "success":
        return "run_finished"
    if status == "cancelled":
        return "run_cancelled"
    return "run_failed"


def _toml_safe(data: dict[str, Any]) -> dict[str, Any]:
    return _drop_none(data)


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value if item is not None]
    return value


def _build_name(build_config: dict[str, Any]) -> str | None:
    if isinstance(build_config.get("name"), str):
        return build_config["name"]
    build = build_config.get("build")
    if isinstance(build, dict) and isinstance(build.get("name"), str):
        return build["name"]
    return None
