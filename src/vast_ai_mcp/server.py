from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP

from vast_ai_mcp.client import VastAIClient, VastAIError
from vast_ai_mcp.config import load_local_env
from vast_ai_mcp.history import HostHistoryStore
from vast_ai_mcp.parsing import (
    merge_filters,
    normalize_filters,
    parse_query_filters,
    pick_offer_value,
    resolve_sort_candidates,
    sort_offers,
)
from vast_ai_mcp.scheduler import ScheduleStore, ScheduleWorker, ScheduledAction

load_local_env()

logging.basicConfig(
    level=getattr(logging, os.getenv("VAST_MCP_LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger(__name__)

DEFAULT_INSTANCE_COLUMNS = [
    "id",
    "label",
    "actual_status",
    "intended_status",
    "gpu_name",
    "num_gpus",
    "cpu_ram",
    "gpu_ram",
    "ssh_host",
    "ssh_port",
    "dph_total",
    "status_msg",
    "machine_id",
]

DEFAULT_TEMPLATE_COLUMNS = [
    "id",
    "hash_id",
    "name",
    "image",
    "recommended_disk_space",
    "ssh_direct",
    "jup_direct",
    "use_ssh",
]

DEFAULT_OFFER_FIELDS = [
    "id",
    "gpu_name",
    "num_gpus",
    "dph_total",
    "dph_base",
    "dlperf",
    "reliability",
    "reliability2",
    "cuda_vers",
    "cpu_ram",
    "gpu_ram",
    "disk_bw",
    "inet_down",
    "inet_up",
    "driver_version",
    "direct_port_count",
    "geolocation",
    "machine_id",
]

mcp = FastMCP(
    "vast-ai-mcp",
    instructions=(
        "Thin operational wrapper for Vast.ai on-demand instances. "
        "Use search_offers first, then create_instance or create_instances_from_offers, "
        "then list/get/wait/logs and instance_action as needed."
    ),
)

_client: VastAIClient | None = None
_schedule_store: ScheduleStore | None = None
_schedule_worker: ScheduleWorker | None = None
_history_store: HostHistoryStore | None = None


def get_client() -> VastAIClient:
    global _client
    if _client is None:
        _client = VastAIClient()
    return _client


def get_schedule_store() -> ScheduleStore:
    global _schedule_store
    if _schedule_store is None:
        raw_path = os.getenv("VAST_MCP_SCHEDULE_PATH")
        schedule_path = Path(raw_path).expanduser() if raw_path else Path.home() / ".vast_ai_mcp" / "schedules.json"
        _schedule_store = ScheduleStore(schedule_path)
    return _schedule_store


def get_history_store() -> HostHistoryStore:
    global _history_store
    if _history_store is None:
        raw_path = os.getenv("VAST_MCP_HISTORY_PATH")
        history_path = Path(raw_path).expanduser() if raw_path else Path.home() / ".vast_ai_mcp" / "host_history.json"
        _history_store = HostHistoryStore(history_path)
    return _history_store


def execute_scheduled_action(action: ScheduledAction) -> None:
    client = get_client()
    if action.action == "stop":
        client.set_instance_state(action.instance_id, "stopped")
        return
    if action.action == "destroy":
        client.destroy_instance(action.instance_id)
        return
    raise VastAIError(f"Unsupported scheduled action '{action.action}'.")


def ensure_schedule_worker() -> None:
    global _schedule_worker
    if _schedule_worker is None:
        _schedule_worker = ScheduleWorker(get_schedule_store(), execute_scheduled_action)
        _schedule_worker.start()


def normalize_instance_type(instance_type: str | None) -> str | None:
    if instance_type is None:
        return None
    normalized = instance_type.strip().lower()
    if normalized in {"ondemand", "on-demand", "on_demand"}:
        return "ondemand"
    if normalized in {"bid", "interruptible"}:
        return "bid"
    raise ValueError("instance_type must be 'ondemand' or 'bid'.")


def summarize_instances(instances: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for instance in instances:
        status = instance.get("actual_status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def trim_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "\n...[truncated]", True


def instance_state_key(details: dict[str, Any]) -> tuple[Any, Any]:
    return (details.get("actual_status"), details.get("intended_status"))


def score_observation(outcome: str) -> int:
    scores = {
        "success": 2,
        "fast_success": 3,
        "slow": -1,
        "failure": -3,
        "stale_offer": -1,
        "manual_blacklist": -5,
        "manual_prefer": 4,
    }
    return scores.get(outcome, 0)


def instance_matches_desired_status(details: dict[str, Any], desired: set[str]) -> bool:
    actual_status = details.get("actual_status")
    intended_status = details.get("intended_status")

    if actual_status in desired:
        return True

    if "stopped" in desired and intended_status == "stopped" and actual_status in {"exited", "stopped"}:
        return True

    return False


def normalize_offer(offer: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    result = {field: offer.get(field) for field in fields}
    result["effective_price"] = pick_offer_value(offer, "price")
    result["effective_reliability"] = pick_offer_value(offer, "reliability")
    result["effective_dlperf"] = pick_offer_value(offer, "dlperf")
    return result


@mcp.tool
def search_offers(
    query: str = "",
    filters: dict[str, Any] | None = None,
    limit: int = 20,
    instance_type: str = "ondemand",
    verified: bool | None = True,
    rentable: bool | None = True,
    sort_by: str = "dph_total",
    descending: bool = False,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Search Vast.ai offers with explicit filters and local sorting."""
    query_filters = parse_query_filters(query) if query else {}
    final_filters = normalize_filters(merge_filters(query_filters, filters))

    normalized_type = normalize_instance_type(instance_type)
    if normalized_type:
        final_filters["type"] = normalized_type
    if verified is not None:
        final_filters["verified"] = {"eq": verified}
    if rentable is not None:
        final_filters["rentable"] = {"eq": rentable}
    final_filters["limit"] = max(1, min(limit, 200))
    if "order" not in final_filters:
        final_filters["order"] = [[resolve_sort_candidates(sort_by)[0], "desc" if descending else "asc"]]

    offers = get_client().search_offers(final_filters).get("offers", [])
    offers = sort_offers(offers, sort_by=sort_by, descending=descending)
    selected_fields = fields or DEFAULT_OFFER_FIELDS

    return {
        "count": len(offers),
        "applied_filters": final_filters,
        "sort_by": sort_by,
        "descending": descending,
        "offers": [normalize_offer(offer, selected_fields) for offer in offers[:limit]],
    }


@mcp.tool
def get_user_info() -> dict[str, Any]:
    """Return current account and credit information."""
    data = get_client().get_user_info()
    return {
        "id": data.get("id"),
        "username": data.get("username"),
        "email": data.get("email"),
        "balance": data.get("balance"),
        "credit": data.get("credit"),
        "can_pay": data.get("can_pay"),
        "balance_threshold": data.get("balance_threshold"),
        "autobill_threshold": data.get("autobill_threshold"),
        "total_spend": data.get("total_spend"),
    }


@mcp.tool
def list_templates(
    query: str = "",
    filters: dict[str, Any] | None = None,
    limit: int = 25,
    order_by: str | None = "name",
    select_cols: list[str] | None = None,
) -> dict[str, Any]:
    """List your own and shared Vast.ai templates."""
    query_filters = parse_query_filters(query) if query else {}
    final_filters = merge_filters(query_filters, filters)
    payload = get_client().list_templates(
        filters=final_filters or None,
        select_cols=select_cols or DEFAULT_TEMPLATE_COLUMNS,
    )
    templates = payload.get("templates", [])[: max(1, limit)]
    if order_by:
        templates = sorted(templates, key=lambda item: (item.get(order_by) is None, item.get(order_by)))
    return {
        "count": len(templates),
        "templates": templates,
    }


@mcp.tool
def list_instances(
    status: str | None = None,
    query: str = "",
    filters: dict[str, Any] | None = None,
    limit: int = 25,
    order_by: list[dict[str, str]] | None = None,
    after_token: str | None = None,
    select_cols: list[str] | None = None,
) -> dict[str, Any]:
    """List current Vast.ai instances with concise status fields."""
    query_filters = parse_query_filters(query) if query else {}
    final_filters = merge_filters(query_filters, filters)
    if status:
        final_filters["actual_status"] = {"eq": status}

    result = get_client().list_instances(
        limit=limit,
        filters=final_filters or None,
        select_cols=select_cols or DEFAULT_INSTANCE_COLUMNS,
        order_by=order_by,
        after_token=after_token,
    )
    instances = result.get("instances", [])
    return {
        "count": len(instances),
        "total_instances": result.get("total_instances"),
        "next_token": result.get("next_token"),
        "status_counts": summarize_instances(instances),
        "instances": instances,
    }


@mcp.tool
def get_instance(instance_id: int) -> dict[str, Any]:
    """Fetch detailed information for one instance."""
    return get_client().get_instance(instance_id).get("instances", {})


@mcp.tool
def create_instance(
    offer_id: int,
    image: str | None = None,
    template_hash_id: str | None = None,
    label: str | None = None,
    disk: float | None = None,
    runtype: str | None = None,
    env: dict[str, str] | None = None,
    onstart: str | None = None,
    args_str: str | None = None,
    target_state: Literal["running", "stopped"] | None = None,
    price: float | None = None,
    cancel_unavail: bool | None = None,
    vm: bool | None = None,
) -> dict[str, Any]:
    """Create one instance from an offer using an image or an existing template hash."""
    if not image and not template_hash_id:
        raise ValueError("Provide either image or template_hash_id.")

    payload: dict[str, Any] = {}
    if image:
        payload["image"] = image
    if template_hash_id:
        payload["template_hash_id"] = template_hash_id
    if label:
        payload["label"] = label
    if disk is not None:
        payload["disk"] = disk
    if runtype:
        payload["runtype"] = runtype
    if env:
        payload["env"] = env
    if onstart:
        payload["onstart"] = onstart
    if args_str:
        payload["args_str"] = args_str
    if target_state:
        payload["target_state"] = target_state
    if price is not None:
        payload["price"] = price
    if cancel_unavail is not None:
        payload["cancel_unavail"] = cancel_unavail
    if vm is not None:
        payload["vm"] = vm

    created = get_client().create_instance(offer_id, payload)
    return {
        "offer_id": offer_id,
        "request": payload,
        "result": created,
    }


@mcp.tool
def create_instances_from_offers(
    offer_ids: list[int],
    image: str | None = None,
    template_hash_id: str | None = None,
    label_prefix: str | None = None,
    disk: float | None = None,
    runtype: str | None = None,
    env: dict[str, str] | None = None,
    onstart: str | None = None,
    args_str: str | None = None,
    target_state: Literal["running", "stopped"] | None = None,
    price: float | None = None,
    cancel_unavail: bool | None = None,
    vm: bool | None = None,
) -> dict[str, Any]:
    """Create multiple instances from explicit offer IDs without making selection decisions."""
    results: list[dict[str, Any]] = []
    for index, offer_id in enumerate(offer_ids, start=1):
        label = f"{label_prefix}-{index}" if label_prefix else None
        try:
            result = create_instance(
                offer_id=offer_id,
                image=image,
                template_hash_id=template_hash_id,
                label=label,
                disk=disk,
                runtype=runtype,
                env=env,
                onstart=onstart,
                args_str=args_str,
                target_state=target_state,
                price=price,
                cancel_unavail=cancel_unavail,
                vm=vm,
            )
        except Exception as exc:
            results.append({"offer_id": offer_id, "ok": False, "error": str(exc)})
        else:
            results.append({"offer_id": offer_id, "ok": True, "result": result.get("result")})
    return {
        "count": len(results),
        "results": results,
    }


@mcp.tool
def instance_action(
    instance_ids: list[int],
    action: Literal["start", "stop", "destroy", "reboot", "label"],
    label: str | None = None,
) -> dict[str, Any]:
    """Apply one lifecycle action to one or more instances."""
    client = get_client()
    results: list[dict[str, Any]] = []

    for instance_id in instance_ids:
        try:
            if action == "start":
                response = client.set_instance_state(instance_id, "running")
            elif action == "stop":
                response = client.set_instance_state(instance_id, "stopped")
            elif action == "destroy":
                response = client.destroy_instance(instance_id)
            elif action == "reboot":
                response = client.reboot_instance(instance_id)
            elif action == "label":
                if not label:
                    raise ValueError("label is required when action='label'.")
                response = client.label_instance(instance_id, label)
            else:
                raise ValueError(f"Unsupported action '{action}'.")
        except Exception as exc:
            results.append({"instance_id": instance_id, "ok": False, "error": str(exc)})
        else:
            results.append({"instance_id": instance_id, "ok": True, "response": response})

    return {
        "action": action,
        "results": results,
    }


@mcp.tool
def get_instance_logs(
    instance_id: int,
    tail: int = 120,
    grep_filter: str | None = None,
    daemon_logs: bool = False,
    max_chars: int = 5000,
) -> dict[str, Any]:
    """Fetch a short logs excerpt for one instance."""
    fallback = None
    try:
        logs = get_client().request_instance_logs(
            instance_id,
            tail=tail,
            grep_filter=grep_filter,
            daemon_logs=daemon_logs,
        )
    except Exception as exc:
        details = get_client().get_instance(instance_id).get("instances", {})
        fallback = {
            "error": str(exc),
            "status_msg": details.get("status_msg"),
            "actual_status": details.get("actual_status"),
            "intended_status": details.get("intended_status"),
        }
        logs = details.get("status_msg") or ""

    excerpt, truncated = trim_text(logs, max_chars=max_chars)
    return {
        "instance_id": instance_id,
        "tail": tail,
        "grep_filter": grep_filter,
        "daemon_logs": daemon_logs,
        "truncated": truncated,
        "excerpt": excerpt,
        "fallback": fallback,
    }


@mcp.tool
def wait_for_instances(
    instance_ids: list[int],
    timeout_seconds: int = 180,
    poll_interval_seconds: int = 15,
    desired_statuses: list[str] | None = None,
    include_logs: bool = False,
    log_tail: int = 40,
    log_max_chars: int = 1500,
) -> dict[str, Any]:
    """Poll instances until they reach a desired state or timeout."""
    desired = set(desired_statuses or ["running"])
    started_at = time.time()
    deadline = time.time() + timeout_seconds
    snapshots: list[dict[str, Any]] = []
    final_instances: dict[int, dict[str, Any]] = {}
    state_started_at: dict[int, float] = {}
    last_state_by_instance: dict[int, tuple[Any, Any]] = {}

    while time.time() < deadline:
        now = time.time()
        listed_instances: list[dict[str, Any]] = []
        next_token: str | None = None
        requested_ids = set(instance_ids)
        while True:
            result = get_client().list_instances(
                limit=min(max(len(instance_ids), 1), 200),
                filters={"id": {"in": instance_ids}},
                select_cols=DEFAULT_INSTANCE_COLUMNS + ["host_id", "cur_state", "next_state"],
                after_token=next_token,
            )
            listed_instances.extend(result.get("instances", []))
            found_ids = {item.get("id") for item in listed_instances}
            next_token = result.get("next_token")
            if not next_token or requested_ids.issubset(found_ids):
                break

        current: list[dict[str, Any]] = []
        all_ready = True

        found_by_id = {instance["id"]: instance for instance in listed_instances}
        for instance_id in instance_ids:
            details = found_by_id.get(instance_id, {"id": instance_id, "actual_status": None})
            state_key = instance_state_key(details)
            if last_state_by_instance.get(instance_id) != state_key:
                last_state_by_instance[instance_id] = state_key
                state_started_at[instance_id] = now

            current_state_duration_seconds = int(now - state_started_at[instance_id])
            details_with_wait = dict(details)
            details_with_wait["current_state_duration_seconds"] = current_state_duration_seconds
            details_with_wait["wait_elapsed_seconds"] = int(now - started_at)

            final_instances[instance_id] = details_with_wait
            actual_status = details.get("actual_status")
            current.append(
                {
                    "instance_id": instance_id,
                    "actual_status": actual_status,
                    "intended_status": details.get("intended_status"),
                    "status_msg": details.get("status_msg"),
                    "current_state_duration_seconds": current_state_duration_seconds,
                }
            )
            if not instance_matches_desired_status(details, desired):
                all_ready = False

        snapshots.append(
            {
                "elapsed_seconds": int(now - started_at),
                "instances": current,
            }
        )

        if all_ready:
            break

        time.sleep(max(1, poll_interval_seconds))

    logs: list[dict[str, Any]] = []
    if include_logs:
        for instance_id, details in final_instances.items():
            if instance_matches_desired_status(details, desired):
                continue
            try:
                excerpt = get_instance_logs(
                    instance_id=instance_id,
                    tail=log_tail,
                    max_chars=log_max_chars,
                )
            except Exception as exc:
                logs.append({"instance_id": instance_id, "error": str(exc)})
            else:
                logs.append(excerpt)

    return {
        "desired_statuses": sorted(desired),
        "timed_out": any((not instance_matches_desired_status(details, desired)) for details in final_instances.values()),
        "snapshots": snapshots,
        "final_instances": list(final_instances.values()),
        "logs": logs,
    }


@mcp.tool
def schedule_instance_action(
    instance_id: int,
    action: Literal["stop", "destroy"],
    in_hours: float | None = None,
    in_minutes: int | None = None,
    at_iso: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Schedule a future stop or destroy action while the MCP server is running."""
    provided = [value is not None for value in (in_hours, in_minutes, at_iso)]
    if sum(provided) != 1:
        raise ValueError("Provide exactly one of in_hours, in_minutes, or at_iso.")

    if at_iso is not None:
        run_at = datetime.fromisoformat(at_iso)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
    elif in_hours is not None:
        run_at = datetime.now(timezone.utc) + timedelta(hours=in_hours)
    else:
        run_at = datetime.now(timezone.utc) + timedelta(minutes=in_minutes or 0)

    ensure_schedule_worker()
    scheduled = get_schedule_store().add(instance_id=instance_id, action=action, run_at=run_at, reason=reason)
    return scheduled.__dict__


@mcp.tool
def list_scheduled_actions(status: str | None = None) -> dict[str, Any]:
    """List scheduled stop/destroy actions."""
    actions = [item.__dict__ for item in get_schedule_store().list(status=status)]
    return {"count": len(actions), "actions": actions}


@mcp.tool
def cancel_scheduled_action(schedule_id: str) -> dict[str, Any]:
    """Cancel one scheduled action."""
    try:
        action = get_schedule_store().cancel(schedule_id)
    except KeyError as exc:
        raise ValueError(f"Unknown schedule_id '{schedule_id}'.") from exc
    return action.__dict__


@mcp.tool
def record_host_observation(
    outcome: Literal["success", "fast_success", "slow", "failure", "stale_offer", "manual_blacklist", "manual_prefer"],
    notes: str | None = None,
    machine_id: int | None = None,
    host_id: int | None = None,
    offer_id: int | None = None,
    instance_id: int | None = None,
    gpu_name: str | None = None,
    label: str | None = None,
    geolocation: str | None = None,
) -> dict[str, Any]:
    """Persist a simple local observation about a machine/host/offer."""
    if instance_id and (machine_id is None or host_id is None or gpu_name is None or label is None):
        details = get_client().get_instance(instance_id).get("instances", {})
        machine_id = machine_id or details.get("machine_id")
        host_id = host_id or details.get("host_id")
        gpu_name = gpu_name or details.get("gpu_name")
        label = label or details.get("label")
        geolocation = geolocation or details.get("geolocation")

    observation = get_history_store().add(
        outcome=outcome,
        notes=notes,
        machine_id=machine_id,
        host_id=host_id,
        offer_id=offer_id,
        instance_id=instance_id,
        gpu_name=gpu_name,
        label=label,
        geolocation=geolocation,
    )
    return observation.__dict__


@mcp.tool
def list_host_rankings(gpu_name: str | None = None) -> dict[str, Any]:
    """Summarize locally recorded host/machine observations for preference or blacklist use."""
    observations = get_history_store().list(gpu_name=gpu_name)
    by_machine: dict[int, dict[str, Any]] = {}

    for obs in observations:
        key = obs.machine_id or -1
        row = by_machine.setdefault(
            key,
            {
                "machine_id": obs.machine_id,
                "host_id": obs.host_id,
                "gpu_name": obs.gpu_name,
                "geolocation": obs.geolocation,
                "score": 0,
                "counts": {},
                "latest_note": None,
                "latest_at": None,
            },
        )
        row["score"] += score_observation(obs.outcome)
        row["counts"][obs.outcome] = row["counts"].get(obs.outcome, 0) + 1
        if row["latest_at"] is None or obs.created_at > row["latest_at"]:
            row["latest_at"] = obs.created_at
            row["latest_note"] = obs.notes

    ranked = sorted(by_machine.values(), key=lambda item: item["score"], reverse=True)
    return {
        "count": len(ranked),
        "machines": ranked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Vast.ai MCP server")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate local configuration and print the resolved paths.",
    )
    args = parser.parse_args()

    if args.check_config:
        schedule_path = os.getenv("VAST_MCP_SCHEDULE_PATH", str(Path.home() / ".vast_ai_mcp" / "schedules.json"))
        print(
            {
                "has_api_key": bool(os.getenv("VAST_API_KEY")),
                "base_url": os.getenv("VAST_API_BASE_URL", "https://console.vast.ai"),
                "schedule_path": schedule_path,
                "cwd": str(Path.cwd()),
            }
        )
        return

    ensure_schedule_worker()
    mcp.run()
