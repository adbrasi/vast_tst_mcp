from vast_ai_mcp import server
from vast_ai_mcp.server import instance_matches_desired_status


def test_instance_matches_desired_status_treats_exited_with_intended_stopped_as_stopped():
    details = {"actual_status": "exited", "intended_status": "stopped"}
    assert instance_matches_desired_status(details, {"stopped"}) is True


def test_instance_matches_desired_status_normal_running():
    details = {"actual_status": "running", "intended_status": "running"}
    assert instance_matches_desired_status(details, {"running"}) is True


def test_wait_for_instances_reports_current_state_duration(monkeypatch):
    class FakeTime:
        def __init__(self):
            self.current = 0.0

        def time(self):
            return self.current

        def sleep(self, seconds):
            self.current += seconds

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def list_instances(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                status = "loading"
            elif self.calls == 2:
                status = "loading"
            else:
                status = "running"
            return {
                "instances": [
                    {
                        "id": 123,
                        "actual_status": status,
                        "intended_status": "running",
                        "status_msg": status,
                    }
                ]
            }

    fake_time = FakeTime()
    fake_client = FakeClient()

    monkeypatch.setattr(server, "get_client", lambda: fake_client)
    monkeypatch.setattr(server.time, "time", fake_time.time)
    monkeypatch.setattr(server.time, "sleep", fake_time.sleep)

    result = server.wait_for_instances(
        instance_ids=[123],
        timeout_seconds=60,
        poll_interval_seconds=15,
        desired_statuses=["running"],
    )

    assert result["timed_out"] is False
    assert result["snapshots"][0]["instances"][0]["current_state_duration_seconds"] == 0
    assert result["snapshots"][1]["instances"][0]["current_state_duration_seconds"] == 15
    assert result["final_instances"][0]["actual_status"] == "running"
    assert result["final_instances"][0]["current_state_duration_seconds"] == 0


def test_search_offers_sends_order_to_api(monkeypatch):
    captured = {}

    class FakeClient:
        def search_offers(self, filters):
            captured["filters"] = filters
            return {"offers": [{"id": 1, "dph_total": 0.7}, {"id": 2, "dph_total": 0.9}]}

    monkeypatch.setattr(server, "get_client", lambda: FakeClient())

    result = server.search_offers(limit=2, sort_by="price", descending=False)

    assert result["offers"][0]["id"] == 1
    assert captured["filters"]["order"] == [["dph_total", "asc"]]
    assert captured["filters"]["limit"] == 2


def test_create_instances_from_offers_passes_vm(monkeypatch):
    calls = []

    def fake_create_instance(**kwargs):
        calls.append(kwargs)
        return {"result": {"new_contract": kwargs["offer_id"]}}

    monkeypatch.setattr(server, "create_instance", fake_create_instance)

    result = server.create_instances_from_offers(
        offer_ids=[11, 12],
        image="vastai/base-image",
        vm=True,
    )

    assert result["count"] == 2
    assert all(call["vm"] is True for call in calls)
