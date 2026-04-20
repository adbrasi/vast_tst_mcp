from datetime import timedelta
from pathlib import Path

from vast_ai_mcp.scheduler import ScheduleStore, utc_now


def test_schedule_store_roundtrip(tmp_path: Path):
    store = ScheduleStore(tmp_path / "schedules.json")
    scheduled = store.add(instance_id=123, action="stop", run_at=utc_now() + timedelta(minutes=5), reason="test")

    listed = store.list()
    assert len(listed) == 1
    assert listed[0].id == scheduled.id
    assert listed[0].status == "scheduled"

    cancelled = store.cancel(scheduled.id)
    assert cancelled.status == "cancelled"
    assert store.list(status="cancelled")[0].id == scheduled.id
