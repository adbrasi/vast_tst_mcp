from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

LOGGER = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScheduledAction:
    id: str
    instance_id: int
    action: str
    run_at: str
    created_at: str
    reason: str | None = None
    status: str = "scheduled"
    last_error: str | None = None

    @property
    def run_at_dt(self) -> datetime:
        return datetime.fromisoformat(self.run_at)


class ScheduleStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _read(self) -> list[ScheduledAction]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [ScheduledAction(**item) for item in raw]

    def _write(self, items: list[ScheduledAction]) -> None:
        data = [asdict(item) for item in items]
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def add(self, instance_id: int, action: str, run_at: datetime, reason: str | None = None) -> ScheduledAction:
        with self.lock:
            items = self._read()
            record = ScheduledAction(
                id=uuid.uuid4().hex[:12],
                instance_id=instance_id,
                action=action,
                run_at=run_at.astimezone(timezone.utc).isoformat(),
                created_at=utc_now().isoformat(),
                reason=reason,
            )
            items.append(record)
            self._write(items)
        return record

    def list(self, *, status: str | None = None) -> list[ScheduledAction]:
        with self.lock:
            items = self._read()
        if status:
            return [item for item in items if item.status == status]
        return items

    def cancel(self, schedule_id: str) -> ScheduledAction:
        with self.lock:
            items = self._read()
            for item in items:
                if item.id == schedule_id:
                    item.status = "cancelled"
                    self._write(items)
                    return item
        raise KeyError(schedule_id)

    def due(self, now: datetime) -> list[ScheduledAction]:
        return [
            item
            for item in self.list(status="scheduled")
            if item.run_at_dt <= now.astimezone(timezone.utc)
        ]

    def mark_done(self, schedule_id: str) -> ScheduledAction:
        return self._mark(schedule_id, status="done", last_error=None)

    def mark_failed(self, schedule_id: str, error: str) -> ScheduledAction:
        return self._mark(schedule_id, status="failed", last_error=error)

    def _mark(self, schedule_id: str, *, status: str, last_error: str | None) -> ScheduledAction:
        with self.lock:
            items = self._read()
            for item in items:
                if item.id == schedule_id:
                    item.status = status
                    item.last_error = last_error
                    self._write(items)
                    return item
        raise KeyError(schedule_id)


class ScheduleWorker:
    def __init__(
        self,
        store: ScheduleStore,
        executor: Callable[[ScheduledAction], None],
        poll_seconds: int = 15,
    ) -> None:
        self.store = store
        self.executor = executor
        self.poll_seconds = poll_seconds
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vast-ai-mcp-scheduler", daemon=True)
        self._thread.start()
        LOGGER.info("Schedule worker started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            for action in self.store.due(utc_now()):
                try:
                    LOGGER.info("Executing scheduled action %s for instance %s", action.action, action.instance_id)
                    self.executor(action)
                except Exception as exc:
                    LOGGER.exception("Scheduled action failed")
                    self.store.mark_failed(action.id, str(exc))
                else:
                    self.store.mark_done(action.id)
            time.sleep(self.poll_seconds)
