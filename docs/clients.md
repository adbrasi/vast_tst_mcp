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

## One-command launcher

The simplest remote install pattern is:

```bash
npx -y github:adbrasi/vast_tst_mcp
```

This launcher bootstraps a cached Python virtualenv automatically and starts the stdio MCP server.

If you prefer `uvx`, this also works:

```bash
uvx --from git+https://github.com/adbrasi/vast_tst_mcp vast-ai-mcp
```

## Claude Code

Anthropic's official project-scoped pattern is `.mcp.json` in the repo root. This repo already includes one.

If you want Claude Code to add it explicitly from the CLI:

```bash
claude mcp add vast-ai --scope project --env VAST_API_KEY=YOUR_KEY -- npx -y github:adbrasi/vast_tst_mcp
```

Useful commands:

```bash
claude mcp list
claude mcp get vast-ai
```

## Codex

Codex uses `~/.codex/config.toml` or `.codex/config.toml` with `mcp_servers.<id>`.

This repo now also includes a project-scoped [.codex/config.toml](../.codex/config.toml) for local checkout usage.

Example:

```toml
[mcp_servers.vast-ai]
command = "npx"
args = ["-y", "github:adbrasi/vast_tst_mcp"]
startup_timeout_sec = 120
tool_timeout_sec = 120

[mcp_servers.vast-ai.env]
VAST_API_KEY = "your_vast_api_key_here"
```

If you prefer a checked-out repo instead of `npx`:

```toml
[mcp_servers.vast-ai]
command = "node"
args = ["/absolute/path/to/vast_tst_mcp/bin/vast-tst-mcp.js"]
cwd = "/absolute/path/to/vast_tst_mcp"
startup_timeout_sec = 120
tool_timeout_sec = 120

[mcp_servers.vast-ai.env]
VAST_API_KEY = "your_vast_api_key_here"
```

## OpenCode

OpenCode config uses `mcp.<name>` with `type = \"local\"`.

This repo now also includes a project-scoped [opencode.json](../opencode.json) for local checkout usage.

Example `opencode.jsonc`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "vast-ai": {
      "type": "local",
      "command": ["npx", "-y", "github:adbrasi/vast_tst_mcp"],
      "enabled": true,
      "environment": {
        "VAST_API_KEY": "your_vast_api_key_here"
      },
      "timeout": 120000
    }
  }
}
```

## Notes

- `npx -y github:adbrasi/vast_tst_mcp` is the shortest install-and-run path.
- `node ./bin/vast-tst-mcp.js` is the simplest checked-out repo path.
- For team use, Claude Code can rely on the checked-in `.mcp.json`.
- For Codex and OpenCode, absolute paths are usually the least fragile option.
