from __future__ import annotations

import re
import shlex
from typing import Any

FILTER_RE = re.compile(r"^(?P<key>[A-Za-z0-9_]+)\s*(?P<op>>=|<=|!=|=|>|<)\s*(?P<value>.+)$")

OPERATOR_MAP = {
    "=": "eq",
    "!=": "neq",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
}

SORT_ALIASES: dict[str, tuple[str, ...]] = {
    "price": ("dph_total", "dph_base", "dph"),
    "dph": ("dph_total", "dph_base", "dph"),
    "dlperf": ("dlperf",),
    "score": ("score",),
    "reliability": ("reliability2", "reliability"),
    "num_gpus": ("num_gpus",),
    "gpu_ram": ("gpu_ram",),
    "cpu_ram": ("cpu_ram",),
    "disk_bw": ("disk_bw",),
    "inet_down": ("inet_down",),
}


def _normalize_named_value(key: str, value: Any) -> Any:
    if key in {"gpu_name", "cpu_name"}:
        if isinstance(value, str):
            return value.replace("_", " ")
        if isinstance(value, list):
            return [item.replace("_", " ") if isinstance(item, str) else item for item in value]
    return value


def coerce_scalar(value: str) -> Any:
    raw = value.strip()
    lowered = raw.lower()

    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None

    if raw.startswith("[") and raw.endswith("]"):
        items = [item.strip() for item in raw[1:-1].split(",") if item.strip()]
        return [coerce_scalar(item) for item in items]

    if "," in raw and not raw.startswith("http"):
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if len(parts) > 1:
            return [coerce_scalar(part) for part in parts]

    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def parse_query_filters(query: str) -> dict[str, dict[str, Any]]:
    filters: dict[str, dict[str, Any]] = {}
    if not query.strip():
        return filters

    for token in shlex.split(query):
        match = FILTER_RE.match(token)
        if not match:
            raise ValueError(
                f"Invalid filter token '{token}'. Use patterns like gpu_name=RTX_5090 or num_gpus>=1."
            )

        key = match.group("key")
        op = OPERATOR_MAP[match.group("op")]
        value = coerce_scalar(match.group("value"))
        value = _normalize_named_value(key, value)

        if isinstance(value, list) and op == "eq":
            op = "in"

        filters[key] = {op: value}

    return filters


def merge_filters(*parts: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for part in parts:
        if not part:
            continue
        for key, value in part.items():
            merged[key] = value
    return merged


def normalize_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    if not filters:
        return {}

    normalized: dict[str, Any] = {}
    for key, operations in filters.items():
        if isinstance(operations, dict):
            normalized[key] = {}
            for op, value in operations.items():
                normalized[key][op] = _normalize_named_value(key, value)
            continue

        normalized[key] = _normalize_named_value(key, operations)
    return normalized


def resolve_sort_candidates(sort_by: str) -> tuple[str, ...]:
    key = sort_by.strip().lower()
    return SORT_ALIASES.get(key, (sort_by,))


def pick_offer_value(offer: dict[str, Any], sort_by: str) -> Any:
    for candidate in resolve_sort_candidates(sort_by):
        if candidate in offer and offer[candidate] is not None:
            return offer[candidate]
    return None


def sort_offers(offers: list[dict[str, Any]], sort_by: str, descending: bool) -> list[dict[str, Any]]:
    def sort_key(offer: dict[str, Any]) -> tuple[int, Any]:
        value = pick_offer_value(offer, sort_by)
        return (value is None, value)

    return sorted(offers, key=sort_key, reverse=descending)
