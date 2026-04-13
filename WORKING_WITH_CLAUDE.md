# Working with Claude on TRACE

This file defines how Claude and Patric collaborate on TRACE.
Every new Claude session must read this file first.

## Communication Style

- Language: German for conversation, English for prompts and code
- Patric is a department head (not a developer by title) but thinks
  and works at engineering level
- Be direct and honest – especially when numbers don't add up
- If something is wrong: say so immediately, don't rationalize it
- No excessive explanations – get to the point
- Ask at most ONE follow-up question per response
- Never use bullet points for simple conversational answers

## How We Work Together

Claude formulates:
1. Ready-to-use prompts for Claude Code (copy-paste ready)
2. Exact commit messages in Conventional Commits format
3. Analysis of bugs before jumping to fixes
4. Honest assessment when something won't work as expected

Patric:
1. Executes prompts in Claude Code
2. Reports back the outcome (test count, summary)
3. Makes decisions on priorities and direction
4. Challenges Claude when results seem wrong

## Prompt Structure for Claude Code

Every Claude Code prompt must follow this structure:

```
Read AI_CONTEXT.md and CLAUDE.md first.

[Clear problem description]

Change 1: [filename]
[What to change and why]

Change 2: [filename]
[What to change and why]

After implementation:
[Verification step]

Run pytest tests/ -v – all tests green
Update AI_CONTEXT.md – last updated today
```

Always start with "Read AI_CONTEXT.md and CLAUDE.md first."
Never skip this – it gives Claude Code the full context.

## Commit Message Format

Always Conventional Commits:

```
feat(scope): add new feature
fix(scope): fix a bug
docs: update documentation
chore: maintenance, config, auto-sync
refactor(scope): restructure without behavior change
test(scope): add or fix tests
```

Examples from this project:

```
feat(dashboard): v0.3.0 token calculator with Anthropic countTokens API
fix(hooks): switch live tracking from PostToolUse to Stop – Desktop App compatibility
fix(transcript_parser): exclude iterations[] to prevent double-counting cache tokens
docs: add token accuracy disclaimer to README and TROUBLESHOOTING
```

## Key Decisions and Why

### Stop Hook instead of PostToolUse
PostToolUse does not fire reliably in Claude Code Desktop App.
Known Anthropic bug: github.com/anthropics/claude-code/issues/42336
We use Stop hook which fires after every completed Claude response.

### cache_read_tokens excluded from health bar total
Including cache_read_tokens in session health inflates the number
massively (50k+ per turn). Health bar uses input + cache_creation
+ output only. Cache read is shown separately for cost purposes.

### iterations[] excluded from transcript parser
The transcript JSON has two levels: top-level fields AND
iterations[] which repeat the same values.
Summing both causes ~3x double-counting.
Always read ONLY top-level fields per requestId.

### Manual provider is default
Anthropic Usage API requires Admin API key (sk-ant-admin...)
which is only available on Team/Enterprise accounts.
Most developers use "manual" provider – this is correct and expected.

### Per-Turn DB Logging via upsert_live_session()
Sessions are written to DB after every Turn (Stop hook).
On clean exit: SessionEnd hook deletes live record and writes final.
On hard shutdown: live record survives in DB with "Live – Turn N" note.

### Token accuracy ~1-2% deviation from Anthropic
Anthropic adds internal system framing tokens not exposed in transcript.
This is documented and expected. If deviation > 10%: investigate as bug.

## Known Pitfalls

1. Never sum cache tokens from both top-level AND iterations[]
2. PostToolUse hook does NOT fire in Claude Code Desktop App
3. Anthropic Admin API key ≠ standard API key
4. live_session.json shows last active project – can be stale after
   switching between Claude Code sessions
5. Dashboard must be restarted after code changes
6. trace_config.yaml changes must be synced:
   `cp trace_config.yaml ~/.trace/trace_config.yaml`
7. On fresh install: run `python3 engine/migrate.py` BEFORE dashboard
8. add_project() UNIQUE constraint = project already exists, safe to ignore

## Quality Standards

- Tests must always be green before commit
- Never rationalize a bug away – investigate immediately
- Token cost deviations > 10% vs Anthropic = bug, not "different aggregation"
- Every public-facing feature needs documentation in README
- TROUBLESHOOTING.md gets a new issue for every non-obvious problem solved
- AI_CONTEXT.md is updated after every session

## Project Context

Repo: github.com/MyPatric69/trace
Main Mac: /Users/patric/My AI Companion/github/trace
Second Mac: /Users/patric.hayna/Documents/github/trace
License: MIT
Current version: v0.3.0 (379/379 tests green)

Registered projects (both machines):
- trace
- mindtrace  
- vocabforge
- mindtrace-meeting
- ai-framework-builder (main Mac only)

## What Makes a Good Session

A good Claude session on TRACE:
- Reads AI_CONTEXT.md + CLAUDE.md + WORKING_WITH_CLAUDE.md first
- Challenges numbers that seem wrong
- Formulates complete, copy-paste ready prompts
- Catches double-counting and similar logic errors proactively
- Documents every non-obvious decision
- Keeps tests green at every step
- Ends with a committed, pushed, tagged state
