from pathlib import Path

from vast_ai_mcp.history import HostHistoryStore


def test_host_history_store_roundtrip(tmp_path: Path):
    store = HostHistoryStore(tmp_path / "history.json")
    item = store.add(outcome="success", machine_id=123, host_id=5, gpu_name="RTX 5090", notes="worked well")
    listed = store.list(gpu_name="RTX 5090")
    assert len(listed) == 1
    assert listed[0].id == item.id
    assert listed[0].machine_id == 123
