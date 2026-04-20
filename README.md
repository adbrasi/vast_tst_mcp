# vast_tst_mcp

Practical MCP server for Vast.ai on-demand instances.

This repository is an independent tool and is not affiliated with Vast.ai.

This project intentionally stays thin. It does not try to decide which offer is "best" for you. The agent does the reasoning. The MCP only gives the agent reliable tools to:

- search and sort offers
- reuse your Vast.ai templates
- create one or many instances from explicit offer IDs
- inspect states and details
- fetch short logs excerpts
- wait/poll for status changes
- inspect account credit and spend
- start, stop, reboot, destroy, or label instances
- schedule a future stop or destroy
- keep a local memory of good/bad machines and hosts

## Why this shape

The official Vast.ai API already supports the hard parts you need for normal hourly rentals:

- search offers
- create instances from offers or templates
- list and inspect instances
- start, stop, reboot, destroy
- request logs

The extra value here is only standardization for agents, not hidden decision logic.

Relevant official docs used while building this server:

- `POST /api/v0/bundles/` for search
- `PUT /api/v0/asks/{offer_id}/` for instance creation
- `GET /api/v1/instances/` and `GET /api/v0/instances/{id}/` for state and details
- `PUT /api/v0/instances/{id}/` for start/stop/label
- `DELETE /api/v0/instances/{id}/` for destroy
- `PUT /api/v0/instances/reboot/{id}/` for reboot
- `PUT /api/v0/instances/request_logs/{id}` for logs
- `GET /api/v0/template/` for template search

Client integration patterns are documented in [docs/clients.md](docs/clients.md).

## Quick start

```bash
npx -y github:adbrasi/vast_tst_mcp --check-config
```

This is now the recommended path. The launcher creates a local cached Python runtime for the MCP automatically on first run.

Set your token before starting the MCP:

```bash
export VAST_API_KEY="your_vast_api_key_here"
```

You can also use `uvx` if you prefer the Python-native route:

```bash
uvx --from git+https://github.com/adbrasi/vast_tst_mcp vast-ai-mcp --check-config
```

## Repo-local development install

If you want the repository checked out locally for development:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

At minimum, set `VAST_API_KEY`.

The server auto-loads `.env` from the repo root or current working directory.

Quick config check:

```bash
npx -y github:adbrasi/vast_tst_mcp --check-config
```

If you are running from a local checkout, these also work:

```bash
node ./bin/vast-tst-mcp.js --check-config
./scripts/run_mcp.sh --check-config
```

## MCP client config

Example config is in [mcp-config.example.json](mcp-config.example.json).

For client-specific setup for Claude Code, Codex, and OpenCode, see [docs/clients.md](docs/clients.md).

The shortest portable launcher is:

```json
{
  "command": "npx",
  "args": ["-y", "github:adbrasi/vast_tst_mcp"]
}
```

If you prefer a local checkout, use:

```json
{
  "command": "node",
  "args": ["/absolute/path/to/vast_tst_mcp/bin/vast-tst-mcp.js"]
}
```

## Tools

### `search_offers`

Flexible search with CLI-like filters plus explicit sorting.

Example:

```text
query="gpu_name=RTX_5090 num_gpus>=1 rented=false"
sort_by="dph_total"
descending=false
instance_type="ondemand"
limit=10
```

`gpu_name` and `cpu_name` values are normalized, so `RTX_5090` and `RTX 5090` both work.

Useful sort fields:

- `price` or `dph_total`
- `dlperf`
- `reliability`
- `num_gpus`
- `gpu_ram`
- `cpu_ram`
- `inet_down`

### `list_templates`

Use this to find your template `hash_id`, then pass that into instance creation.

### `create_instance`

Create one instance from one offer ID.

Pass either:

- `image`
- `template_hash_id`

### `create_instances_from_offers`

Batch create multiple instances from explicit offer IDs. This is useful for your "open 10 good 5090 offers, keep the survivors" workflow.

### `list_instances`

Concise status listing with counts grouped by `actual_status`.

### `get_instance`

Detailed inspection of one instance, including status fields such as:

- `actual_status`
- `intended_status`
- `status_msg`
- connection fields like `ssh_host` and `ssh_port`

### `get_user_info`

Useful for checking current `credit`, `balance`, and `total_spend` before and after short tests.

### `get_instance_logs`

Downloads logs through Vast.ai's logs endpoint and returns only a short excerpt. This avoids flooding the model with giant logs from multiple instances.

The MCP now retries both the Vast.ai request and the S3 log download because the real API frequently returns logs asynchronously.

### `wait_for_instances`

Simple polling helper. It does not decide anything. It only waits until the given instances reach a desired status or timeout, and can optionally attach short logs for instances that did not reach the target.

It uses a single `list_instances` call per polling cycle for the whole batch to reduce `429` rate limits.

Each snapshot now includes `current_state_duration_seconds`, so an agent can reason about cases like "this instance has been loading for 95 seconds already".

### `instance_action`

Batch action wrapper for:

- `start`
- `stop`
- `destroy`
- `reboot`
- `label`

### `schedule_instance_action`

Minimal future action support while the MCP server is running:

- `stop`
- `destroy`

Also available:

- `list_scheduled_actions`
- `cancel_scheduled_action`

### `record_host_observation` and `list_host_rankings`

Local memory for daily use. This is intentionally simple:

- record that a machine or host was good, slow, bad, stale, manually preferred, or manually blacklisted
- retrieve a ranked summary later for future launches

This does not auto-decide for the agent. It only preserves evidence.

## Production notes from real tests

Real API validation in this repo found a few Vast.ai-specific behaviors worth knowing:

- `stop` commonly ends up as `actual_status = "exited"` plus `intended_status = "stopped"`. The MCP treats that as a successful stopped state.
- Search results can include stale asks. A cheap offer may fail with `no_such_ask` during create even if it appeared moments earlier.
- The logs endpoint can return an S3 URL that still fails temporarily. The MCP retries and falls back to instance `status_msg` when needed.
- Batch polling should prefer `list_instances` over one `get_instance` call per instance to reduce `429` rate limits.

## Example agent flow

1. `search_offers` for `RTX_5090`, sorted by `price`.
2. `list_templates` to find the template hash.
3. `create_instances_from_offers` using the cheapest acceptable offer IDs.
4. `wait_for_instances` for `running` with a 3-minute timeout.
5. `get_instance_logs` only for the instances that look suspicious.
6. `instance_action(action="destroy")` on the failures.
7. Keep using `list_instances` and `get_instance` while working.
8. `schedule_instance_action(action="destroy", in_hours=...)` if needed.

## Development

Run tests:

```bash
source .venv/bin/activate
pytest -q
```
