# Troubleshooting

Common issues and their solutions when setting up
and running TRACE.

---

## Issue 1: Project shows X commits behind in dashboard

**Symptom:**
Dashboard shows a project with many commits behind
(e.g. "287 commits behind") even though the project
is up to date.

**Cause:**
`.trace_sync` file is missing in the project root.
TRACE uses this file as a bookmark for the last
synced commit. Without it, TRACE counts all commits
from the beginning of the repository.

**Fix:**
```bash
cd /path/to/your/project
git rev-parse HEAD > .trace_sync
```

Then reload the dashboard – the counter should reset to 0.

---

## Issue 2: Project not showing in dashboard

**Symptom:**
A project exists locally but does not appear
in the TRACE dashboard or project selector.

**Cause:**
The project has not been registered in
`~/.trace/trace.db`.

**Fix:**
```python
python3 -c "
from engine.store import TraceStore
store = TraceStore.default()
store.add_project(
    'your-project-name',
    '/path/to/your/project',
    'Short description'
)
print('Registered.')
"
```

Then install the hook:
```bash
bash hooks/install_hook.sh /path/to/your/project
```

---

## Issue 3: UNIQUE constraint failed: projects.name

**Symptom:**
```
sqlite3.IntegrityError: UNIQUE constraint failed: projects.name
```

**Cause:**
The project name is already registered in the DB.
This typically happens when using a placeholder name
like "projekt-name" that was already added.

**Fix – check what is already registered:**
```python
python3 -c "
from engine.store import TraceStore
for p in TraceStore.default().list_projects():
    print(f'  - {p[\"name\"]}  →  {p[\"path\"]}')
"
```

If the name is wrong, rename it:
```python
python3 -c "
import sqlite3
from pathlib import Path
db = Path.home() / '.trace' / 'trace.db'
conn = sqlite3.connect(db)
conn.execute(
    \"UPDATE projects SET name = 'correct-name' \
      WHERE name = 'wrong-name'\"
)
conn.commit()
conn.close()
print('Fixed.')
"
```

---

## Issue 4: AI_CONTEXT.md shows as modified after every commit

**Symptom:**
After every git commit, `git status` shows:
```
modified: AI_CONTEXT.md
```

**Cause:**
This is expected behaviour – not a bug.
The TRACE post-commit hook automatically updates
`AI_CONTEXT.md` after every commit to keep it
in sync with the latest changes.

**Fix:**
Simply stage and commit the change as part
of your normal workflow:

```bash
git add AI_CONTEXT.md
git commit -m "chore: AI_CONTEXT.md auto-sync"
```

Tip: if you want to suppress this for doc-only or
chore commits, this behaviour will be configurable
in a future release.

---

## Issue 5: Dashboard shows test project names

**Symptom:**
Dashboard shows projects with names like
`test_check_drift_stale_when_be0` or `tmpXXXXX`.

**Cause:**
pytest test fixtures wrote temporary projects into
`~/.trace/trace.db`. This is fixed in TRACE v0.1.0
but may affect older installs.

**Fix – identify and remove test projects:**
```python
python3 -c "
import sqlite3
from pathlib import Path
db = Path.home() / '.trace' / 'trace.db'
conn = sqlite3.connect(db)
rows = conn.execute(
    'SELECT id, name, path FROM projects'
).fetchall()
for r in rows:
    print(r)
conn.close()
"
```

Then delete any test entries by id:
```python
python3 -c "
import sqlite3
from pathlib import Path
db = Path.home() / '.trace' / 'trace.db'
conn = sqlite3.connect(db)
conn.execute('DELETE FROM projects WHERE id = ?', (ID,))
conn.commit()
conn.close()
print('Removed.')
"
```

Replace `ID` with the actual id from the list above.

---

## Issue 6: Hook not firing after commits

**Symptom:**
`AI_CONTEXT.md` is never updated automatically.
`.trace_sync` is never updated after commits.

**Cause:**
The global git template was not installed, or the
hook is not executable.

**Fix – run the global template setup:**
```bash
bash hooks/setup_global_template.sh
```

For existing repos, install manually:
```bash
bash hooks/install_hook.sh /path/to/your/project
```

Verify the hook is executable:
```bash
ls -la /path/to/your/project/.git/hooks/post-commit
```

If not executable:
```bash
chmod +x /path/to/your/project/.git/hooks/post-commit
```

---

## Issue 7: Dashboard not starting

**Symptom:**
`bash dashboard/start.sh` fails with
`ModuleNotFoundError` or `address already in use`.

**Cause A – missing dependencies:**
```bash
pip install -r requirements.txt
```

**Cause B – port 8080 already in use:**
```bash
lsof -i :8080
kill -9 PID
```

Then restart:
```bash
bash dashboard/start.sh
```

---

## Issue 8: favicon.ico 404 in server logs

**Symptom:**
Server logs show:
```
GET /favicon.ico HTTP/1.1" 404 Not Found
```

**Cause:**
Browsers automatically request `favicon.ico`.
TRACE serves `favicon.svg` not `favicon.ico`.

**Fix:**
This is harmless – the browser tab still shows
the correct SVG icon. The 404 for `favicon.ico`
can be safely ignored.
It is resolved in TRACE v0.1.0 which serves
`/favicon.svg` and references it in `index.html`.

