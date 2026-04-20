# Client Setup

This project is designed as a local stdio MCP server.

Official references used:

- Anthropic Claude Code MCP docs: https://docs.anthropic.com/en/docs/claude-code/mcp
- OpenAI Codex config reference: https://developers.openai.com/codex/config-reference
- OpenCode MCP docs: https://opencode.ai/docs/mcp-servers

## Shared requirement

Set `VAST_API_KEY` in your shell environment before starting the client.

Example:

```bash
export VAST_API_KEY="your_vast_api_key_here"
```

The repo also supports a local `.env` file for direct local runs.

## Claude Code

Anthropic's official project-scoped pattern is `.mcp.json` in the repo root. This repo already includes one.

If you want Claude Code to add it explicitly from the CLI:

```bash
claude mcp add --transport stdio vast-ai --scope project -- bash ./scripts/run_mcp.sh
```

Useful commands:

```bash
claude mcp list
claude mcp get vast-ai
```

## Codex

Codex uses `~/.codex/config.toml` or `.codex/config.toml` with `mcp_servers.<id>`.

Example:

```toml
[mcp_servers.vast-ai]
command = "bash"
args = ["/absolute/path/to/vast_tst_mcp/scripts/run_mcp.sh"]
cwd = "/absolute/path/to/vast_tst_mcp"
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.vast-ai.env]
VAST_API_KEY = "your_vast_api_key_here"
```

## OpenCode

OpenCode config uses `mcp.<name>` with `type = \"local\"`.

Example `opencode.jsonc`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "vast-ai": {
      "type": "local",
      "command": ["bash", "/absolute/path/to/vast_tst_mcp/scripts/run_mcp.sh"],
      "enabled": true,
      "environment": {
        "VAST_API_KEY": "your_vast_api_key_here"
      },
      "timeout": 20000
    }
  }
}
```

## Notes

- `scripts/run_mcp.sh` bootstraps `.venv` automatically on first run.
- For team use, Claude Code can rely on the checked-in `.mcp.json`.
- For Codex and OpenCode, absolute paths are usually the least fragile option.
