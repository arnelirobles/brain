#!/usr/bin/env python3
"""The calls lean-agent-tools and the VS Code extension make to brain, run against a scratch database.

  tests/contract.py --self-test

Each check runs the real tools/brain with LEAN_BRAIN_DB and HOME under a temp folder and looks at the
exit code and, for --json calls, the keys. Also checked: the version matches plugin.json, hooks.json
registers each hook for the events, matcher and timeout in its HOOK literal, and the brain.db tables
and columns the extension reads exist. The extension's reads of tests.db belong to lean-agent-tools
and are not listed here.
"""
import ast
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BRAIN = os.path.join(ROOT, "tools", "brain")

ITEM_KEYS = {"id", "kind", "status", "project", "repo", "branch", "cycle", "run_id", "ref", "title", "tags",
             "first_seen", "last_seen"}

# Tables and columns vscode/src/queries.ts reads from brain.db (items is read with SELECT *, into ItemFull).
EXTENSION_READS = {
    "meta": {"key", "value"},
    "items": {"id", "project", "kind", "ref", "title", "severity", "cycle", "occurrences", "first_seen",
              "last_seen", "status", "closed_at", "repo", "branch", "body", "resolution", "phase", "source",
              "model", "commit_hash", "link", "run_id", "session_id", "session_cwd"},
    "tags": {"item_id", "tag"},
    "sessions": {"id", "ended_at"},
    "activities": {"id", "source", "ts", "action", "project", "target", "ok", "duration_ms", "error", "host"},
}

HOOK_FILES = ("brain-resume.py", "brain-session.py", "serve-start.py")


def run(env, args, stdin="", cwd=None):
    return subprocess.run([sys.executable, BRAIN] + args, input=stdin, capture_output=True, text=True,
                          env=env, cwd=cwd)


def hook_literal(name):
    tree = ast.parse(open(os.path.join(ROOT, "hooks", name)).read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "HOOK" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"{name} has no HOOK literal")


def check_hooks(fails):
    reg = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))["hooks"]
    for name in HOOK_FILES:
        hook = hook_literal(name)
        command = 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/%s"' % name
        want = sorted((e["event"], e.get("matcher", ""), hook["timeout"]) for e in hook["events"])
        got = []
        for event, groups in reg.items():
            for g in groups:
                for h in g.get("hooks", []):
                    if h.get("command") == command and h.get("type") == "command":
                        got.append((event, g.get("matcher", ""), h.get("timeout")))
        if sorted(got) != want:
            fails.append(f"hooks.json for {name}: registered {sorted(got)}, HOOK says {want}")
    known = {'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/%s"' % n for n in HOOK_FILES}
    for groups in reg.values():
        for g in groups:
            for h in g.get("hooks", []):
                if h.get("command") not in known:
                    fails.append(f"hooks.json registers an unknown command: {h.get('command')}")


def check_plugin(fails):
    plugin = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
    ns = {}
    exec(open(os.path.join(ROOT, "lib", "brain", "version.py")).read(), ns)
    if ns["VERSION"] != plugin["version"]:
        fails.append(f"version.py says {ns['VERSION']}, plugin.json says {plugin['version']}")
    if plugin["name"] != "brain":
        fails.append("plugin.json name is not brain")
    if plugin.get("mcpServers", {}).get("brain", {}).get("command") != "${CLAUDE_PLUGIN_ROOT}/tools/brain-mcp":
        fails.append("plugin.json mcpServers.brain does not point at tools/brain-mcp")
    for key in ("serve_mode", "worktree_roots"):
        if key not in plugin.get("userConfig", {}):
            fails.append(f"plugin.json userConfig lacks {key}")
    market = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))
    if market["name"] != "brain" or [p["name"] for p in market["plugins"]] != ["brain"]:
        fails.append("marketplace.json must name marketplace brain with the one plugin brain")
    return plugin["version"]


