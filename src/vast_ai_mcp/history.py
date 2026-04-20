from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HostObservation:
    id: str
    created_at: str
    outcome: str
    notes: str | None = None
    gpu_name: str | None = None
    machine_id: int | None = None
    host_id: int | None = None
    offer_id: int | None = None
    instance_id: int | None = None
    label: str | None = None
    geolocation: str | None = None


class HostHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _read(self) -> list[HostObservation]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [HostObservation(**item) for item in raw]

    def _write(self, items: list[HostObservation]) -> None:
        self.path.write_text(
            json.dumps([asdict(item) for item in items], indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def add(self, **kwargs) -> HostObservation:
        with self.lock:
            items = self._read()
            observation = HostObservation(
                id=uuid.uuid4().hex[:12],
                created_at=utc_now_iso(),
                **kwargs,
            )
            items.append(observation)
            self._write(items)
        return observation

    def list(self, gpu_name: str | None = None) -> list[HostObservation]:
        with self.lock:
            items = self._read()
        if gpu_name:
            return [item for item in items if item.gpu_name == gpu_name]
        return items
