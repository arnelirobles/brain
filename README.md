# brain

A local list of open items (failed tests, questions, blockers, running agents, deferred minors) shared by every session on the machine. One sqlite file, a command line, an MCP server and a web page. Nothing leaves the machine.

Brain works alone. It needs Python 3 and nothing else.

## Install

Claude Code:

```
claude plugin marketplace add arnelirobles/brain
claude plugin install brain@brain
```

This adds the `brain` MCP server (six tools: `brain_list`, `brain_show`, `brain_add`, `brain_close`, `brain_stats`, `brain_digest`) and three hooks.

Codex and Cursor: point an MCP server at `tools/brain-mcp` in a checkout of this repository. For Cursor, in `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "brain": { "command": "/path/to/brain/tools/brain-mcp" }
  }
}
```

For Codex, in `~/.codex/config.toml`:

```toml
[mcp_servers.brain]
command = "/path/to/brain/tools/brain-mcp"
```

Those tools do not run Claude Code hooks, so only the command line, the MCP server and the page apply there.

## Commands

```
brain add --project P --kind K --ref R [--title T] [--body-file -] [--tag T]
brain list [--open] [--project P] [--kind K] [--tag T] [--cycle C] [--json]
brain show ID
brain close ID --resolution R [--note N]
brain reopen ID
brain digest [--project P | --all]
brain resume [--project P]
brain stats [--json]
brain export [--format md|json]
brain session start|end|status|infer
brain notice add|list|dismiss
brain created add|list
brain activity add|list|import-baryovm
brain serve
brain --version
```

`brain --help` lists every option and the kinds and resolutions. Adding an open item with the same project, kind and ref raises its count instead of making a new row.

The database is `~/.local/share/lean/brain.db`, migrated forward when opened.

## The page

`brain serve` shows the items in a browser at `http://127.0.0.1:8770`. `brain serve --install always` starts it at login.

## Hooks

- `brain-resume.py` adds a digest of the open items at session start and after a compaction.
- `brain-session.py` records the session id, so an answer to a filed question can resume the session.
- `serve-start.py` starts the page server according to the `serve_mode` setting.

## Switches

- `LEAN_BRAIN_DB`: path of the database file.
- `LEAN_BRAIN_RESUME=off`: no digest at session start.
- `LEAN_PROFILE=off`: turns the hooks off.
- `LEAN_SERVE_PORT`: port of the page (default 8770).
- Plugin setting `serve_mode`: `manual` (default), `session` (started with a session, stops 30 minutes after the last one) or `always`.
- Plugin setting `worktree_roots`: comma-separated folders the page searches for git worktrees.

## Tests

`bash tests/run-all.sh` runs every `--self-test`. `tests/contract.py` runs the calls that lean-agent-tools and the VS Code extension make against a scratch database.

## License

MPL-2.0.
