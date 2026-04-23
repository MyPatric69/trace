# Frontend Health State Persistence Tests

These tests verify that the Session Health indicator remains persistent across page refreshes and session state changes.

**UPDATE 2026-04-13:** Health state is now persisted server-side in `~/.trace/last_health.json`. The frontend no longer uses a JS variable — all state comes from `/api/live` response field `last_health`.

## Prerequisites

1. Start the dashboard: `bash dashboard/start.sh`
2. Have a project with active Claude Code sessions
3. Open browser DevTools Console to monitor `/api/live` responses

## Test 1: Health State Persists Across Full Refresh

**Goal:** Verify that yellow/red health state survives `loadAll()` full refresh cycles.

**Steps:**
1. Start a Claude Code session in a tracked project
2. Generate enough tokens to trigger warning state (>80k tokens)
3. Open dashboard at http://localhost:8080
4. Verify Session Health Bar shows **amber** (yellow)
5. Wait 120 seconds for automatic `loadAll()` refresh
6. **Expected:** Health bar remains **amber**, does not reset to green or disappear
7. Verify label reads: `{tokens} / {resetAt} tokens`

**Pass Criteria:**
- Health bar color persists across refresh
- Token count updates but color doesn't reset
- No visual "flicker" or temporary disappearance

## Test 2: Red/Yellow State Remains After Session Ends

**Goal:** Verify that warning indicators stay visible after session closes.

**Steps:**
1. Start a Claude Code session in a tracked project
2. Generate enough tokens to trigger **red** critical state (>150k tokens)
3. Verify dashboard shows Session Health Bar in **red**
4. Close the Claude Code session (or let it timeout)
5. Wait 10 seconds for live session to clear
6. **Expected:**
   - Health bar remains **visible** with red color
   - Label changes to: `{tokens} tokens – Session beendet (war rot)`
   - Live Session panel shows "No active session"

**Pass Criteria:**
- Health bar does NOT disappear when session ends
- Red/amber color persists
- Label clearly indicates session has ended

## Test 3: State Resets When New Session Starts

**Goal:** Verify that health state clears when a fresh session begins.

**Steps:**
1. Have a persisted red/yellow health state from previous session (see Test 2)
2. Verify dashboard shows: `{tokens} tokens – Session beendet (war rot/gelb)`
3. Start a **new** Claude Code session in the same project
4. Generate a few tokens (<80k, below warning threshold)
5. **Expected:**
   - Health bar updates to show current session
   - Color changes to **green** (or bar disappears if "No active session")
   - Label returns to normal: `{tokens} / {resetAt} tokens` (no "beendet" text)

**Pass Criteria:**
- Persisted warning clears when new healthy session starts
- Fresh session shows correct current state
- No stale data from previous session

## Test 4: Project Filter Respects Health State

**Goal:** Verify that persisted health state only shows for matching project.

**Steps:**
1. Have two projects: `alpha` and `beta`
2. Generate warning state (yellow/red) in project `alpha`
3. Close the session so health state persists
4. In dashboard, select project `alpha` from dropdown
5. **Expected:** Health bar shows persisted warning
6. Switch to project `beta`
7. **Expected:** Health bar shows "No active session" (no warning from alpha)

**Pass Criteria:**
- Persisted health state is project-specific
- Switching projects does not show wrong project's health

## Test 5: Manual Clear Removes Persisted State

**Goal:** Verify that clicking "clear" on Live Session panel clears health state.

**Steps:**
1. Generate a yellow/red health state
2. Close the session (persisted state remains visible)
3. Click the **"clear"** button in Live Session panel
4. **Expected:**
   - Live Session panel shows "No active session"
   - Health bar disappears or shows "No active session"
   - No persisted warning remains

**Pass Criteria:**
- Manual clear removes all persisted state
- UI resets to clean "no session" state

## Debugging Tips

If tests fail, check:
- **Browser console** Network tab: `/api/live` responses include `last_health` field when session has ended
- **Server-side:** `~/.trace/last_health.json` file contents (should exist when session was yellow/red)
- **Health bar DOM** element visibility and class names
- **Backend logs:** `~/.trace/session_logger.log` for health state write/clear events

## Expected Behavior Summary

| Session State | Health Status | UI Behavior |
|--------------|---------------|-------------|
| No session, no history | N/A | "No active session" |
| Active, <80k tokens | ok | Bar hidden or green |
| Active, 80k–150k tokens | warn | Amber bar, live updating |
| Active, >150k tokens | reset | Red bar, live updating |
| Ended, was warn | warn (persisted) | Amber bar, "Session beendet (war gelb)" |
| Ended, was reset | reset (persisted) | Red bar, "Session beendet (war rot)" |
| New session starts | ok | Clears persisted state, shows current |

## Server-Side Verification

You can manually check the server-side health state:

```bash
# View current health snapshot
cat ~/.trace/last_health.json

# Example output (session was yellow/red):
{
  "status": "warn",
  "tokens": 95000,
  "project": "trace",
  "session_id": "abc123",
  "updated_at": "2026-04-13T15:30:00"
}

# If file doesn't exist or session was green: no warning to persist
```

