import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parents[1]))

from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse

from engine.store import TraceStore

app = FastAPI(title="TRACE Dashboard", version="0.1.0")


def get_store() -> TraceStore:
    store = TraceStore.default()
    store.init_db()
    return store


def _since(period: str) -> str | None:
    today = date.today()
    match period:
        case "today":
            return today.isoformat()
        case "week":
            return (today - timedelta(days=7)).isoformat()
        case "month":
            return (today - timedelta(days=30)).isoformat()
        case _:
            return None


@app.get("/api/projects")
def api_projects(store: TraceStore = Depends(get_store)):
    return store.list_projects()


@app.get("/api/costs")
def api_costs(
    project: str | None = None,
    period: str = "all",
    store: TraceStore = Depends(get_store),
):
    since = _since(period)
    summary = store.get_cost_summary(project_name=project, since_date=since)
    sessions = store.get_sessions_with_projects(project_name=project, since_date=since)
    return {
        "project": project or "all",
        "period": period,
        **summary,
        "sessions": sessions,
    }


@app.get("/api/summary")
def api_summary(store: TraceStore = Depends(get_store)):
    budgets = store.config.get("budgets", {})
    monthly_budget = budgets.get("default_monthly_usd", 20.0)
    alert_pct = budgets.get("alert_threshold_pct", 80)

    today_s = store.get_cost_summary(since_date=_since("today"))
    week_s = store.get_cost_summary(since_date=_since("week"))
    month_s = store.get_cost_summary(since_date=_since("month"))
    projects = store.list_projects()

    spent = month_s["total_cost_usd"]
    used_pct = round((spent / monthly_budget) * 100, 1) if monthly_budget else 0.0

    return {
        "today": today_s,
        "week": week_s,
        "month": month_s,
        "project_count": len(projects),
        "budget": {
            "monthly_usd": monthly_budget,
            "spent_usd": spent,
            "used_pct": used_pct,
            "alert_threshold_pct": alert_pct,
            "over_alert": used_pct >= alert_pct,
        },
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return _HTML


_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TRACE Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8fafc; color: #1e293b; }

    header {
      background: #0f172a;
      color: white;
      padding: 0.875rem 2rem;
      display: flex;
      align-items: center;
      gap: 1rem;
    }
    header h1 { font-size: 1rem; font-weight: 700; letter-spacing: 0.1em; }
    header span { color: #64748b; font-size: 0.8125rem; }

    main { max-width: 1200px; margin: 0 auto; padding: 2rem; }

    .cards {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 1rem;
      margin-bottom: 1.25rem;
    }
    .card {
      background: white;
      border-radius: 0.5rem;
      padding: 1.25rem 1.5rem;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .card .label {
      font-size: 0.7rem;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 0.5rem;
    }
    .card .value {
      font-size: 1.625rem;
      font-weight: 700;
      color: #0f172a;
      font-variant-numeric: tabular-nums;
    }
    .card .sub { font-size: 0.78rem; color: #94a3b8; margin-top: 0.3rem; }

    .budget-section {
      background: white;
      border-radius: 0.5rem;
      padding: 1rem 1.5rem;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      margin-bottom: 1.25rem;
    }
    .budget-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.625rem;
    }
    .budget-header .label { font-size: 0.8125rem; font-weight: 600; color: #374151; }
    .budget-header .amount { font-size: 0.8125rem; color: #64748b; font-variant-numeric: tabular-nums; }
    .budget-bar { height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; }
    .budget-fill { height: 100%; border-radius: 3px; transition: width 0.4s ease; }
    .budget-fill.safe { background: #22c55e; }
    .budget-fill.warn { background: #f59e0b; }
    .budget-fill.over { background: #ef4444; }

    .controls {
      display: flex;
      gap: 0.75rem;
      margin-bottom: 1rem;
      align-items: center;
    }
    .controls label { font-size: 0.8125rem; color: #64748b; }
    .controls select {
      padding: 0.4rem 0.75rem;
      border: 1px solid #e2e8f0;
      border-radius: 0.375rem;
      font-size: 0.8125rem;
      background: white;
      color: #1e293b;
      cursor: pointer;
      outline: none;
    }
    .controls select:focus { border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,0.15); }

    .table-section {
      background: white;
      border-radius: 0.5rem;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      overflow: hidden;
    }
    .table-header {
      padding: 0.875rem 1.25rem;
      font-size: 0.8125rem;
      font-weight: 600;
      color: #374151;
      border-bottom: 1px solid #f1f5f9;
    }
    table { width: 100%; border-collapse: collapse; }
    th {
      text-align: left;
      padding: 0.625rem 1rem;
      font-size: 0.7rem;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      background: #f8fafc;
      border-bottom: 1px solid #e2e8f0;
    }
    td { padding: 0.7rem 1rem; font-size: 0.8125rem; border-bottom: 1px solid #f8fafc; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #fafafa; }
    .cost { font-weight: 600; color: #0f172a; font-variant-numeric: tabular-nums; }
    .model { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.75rem; color: #6366f1; }
    .project-name { font-weight: 500; }
    .notes { color: #94a3b8; font-size: 0.75rem; }
    .empty { text-align: center; color: #94a3b8; padding: 3rem; font-size: 0.875rem; }
  </style>
</head>
<body>
  <header>
    <h1>TRACE</h1>
    <span>Token-aware Realtime AI Context Engine</span>
  </header>

  <main>
    <div class="cards">
      <div class="card">
        <div class="label">Today</div>
        <div class="value" id="today-cost">–</div>
        <div class="sub" id="today-sessions"></div>
      </div>
      <div class="card">
        <div class="label">This Week</div>
        <div class="value" id="week-cost">–</div>
        <div class="sub" id="week-sessions"></div>
      </div>
      <div class="card">
        <div class="label">This Month</div>
        <div class="value" id="month-cost">–</div>
        <div class="sub" id="month-sessions"></div>
      </div>
      <div class="card">
        <div class="label">Projects</div>
        <div class="value" id="project-count">–</div>
      </div>
    </div>

    <div class="budget-section">
      <div class="budget-header">
        <span class="label">Monthly Budget</span>
        <span class="amount" id="budget-label">–</span>
      </div>
      <div class="budget-bar">
        <div class="budget-fill safe" id="budget-fill" style="width:0%"></div>
      </div>
    </div>

    <div class="controls">
      <label>Project</label>
      <select id="project-select" onchange="loadSessions()">
        <option value="">All Projects</option>
      </select>
      <label>Period</label>
      <select id="period-select" onchange="loadSessions()">
        <option value="all">All Time</option>
        <option value="today">Today</option>
        <option value="week">This Week</option>
        <option value="month">This Month</option>
      </select>
    </div>

    <div class="table-section">
      <div class="table-header">Sessions</div>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Project</th>
            <th>Model</th>
            <th>Input Tokens</th>
            <th>Output Tokens</th>
            <th>Cost</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody id="sessions-body">
          <tr><td colspan="7" class="empty">Loading…</td></tr>
        </tbody>
      </table>
    </div>
  </main>

  <script>
    const $ = id => document.getElementById(id);
    const fmt = usd => '$' + usd.toFixed(4);
    const plural = (n, w) => n + '\u202f' + (n === 1 ? w : w + 's');

    async function loadSummary() {
      const data = await fetch('/api/summary').then(r => r.json());

      $('today-cost').textContent = fmt(data.today.total_cost_usd);
      $('today-sessions').textContent = plural(data.today.session_count, 'session');
      $('week-cost').textContent = fmt(data.week.total_cost_usd);
      $('week-sessions').textContent = plural(data.week.session_count, 'session');
      $('month-cost').textContent = fmt(data.month.total_cost_usd);
      $('month-sessions').textContent = plural(data.month.session_count, 'session');
      $('project-count').textContent = data.project_count;

      const b = data.budget;
      $('budget-label').textContent =
        '$' + b.spent_usd.toFixed(2) + ' / $' + b.monthly_usd.toFixed(2) +
        '  (' + b.used_pct + '%)';

      const fill = $('budget-fill');
      fill.style.width = Math.min(b.used_pct, 100) + '%';
      const cls = b.over_alert ? 'over'
                : b.used_pct >= b.alert_threshold_pct * 0.75 ? 'warn'
                : 'safe';
      fill.className = 'budget-fill ' + cls;
    }

    async function loadProjects() {
      const projects = await fetch('/api/projects').then(r => r.json());
      const sel = $('project-select');
      projects.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.name;
        opt.textContent = p.name;
        sel.appendChild(opt);
      });
    }

    async function loadSessions() {
      const project = $('project-select').value;
      const period  = $('period-select').value;
      const params  = new URLSearchParams({ period });
      if (project) params.set('project', project);

      const data = await fetch('/api/costs?' + params).then(r => r.json());
      const tbody = $('sessions-body');

      if (!data.sessions.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty">No sessions found.</td></tr>';
        return;
      }

      tbody.innerHTML = data.sessions.map(s => `
        <tr>
          <td>${s.date}</td>
          <td class="project-name">${s.project_name || '–'}</td>
          <td><span class="model">${s.model}</span></td>
          <td>${s.input_tokens.toLocaleString()}</td>
          <td>${s.output_tokens.toLocaleString()}</td>
          <td class="cost">${fmt(s.cost_usd)}</td>
          <td class="notes">${s.notes || ''}</td>
        </tr>
      `).join('');
    }

    loadSummary();
    loadProjects();
    loadSessions();
  </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7070)