def check_calls(fails, version):
    tmp = tempfile.mkdtemp(prefix="brain-contract.")
    try:
        home = os.path.join(tmp, "home")
        work = os.path.realpath(os.path.join(tmp, "work"))
        os.makedirs(home)
        os.makedirs(work)
        env = dict(os.environ, LEAN_BRAIN_DB=os.path.join(tmp, "brain.db"), HOME=home)
        for k in ("LEAN_SESSION_ID", "LEAN_SESSION_CWD"):
            env.pop(k, None)

        def ok(label, r):
            if r.returncode != 0:
                fails.append(f"{label}: exit {r.returncode}: {r.stderr.strip()[:200]}")
                return False
            return True

        r = run(env, ["--version"])
        if ok("--version", r) and r.stdout.strip() != f"brain {version}":
            fails.append(f"--version printed {r.stdout.strip()!r}")

        r = run(env, ["add", "--project", "demo", "--repo", "r", "--branch", "b", "--kind", "question",
                      "--ref", "q1", "--title", "a title", "--cycle", "c1", "--tag", "t1", "--body-file", "-"],
                stdin="the body\nsecond line")
        ok("add with the body on stdin", r)
        run(env, ["add", "--project", "other", "--kind", "question", "--ref", "q2", "--title", "other"])

        r = run(env, ["list", "--json", "--open", "--kind", "question", "--project", "demo", "--tag", "t1",
                      "--cycle", "c1"])
        items = []
        if ok("list --json with filters", r):
            try:
                items = json.loads(r.stdout)
            except ValueError:
                fails.append("list --json did not print JSON")
        if len(items) != 1:
            fails.append(f"list --json filters returned {len(items)} items, want 1")
        else:
            missing = ITEM_KEYS - set(items[0])
            if missing:
                fails.append(f"list --json items lack {sorted(missing)}")
            elif items[0]["ref"] != "q1" or "t1" not in items[0]["tags"]:
                fails.append("list --json returned the wrong item or tags")

            r = run(env, ["close", str(items[0]["id"]), "--resolution", "answered", "--note", "done"])
            if ok("close --resolution --note", r):
                r = run(env, ["list", "--json", "--open", "--project", "demo"])
                if ok("list after close", r) and json.loads(r.stdout) != []:
                    fails.append("close left the item open")

        # The close, reopen and resume calls the extension makes (vscode/src/brainCli.ts).
        for ref in ("w1", "a1", "r1"):
            run(env, ["add", "--project", "demo", "--kind", "question", "--ref", ref, "--title", ref])
        r = run(env, ["list", "--json", "--open", "--project", "demo"])
        ids = {i["ref"]: i["id"] for i in json.loads(r.stdout)} if r.returncode == 0 else {}
        if {"w1", "a1", "r1"} - set(ids):
            fails.append(f"could not set up items for close and reopen: {r.stdout[:200]}")
        else:
            ok("close --wontfix --resolution not-a-bug",
               run(env, ["close", str(ids["w1"]), "--wontfix", "--resolution", "not-a-bug"]))
            ok("close --resolution answered --note --delivered",
               run(env, ["close", str(ids["a1"]), "--resolution", "answered", "--note", "an answer", "--delivered"]))
            ok("close --resolution fixed", run(env, ["close", str(ids["r1"]), "--resolution", "fixed"]))
            ok("reopen", run(env, ["reopen", str(ids["r1"])]))
            r = run(env, ["list", "--json", "--open", "--project", "demo"])
            if ok("list after reopen", r) and [i["ref"] for i in json.loads(r.stdout)] != ["r1"]:
                fails.append(f"after the closes and the reopen only r1 should be open: {r.stdout[:200]}")
        ok("resume", run(env, ["resume"], cwd=work))
        r = run(env, ["resume", "--project", "demo"])
        if ok("resume --project", r) and "r1" not in r.stdout:
            fails.append(f"resume --project demo should list the open item r1: {r.stdout[:200]!r}")

        r = run(env, ["notice", "add", "--hook", "contract", "--session", "s1", "--cwd", work],
                stdin="a notice")
        ok("notice add", r)
        r = run(env, ["created", "add", "--kind", "pr", "--forge", "github", "--url",
                      "https://example.com/o/r/pull/1", "--repo", "o/r", "--number", "1", "--title", "t"])
        ok("created add", r)

        r = run(env, ["session", "start", "contract-1", "--cwd", work])
        ok("session start", r)
        r = run(env, ["session", "infer", "--json"], cwd=work)
        if ok("session infer --json", r):
            try:
                got = json.loads(r.stdout)
            except ValueError:
                got = {}
            if set(got) != {"id", "cwd"} or got.get("id") != "contract-1":
                fails.append(f"session infer --json printed {r.stdout.strip()!r}")
        r = run(env, ["session", "infer", "--json"], cwd=tmp)
        if ok("session infer --json with no session", r) and json.loads(r.stdout) != {"id": "", "cwd": ""}:
            fails.append(f"session infer --json with none printed {r.stdout.strip()!r}")

        r = run(env, ["activity", "add", "--source", "contract", "--action", "check"])
        ok("activity add", r)

        con = sqlite3.connect(env["LEAN_BRAIN_DB"])
        for table, cols in EXTENSION_READS.items():
            have = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
            if not have:
                fails.append(f"brain.db has no table {table}")
            elif cols - have:
                fails.append(f"brain.db table {table} lacks {sorted(cols - have)}")
        row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not row:
            fails.append("brain.db meta has no schema_version")
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_validate(fails):
    claude = shutil.which("claude")
    if not claude:
        return
    r = subprocess.run([claude, "plugin", "validate", "."], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        fails.append(f"claude plugin validate: exit {r.returncode}: {(r.stdout + r.stderr).strip()[:300]}")


def check_validate_skips(fails):
    """With no claude on PATH, check_validate says so instead of passing in silence."""
    import contextlib
    import io
    saved = os.environ.get("PATH", "")
    out = io.StringIO()
    os.environ["PATH"] = tempfile.mkdtemp()
    try:
        with contextlib.redirect_stdout(out):
            check_validate([])
    finally:
        os.environ["PATH"] = saved
    if "skipped: claude not on PATH, plugin validate not run" not in out.getvalue():
        fails.append(f"check_validate must print its skip line when claude is not on PATH: {out.getvalue()!r}")


def self_test():
    fails = []
    check_validate_skips(fails)
    version = check_plugin(fails)
    check_hooks(fails)
    check_calls(fails, version)
    check_validate(fails)
    for f in fails:
        print("FAIL", f)
    if not fails:
        print("contract: ok")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
    sys.exit(2)
