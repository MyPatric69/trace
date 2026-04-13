# Frontend Health State Persistence Tests

These tests verify that the Session Health indicator remains persistent across page refreshes and session state changes.

## Prerequisites

1. Start the dashboard: `bash dashboard/start.sh`
2. Have a project with active Claude Code sessions
3. Open browser DevTools Console to monitor state

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

If tests fail, check browser console for:
- `lastHealthState` variable value (should be null or `{status, tokens, warnAt, resetAt, project}`)
- Network tab: `/api/live` responses include `health`, `warn_at`, `reset_at` fields
- Health bar DOM element visibility and class names

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

---

**Last updated:** 2026-04-13
