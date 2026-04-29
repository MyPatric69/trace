# TRACE Setup Script – Manual Verification

`trace.sh` uses shell features and LaunchAgents that cannot be unit-tested
with pytest. Verify each option manually before releasing.

---

## Prerequisites

```bash
# These must pass before running any option
python3 --version   # ≥ 3.10
git --version
pip3 --version
```

---

## Header (always shown)

```bash
cd /path/to/trace
bash trace.sh
```

**Expected:**
- Box drawn with `╔ ╝ ║` characters
- Version read from `trace_config.yaml` (e.g. `TRACE Manager v0.2.0`)
- Subtitle: `Token-Aware AI Context Engine`
- Menu with options 1–6 displayed
- Auto-detected option highlighted in green with `→` marker

---

## Option 1 – Install TRACE

**Setup:** `~/.trace/user_config.yaml` must NOT exist.

```bash
# Simulate clean state (back up first if needed)
mv ~/.trace ~/.trace.bak

cd /path/to/trace
bash trace.sh
# Press Enter to accept auto-selected option 1
```

**Expected:**
- `→ Checking prerequisites...` then `✅ Prerequisites satisfied`
- API key check: `✅` if stored in Keychain, `⚠️` with instructions if missing
- `✅ Dependencies installed`
- `✅ TRACE initialized at ~/.trace/`
- `~/.trace/trace.db` created
- `~/.trace/user_config.yaml` created
- `~/.trace/trace_config.yaml` created (legacy compat copy)
- TRACE SessionEnd + Stop hooks present in `~/.claude/settings.json`
- `com.trace.dashboard` LaunchAgent loaded: `launchctl list | grep trace.dashboard`
- `com.trace.tokenizer` LaunchAgent loaded: `launchctl list | grep trace.tokenizer`
- Final: `✅ TRACE installed successfully` with dashboard URL

**Idempotency check:** Run `bash trace.sh` a second time – no errors, no
duplicate entries in `~/.claude/settings.json`.

---

## Option 1 variant – Fresh install from a project directory

**Setup:** clean state (`~/.trace` removed) AND run from a non-TRACE project.

```bash
mv ~/.trace ~/.trace.bak
cd /path/to/some-other-project   # must have .git or CLAUDE.md
bash /path/to/trace/trace.sh
# Select option 1
```

**Expected (in addition to Option 1 above):**
- `→ Registering project '<dirname>'...` printed
- Project appears in `python3 -c "from engine.store import TraceStore; print([p['name'] for p in TraceStore.default().list_projects()])"`
- `.git/hooks/post-commit` created in the project directory (if it is a git repo)

---

## Option 2 – Add project

**Setup:** TRACE already installed, run from a project directory.

```bash
cd /path/to/another-project   # has .git or CLAUDE.md
bash /path/to/trace/trace.sh
# Option 2 is auto-selected; press Enter
```

**Expected:**
- `Option 2 – Add project to TRACE` header printed
- `→ Verifying Claude Code hooks (idempotent)...` (no duplicate hooks added)
- `→ Registering project '<dirname>'...`
- Project appears in `list_projects()` output
- If `.git` exists and no `post-commit` hook was there: hook now installed
- Final: `✅ Project '<name>' added to TRACE`

**Edge case – not a project:**

```bash
cd /tmp
bash /path/to/trace/trace.sh
# Select option 2
```

Expected: `⚠️` warning and exit 1 (no .git or CLAUDE.md found).

**Idempotency:** Run twice from the same project – second run prints
`Already registered: <name>` and `Git hook already installed`, exits cleanly.

---

## Option 3 – Update TRACE

**Setup:** TRACE installed, run from the TRACE repo directory.

```bash
cd /path/to/trace
bash trace.sh
# Option 3 is auto-selected; press Enter
```

**Expected:**
- Description line: `git pull + pip install + reload LaunchAgents – user data untouched`
- `→ Pulling latest changes...` (git pull output shown)
- `✅ Dependencies updated`
- `→ Reloading LaunchAgents...` with `Reloaded: com.trace.dashboard` and
  `Reloaded: com.trace.tokenizer` (or warning if not installed)
- If already on latest: `✅ Already on latest version (vX.X.X)`
- If updated: `✅ Updated from vX.X.X to vY.Y.Y – user data preserved`
- `~/.trace/user_config.yaml` unchanged after update

---

## Option 4 – Remove project

**Setup:** TRACE installed, run from a registered project directory.

```bash
cd /path/to/registered-project
bash /path/to/trace/trace.sh
# Select option 4
```

**Expected:**
- Description line: `Removes hook from a project and unregisters it from TRACE`
- Project name and path displayed
- Confirmation prompt: `Remove TRACE from '<name>'? [y/N]`
- On `y`: git hook removed, project unregistered from DB
- Final: `✅ TRACE removed from '<name>'`
- Note: `Session data in trace.db is preserved`
- On `N` or Enter: `Cancelled.` and exit 0

**Verify:**
```bash
ls /path/to/registered-project/.git/hooks/post-commit   # should not exist
python3 -c "from engine.store import TraceStore; print([p['name'] for p in TraceStore.default().list_projects()])"
# project name should be absent
```

---

## Option 5 – Uninstall TRACE

**Setup:** TRACE installed with LaunchAgents, registered projects, and MCP entry.

```bash
cd /path/to/trace
bash trace.sh
# Select option 5
```

**Expected:**
- Description line: `Removes all LaunchAgents, MCP entry, ~/.trace/ – asks for confirmation`
- Warning box listing all items that will be removed
- Confirmation prompt: `Type 'uninstall' to confirm:`
- On wrong input: `Cancelled.` and exit 0
- On `uninstall`:
  - Git hooks removed from all registered projects
  - `com.trace.dashboard` and `com.trace.tokenizer` LaunchAgents unloaded and plists deleted
  - `trace` entry removed from `~/Library/Application Support/Claude/claude_desktop_config.json`
  - TRACE hooks removed from `~/.claude/settings.json`
  - `~/.trace/` directory deleted
  - Final: `✅ TRACE uninstalled. Your repo is still at <path>`

**Verify:**
```bash
ls ~/.trace/                             # should not exist
launchctl list | grep trace              # no entries
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json | python3 -m json.tool | grep trace
# should be empty
ls /path/to/registered-project/.git/hooks/post-commit   # should not exist
```

---

## Option 6 – Exit

```bash
bash /path/to/trace/trace.sh
# Select option 6
```

**Expected:** `Bye.` printed, exit code 0.

---

## Automated test

No pytest tests for trace.sh. After running any option, verify that
the full test suite still passes:

```bash
cd /path/to/trace
pytest tests/ -v
```

All 569 tests should be green.
