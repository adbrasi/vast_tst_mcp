from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class VastAIError(RuntimeError):
    """Raised when the Vast.ai API returns an error."""


class VastAIClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 30,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key or os.getenv("VAST_API_KEY")
        self.base_url = (base_url or os.getenv("VAST_API_BASE_URL") or "https://console.vast.ai").rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = requests.Session()

        if self.api_key:
            self.session.headers.update(
                {
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "vast-ai-mcp/0.1.0",
                }
            )

    def _ensure_api_key(self) -> None:
        if not self.api_key:
            raise VastAIError("VAST_API_KEY is not configured.")

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        expect_json: bool = True,
    ) -> Any:
        self._ensure_api_key()
        url = self._url(path)
        LOGGER.info("Vast.ai request %s %s", method, url)

        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_body,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                LOGGER.exception("Vast.ai request failed")
                raise VastAIError(f"Request failed: {exc}") from exc

            if response.status_code != 429 or attempt >= self.max_retries:
                break

            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 1.2 * (attempt + 1)
            LOGGER.warning("Vast.ai rate limited request, retrying in %.2fs", delay)
            time.sleep(delay)

        assert response is not None

        if response.status_code >= 400:
            detail = response.text.strip()
            try:
                payload = response.json()
                detail = payload.get("msg") or payload.get("error") or detail
            except ValueError:
                pass
            raise VastAIError(f"HTTP {response.status_code}: {detail}")

        if not expect_json:
            return response.text

        try:
            data = response.json()
        except ValueError as exc:
            raise VastAIError("Invalid JSON response from Vast.ai.") from exc

        if isinstance(data, dict) and data.get("success") is False:
            raise VastAIError(data.get("msg") or data.get("error") or "Vast.ai returned success=false.")

        return data

    def get_user_info(self) -> dict[str, Any]:
        return self._request("GET", "/api/v0/users/current/")

    def list_instances(
        self,
        *,
        limit: int = 25,
        filters: dict[str, Any] | None = None,
        select_cols: list[str] | None = None,
        order_by: list[dict[str, str]] | None = None,
        after_token: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": max(1, min(limit, 25))}
        if filters:
            params["select_filters"] = json.dumps(filters)
        if select_cols:
            params["select_cols"] = json.dumps(select_cols)
        if order_by:
            params["order_by"] = json.dumps(order_by)
        if after_token:
            params["after_token"] = after_token
        return self._request("GET", "/api/v1/instances/", params=params)

    def get_instance(self, instance_id: int) -> dict[str, Any]:
        return self._request("GET", f"/api/v0/instances/{instance_id}/")

    def search_offers(self, filters: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v0/bundles/", json_body=filters)

    def list_templates(
        self,
        *,
        filters: dict[str, Any] | None = None,
        select_cols: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if filters:
            params["select_filters"] = json.dumps(filters)
        if select_cols:
            params["select_cols"] = json.dumps(select_cols)
        return self._request("GET", "/api/v0/template/", params=params)

    def create_instance(self, offer_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/v0/asks/{offer_id}/", json_body=payload)

    def set_instance_state(self, instance_id: int, state: str) -> dict[str, Any]:
        return self._request("PUT", f"/api/v0/instances/{instance_id}/", json_body={"state": state})

    def label_instance(self, instance_id: int, label: str) -> dict[str, Any]:
        return self._request("PUT", f"/api/v0/instances/{instance_id}/", json_body={"label": label})

    def destroy_instance(self, instance_id: int) -> dict[str, Any]:
        return self._request("DELETE", f"/api/v0/instances/{instance_id}/")

    def reboot_instance(self, instance_id: int) -> dict[str, Any]:
        return self._request("PUT", f"/api/v0/instances/reboot/{instance_id}/")

    def request_instance_logs(
        self,
        instance_id: int,
        *,
        tail: int,
        grep_filter: str | None = None,
        daemon_logs: bool = False,
        fetch_retries: int = 5,
        fetch_delay_seconds: float = 2.0,
    ) -> str:
        payload: dict[str, str] = {"tail": str(tail)}
        if grep_filter:
            payload["filter"] = grep_filter
        if daemon_logs:
            payload["daemon_logs"] = "true"

        result = self._request("PUT", f"/api/v0/instances/request_logs/{instance_id}", json_body=payload)
        result_url = result.get("result_url")
        if not result_url:
            raise VastAIError(result.get("msg") or "Vast.ai did not return a logs URL.")

        LOGGER.info("Fetching logs for instance %s from result URL", instance_id)
        last_error: Exception | None = None
        for attempt in range(fetch_retries + 1):
            try:
                response = requests.get(result_url, timeout=min(self.timeout_seconds, 20))
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= fetch_retries:
                    break
                time.sleep(fetch_delay_seconds)

        raise VastAIError(f"Failed to download logs from {result_url}: {last_error}") from last_error
