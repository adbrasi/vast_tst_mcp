from vast_ai_mcp.server import instance_matches_desired_status


def test_instance_matches_desired_status_treats_exited_with_intended_stopped_as_stopped():
    details = {"actual_status": "exited", "intended_status": "stopped"}
    assert instance_matches_desired_status(details, {"stopped"}) is True


def test_instance_matches_desired_status_normal_running():
    details = {"actual_status": "running", "intended_status": "running"}
    assert instance_matches_desired_status(details, {"running"}) is True