---

## Issue 9: Sessions not being auto-logged

**Symptom:**
Token usage is not appearing in the dashboard
after Claude Code sessions.

**Cause:**
The SessionEnd hook is not installed in
`~/.claude/settings.json`.

**Fix:**
```bash
bash hooks/setup_claude_hook.sh
```

Verify the hook is installed:
```bash
cat ~/.claude/settings.json
```

**Note – Live Session panel not updating (Desktop App):**
PostToolUse hooks do not fire reliably in Claude Code
Desktop App (known Anthropic bug #42336). TRACE uses
the Stop hook instead, which fires after every completed
Claude response. If you installed TRACE before v0.2.0,
re-run `bash hooks/setup_claude_hook.sh` to migrate
from PostToolUse to Stop automatically.

Manual fallback – log a session manually:
```python
python3 -c "
from engine.store import TraceStore
store = TraceStore.default()
store.add_session(
    'your-project',
    'claude-sonnet-4-5',
    INPUT_TOKENS,
    OUTPUT_TOKENS,
    'Manual entry'
)
"
```

---

## Issue 10: Dashboard shows old threshold values after config change

**Symptom:**
Dashboard session health bar shows old warn/reset
values after updating `trace_config.yaml`.

**Cause:**
TRACE uses two config files that must be kept in sync:
- `~/github/trace/trace_config.yaml` (development / git)
- `~/.trace/trace_config.yaml` (runtime / store)

The store always reads from `~/.trace/trace_config.yaml`.
Changes to the project config are not automatically
propagated.

**Fix:**
```bash
cp /path/to/trace/trace_config.yaml ~/.trace/trace_config.yaml
```

Then restart the dashboard:
```bash
pkill -f "uvicorn dashboard"
bash dashboard/start.sh
```

Note: this will be resolved in v0.2.0 with automatic
config sync between the project and `~/.trace/`.

---

## Issue 11: How to reset the database

Three options depending on how much you want to clear.

---

**Option A – Clear all sessions, keep projects**

Removes every session row but leaves all registered
projects intact. Use this after a testing period to
start fresh cost tracking.

```python
python3 -c "
import sqlite3
from pathlib import Path
db = Path.home() / '.trace' / 'trace.db'
conn = sqlite3.connect(db)
conn.execute('DELETE FROM sessions')
conn.commit()
conn.close()
print('All sessions deleted.')
"
```

---

**Option B – Clear sessions for one project**

```python
python3 -c "
import sqlite3
from pathlib import Path
from engine.store import TraceStore
store = TraceStore.default()
project = store.get_project('your-project-name')
if project is None:
    print('Project not found.')
else:
    db = Path.home() / '.trace' / 'trace.db'
    conn = sqlite3.connect(db)
    conn.execute('DELETE FROM sessions WHERE project_id = ?', (project['id'],))
    conn.commit()
    conn.close()
    print(f'Sessions deleted for project: {project[\"name\"]}')
"
```

Replace `your-project-name` with the actual project name.

---

**Option C – Full reset (delete DB, recreate, re-register)**

Use this to wipe everything and start completely fresh.

1. Note your registered projects first:
```python
python3 -c "
from engine.store import TraceStore
for p in TraceStore.default().list_projects():
    print(f'{p[\"name\"]}  →  {p[\"path\"]}  ({p[\"description\"]})')
"
```

2. Delete the database:
```bash
rm ~/.trace/trace.db
```

3. Re-initialise and re-register each project:
```python
python3 -c "
from engine.store import TraceStore
store = TraceStore.default()
store.init_db()
store.add_project('your-project', '/path/to/project', 'Description')
print('Done.')
"
```

4. Reinstall git hooks if needed:
```bash
bash hooks/install_hook.sh /path/to/project
```

---

## Issue 12: Anthropic Usage board shows different costs than TRACE

**Symptom:**
The Anthropic Usage dashboard shows lower costs than
TRACE, or shows zero usage for a session you just ran.

**Cause:**
The Anthropic Usage board has a **15–60 minute delay**.
It does not reflect real-time API consumption.

TRACE reads token counts directly from the Claude Code
transcript file at session end and calculates cost
locally using the prices in `trace_config.yaml`.
TRACE is the real-time source.

**Expected difference:**
- Anthropic Usage: delayed by 15–60 min, aggregated
  by billing period
- TRACE: immediate, per-session breakdown with
  cache token cost breakdown (input, cache_creation,
  cache_read, output)

**If costs differ significantly after the delay clears:**
Check that your `trace_config.yaml` model prices match
the current Anthropic pricing page. Update if needed:
```bash
# After editing trace_config.yaml:
cp trace_config.yaml ~/.trace/trace_config.yaml
```

---

## Still stuck?

Check the project status:
```python
python3 -c "
from engine.store import TraceStore
store = TraceStore.default()
print('Projects:')
for p in store.list_projects():
    print(f'  - {p[\"name\"]}  →  {p[\"path\"]}')
summary = store.get_cost_summary()
print(f'Total cost tracked: \${summary[\"total_cost_usd\"]:.4f}')
"
```

Open an issue on GitHub:
https://github.com/MyPatric69/trace/issues
