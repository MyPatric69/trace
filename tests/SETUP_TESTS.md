# TRACE Install Script – Manual Verification

`install.sh` uses shell features and LaunchAgents that cannot be unit-tested
with pytest. Verify each mode manually before releasing.

---

## Prerequisites

```bash
# These must pass before running any mode
python3 --version   # ≥ 3.10
git --version
pip3 --version
```

---

## Mode 1 – Fresh install

**Setup:** `~/.trace/user_config.yaml` must NOT exist.

```bash
# Simulate clean state (back up first if needed)
mv ~/.trace ~/.trace.bak

cd /path/to/trace
bash install.sh
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

**Idempotency check:** Run `bash install.sh` a second time – no errors, no
duplicate entries in `~/.claude/settings.json`.

---

## Mode 1 variant – Fresh install from a project directory

**Setup:** clean state (`~/.trace` removed) AND run from a non-TRACE project.

```bash
mv ~/.trace ~/.trace.bak
cd /path/to/some-other-project   # must have .git or CLAUDE.md
bash /path/to/trace/install.sh
```

**Expected (in addition to Mode 1 above):**
- `→ Registering project '<dirname>'...` printed
- Project appears in `python3 -c "from engine.store import TraceStore; print([p['name'] for p in TraceStore.default().list_projects()])"`
- `.git/hooks/post-commit` created in the project directory (if it is a git repo)

---

## Mode 2 – Add project

**Setup:** TRACE already installed, run from a project directory.

```bash
cd /path/to/another-project   # has .git or CLAUDE.md
bash /path/to/trace/install.sh
```

**Expected:**
- `TRACE vX.X.X – Add project` header
- `→ Verifying Claude Code hooks (idempotent)...` (no duplicate hooks added)
- `→ Registering project '<dirname>'...`
- Project appears in `list_projects()` output
- If `.git` exists and no `post-commit` hook was there: hook now installed
- Final: `✅ Project '<name>' added to TRACE`

**Edge case – not a project:**

```bash
cd /tmp
bash /path/to/trace/install.sh
```

Expected: `⚠️` warning and exit 1 (no .git or CLAUDE.md found).

**Idempotency:** Run twice from the same project – second run prints
`Already registered: <name>` and `Git hook already installed`, exits cleanly.

---

## Mode 3 – Update (via menu)

**Setup:** TRACE installed, run from the TRACE repo directory.

```bash
cd /path/to/trace
bash install.sh
# Select: 2) Update TRACE to latest version
```

**Expected:**
- `→ Pulling latest changes...` (git pull runs)
- `✅ Dependencies updated`
- `→ Reloading LaunchAgents...` with `Reloaded: com.trace.dashboard` and
  `Reloaded: com.trace.tokenizer`
- Final: `✅ TRACE updated to latest version`
- `~/.trace/user_config.yaml` unchanged

---

## Menu – installed + TRACE repo

**Setup:** TRACE installed, run from the TRACE repo.

```bash
cd /path/to/trace
bash install.sh
```

**Expected:**
- `TRACE vX.X.X is already installed.` printed
- Menu with options 1–4 displayed
- Each option routes to the correct mode
- Option 4 exits cleanly with code 0

---

## Full reinstall (menu option 3)

**Setup:** TRACE installed with existing `~/.trace/user_config.yaml`.

```bash
cd /path/to/trace
bash install.sh
# Select: 3) Full reinstall (preserves user settings)
```

**Expected:**
- Existing `user_config.yaml` content survives reinstall
- LaunchAgents reloaded
- Final: `✅ TRACE reinstalled`

---

## Automated test

No pytest tests for install.sh. After running any mode, verify that
the full test suite still passes:

```bash
cd /path/to/trace
pytest tests/ -v
```

All 569 tests should be green.