## Test 6: Selected Project Persists Across Page Refresh

**Goal:** Verify that project filter selection survives browser refresh.

**Steps:**
1. Open dashboard at http://localhost:8080
2. Default state: "All Projects" is selected
3. Select a specific project (e.g., "trace") from dropdown
4. Verify dashboard shows data for that project only
5. **Refresh the page (F5 or Cmd+R)**
6. **Expected:**
   - Dropdown still shows "trace" (not "All Projects")
   - Dashboard continues to show data for "trace" only
   - Session health bar (if visible) remains project-scoped

**Pass Criteria:**
- Project selection persists across refresh
- No data from other projects visible
- localStorage contains `trace_selected_project` = "trace"

## Test 7: Fallback When Stored Project No Longer Exists

**Goal:** Verify graceful fallback if stored project was deleted.

**Steps:**
1. Select a project (e.g., "test-project")
2. Verify localStorage has `trace_selected_project` = "test-project"
3. Close dashboard
4. Delete the project from the database:
   ```bash
   sqlite3 ~/.trace/trace.db "DELETE FROM projects WHERE name='test-project'"
   ```
5. Restart dashboard and open in browser
6. **Expected:**
   - Dropdown shows "All Projects" (fallback)
   - localStorage updated to `trace_selected_project` = ""
   - No errors in browser console

**Pass Criteria:**
- No crash or errors
- Automatic fallback to "All Projects"
- localStorage cleared for non-existent project

---

## Test 8: Dark Mode Applies When System Is Dark

**Goal:** Verify that auto mode follows `prefers-color-scheme: dark`.

**Steps:**
1. Open dashboard with no `trace_theme` in localStorage (or remove it)
2. Set your OS/browser to dark mode
3. **Expected:** Dashboard background becomes dark (`#1a1a1a`), text becomes light

**Pass Criteria:**
- `html` element has no `data-theme` attribute (auto mode)
- CSS `@media (prefers-color-scheme: dark)` overrides apply
- Theme toggle button reads "Auto"

---

## Test 9: Manual Override Persists After Page Refresh

**Goal:** Verify that a manually selected theme survives browser refresh.

**Steps:**
1. Open dashboard — note current theme
2. Click the **"Auto" / "○ Light" / "● Dark"** toggle button (fixed, bottom-right corner)
3. Cycle to "● Dark" (button reads "● Dark")
4. Refresh the page (F5 or Cmd+R)
5. **Expected:** Dashboard still shows in dark mode, button reads "Dark"

**Pass Criteria:**
- `localStorage.getItem('trace_theme')` === `'dark'`
- `html[data-theme]` === `'dark'`
- No flash of light theme on load (FOUC prevention script in `<head>`)
- Toggle button is visible in bottom-right corner regardless of viewport width

---

## Test 10: Auto Mode Follows System Preference

**Goal:** Verify that switching back to "Auto" re-enables system detection.

**Steps:**
1. Set theme to "Light" via toggle (button reads "Light")
2. Verify dark system preference is ignored
3. Click toggle to "Dark", then again to "Auto"
4. **Expected:** Theme now follows system preference again

**Pass Criteria:**
- Cycle order: Auto → Light → Dark → Auto
- In Auto mode, `html` has no `data-theme` attribute
- `localStorage.getItem('trace_theme')` === `'auto'`

---

---

## Test 11: Session Health Bar Visible in VS Code Simple Browser

**Goal:** Verify that the session health progress bar renders with correct dimensions inside VS Code Simple Browser (iframe).

**Background:** VS Code Simple Browser embeds the dashboard in an iframe. In this context flex-child widths can collapse to 0 and `height:100%` fills can resolve to 0 when the parent height is computed lazily, making the bar invisible.

**Fix applied (2026-04-23):**
- `.health-row` changed from `display:flex` to `display:block` with `min-height:2.5rem`
- `.health-bar-wrap` changed from `flex:1; position:relative` to `display:block; width:100%`
- `.health-bar` now has explicit `display:block; width:100%`
- `.health-fill` now uses explicit `height:8px` instead of `height:100%`

**Steps:**
1. Start dashboard: `bash dashboard/start.sh`
2. In VS Code: `Cmd+Shift+P` → "Simple Browser: Show" → `http://localhost:8080`
3. Select a project that has an active or recent session
4. **Expected:** Session health bar is visible as a coloured horizontal bar
5. Resize the VS Code panel to different widths
6. **Expected:** Bar scales correctly to panel width at all sizes

**Pass Criteria:**
- Health bar has visible height (≥ 8 px)
- Fill colour matches session state (green / amber / red)
- Bar width reflects token usage percentage
- Threshold labels ("warn at Xk", "reset at Xk") are visible below the bar
- Token count label appears below the bar
- No invisible / collapsed bar at any panel width

---

**Last updated:** 2026-04-23 (health bar iframe fix — block layout, explicit heights)
