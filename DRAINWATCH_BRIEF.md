# Drain Watch: build brief

Read this file fully before writing code. It is the source of truth for the project.
Reference screenshots are pasted separately in the chat. Match their look (see section 5).

## 0. How to work
1. Do not write code yet. First show the proposed file structure and the shared data models (section 7), then wait for approval.
2. Build in the order in section 13. Commit after each milestone with a clear message.
3. Keep every module small and typed. Prefer clear code over clever code.
4. Ask before adding any dependency that is not listed in section 3.

## 1. Context and constraints
- Event: PySustain-2026 Python hackathon, Track 2 (water management and sanitation).
- **Python only.** No hand-written JavaScript frontend. Styling is done with Tailwind classes and a small CSS file served by the app (confirm with the team that custom CSS is allowed).
- Time: 3 to 6 hours of build time. Scope accordingly (see section 13).
- Team: 4 people working in parallel on one GitHub repo, each owning separate files (section 12).
- Delivery: a live demo plus the GitHub repo. The repo must run with one command.
- Priority: **a polished, high-tech UI**. Spend effort there first.

## 2. Product
Drain Watch is a decision-support web app for municipal drainage teams. During heavy rain it ranks drains by **inspection priority** and explains each rank.

It compares each drain's water-level behaviour with its own normal behaviour and with nearby drains, and combines that with blockage reports and inspection history.

Important honesty rules, shown in the app and README:
- All data is simulated. The app demonstrates a prioritisation method.
- It does **not** predict floods and does **not** confirm that a drain is blocked. It tells crews where to look first.

### Users and login
A login screen with demo accounts (demo-grade only, no real security, say so in the README):
- `operator` : control-room operator. Sees the full dashboard, map, board, work orders, analytics.
- `crew` : field crew member. Sees assigned tasks, task detail with checklist and photo upload, and a report form. Layout works on a phone-sized screen.
Show the demo credentials on the login screen so judges can sign in quickly.

## 3. Tech stack (all Python)
- UI: **NiceGUI** (Quasar components + Tailwind classes). Use `ui.dark_mode`, `ui.echart`, `ui.leaflet`, `ui.aggrid`, drawers, tabs, dialogs, timers for live updates.
- Backend: FastAPI (runs underneath NiceGUI). Add small `/api` routes for reports and readings.
- Data: SQLModel + SQLite. Pydantic models.
- Analysis: pandas, numpy, scipy, scikit-learn (robust statistics), networkx (drain network graph).
- Maps: Leaflet with a dark tile layer and a light tile layer that swap with the theme. Internet is needed at the venue for tiles. Add a plain offline fallback style.
- Charts: Apache ECharts through `ui.echart`. Register one dark and one light ECharts theme.
- Quality: `uv` for environment, `ruff` for lint and format, `pytest` for the scoring and simulator tests.
- Fonts: self-host the font files in `static/fonts` so the demo does not depend on the network.

## 4. City and data (fictional)
- Invent a fictional city with 4 zones and invented street names. Suggested city name: Rivermere (change freely). Do not use real place names.
- About **150 drains** in a connected network. Each drain has a downstream drain, forming a tree that ends at an outfall (river or lake). Build it as a networkx DiGraph.
- Drain fields: id (like D-018), zone, lat/lon, elevation, capacity, catchment size, silt-prone flag, last inspection date, past blockage count, has_sensor.
- Only about 60 percent of drains have a water-level sensor. The rest rely on reports and history, and show lower confidence.

## 5. Design system
Follow the pasted references exactly where they set direction:
- **Dark mode:** neon control-room look (smart-drainage big screen and Everbridge alert board).
- **Light mode:** clean municipal dashboard (teal sidebar, white KPI cards, light map).
Layout and components are the same in both themes. Only the tokens change.

### Tokens (approximate, sample real values from the reference images)
| Token | Dark | Light |
|---|---|---|
| Page background | deep navy `#060B1E` | cool off-white `#F2F6F9` |
| Panel | translucent navy `#0B1533` with thin cyan border | white `#FFFFFF` with soft border |
| Sidebar | near-black navy `#050A18` | deep teal `#0F2B36` |
| Primary accent | electric cyan `#22D3EE` | teal `#14A38B` |
| Text / muted text | `#E6EEFF` / `#8BA3C7` | `#0F2230` / `#5B6B7A` |
| Critical / High / Medium / Healthy | `#FF4D4F` / `#FF8A1F` / `#FBBF24` / `#2DD4A0` | slightly deeper versions of the same hues |
| Info | `#4C8DFF` | `#3B82F6` |

Implement tokens as CSS variables on the page root. Theme toggle flips the variables, the ECharts theme and the map tiles together. It follows the system setting by default and remembers the user's choice.

### Type
- Headings, KPI numbers: **Saira Semi Condensed** (tabular numerals).
- Body, tables, forms: **Public Sans**.
- Sentence case everywhere. Do not add small all-caps labels above headings. Do not use monospace for ordinary labels.

### Principles
- Spend the boldness in one place: the **drain network map**. In dark mode the network lines glow, flow direction is animated slowly, and critical drains pulse. Keep everything around it quiet and disciplined.
- One border radius scale and one shadow scale. Hierarchy comes from spacing and size, not identical cards.
- Corner-bracket HUD framing only on the main map panel and the wall screen. Do not decorate every panel.
- Motion: pulse on critical markers, smooth open and close of the detail drawer, number count-up on first load only. Respect reduced-motion.
- Severity is never colour alone. Always add an icon and a text label.
- Visible keyboard focus, accessible contrast in both themes, usable down to phone width.
- Plain, action-led copy. Buttons say what happens ("Assign crew", "Mark as cleared"). Empty states tell the user what to do next.

## 6. Screens
### Operator
1. **Overview:** greeting and date, KPI strip (drains monitored, critical alerts, likely blocked, inspections today with target), drain network map, priority alerts feed, rainfall and forecast strip, sensor health rings (Normal / Warning / Alarm split with counts by sensor type), recent field reports table.
2. **Priority board:** columns Critical, High, Medium, Low (like the Everbridge reference), with counts, drain cards, filters (zone, status, type), and list-view toggle.
3. **Drain detail drawer** (opens from board, map or table): header with drain ID, zone, status badge, owner. Tabs: Details, Readings, Reports, History.
   - Details: priority score, a bar chart of what contributed to the score, a plain-language reason, a confidence score, and the classification label.
   - Readings: observed level against expected level, with rainfall overlay.
   - Reports: nearby reports and photos.
   - History: inspections, status changes, audit log.
4. **Drain map:** full-screen map, layers (priority, sensor health, flow direction, zones), click for the drawer.
5. **Work orders:** kanban (Pending, Assigned, In progress, Cleared) with drag and drop, with a "Move to" menu as the fallback. SLA countdown on each card.
6. **Crew planner:** inputs for number of crews and inspections per shift. Output is an ordered assignment by priority and proximity, shown on the map.
7. **Analytics:** validation panel (see section 9), impact summary, rainfall versus alerts chart.
8. **Storm control panel** (collapsible bar): scenario select (Light rain, Heavy storm, Cloudburst), intensity slider, play, pause, speed, reset. Drives the whole app live.
9. **Control room wall mode** (stretch goal): full-screen auto-refreshing view in the style of the big-screen reference.

### Field crew
1. **My tasks:** assigned drains sorted by priority, distance, SLA timer.
2. **Task detail:** map pin, why it was flagged, checklist (inspect inlet, clear debris, check outflow, photo before, photo after), status buttons, notes. Photo upload with `ui.upload`.
3. **Report a blockage:** drain picker or map pin, issue type, severity, optional photo. Submitting updates rankings live.
Mark these screens clearly as phone-friendly.

### Shared
- Login screen, theme toggle, notification bell, search for drains and reports, sign out.
- An about and method page: how scoring works, data is simulated, limits of the tool.

## 7. Data models (SQLModel)
Define these first and share them with the whole team: `Zone`, `Drain`, `SensorReading` (drain_id, ts, level_cm), `RainObservation` (ts, mm_per_10min), `Report` (id, drain_id, ts, type, severity, photo_path, source), `WorkOrder` (id, drain_id, status, assignee, created, due, notes), `InspectionRecord` (drain_id, ts, outcome), `User` (username, role, display_name), `Crew`, `AuditEvent`.

## 8. Simulator
- Time step: 10 minutes. A scenario is about 6 hours (36 steps). Playback is compressed (for example 1 step per second) and adjustable.
- Rainfall profiles: light rain, heavy storm, cloudburst.
- Water level per drain: rises with rain times catchment, falls with an outflow coefficient, plus noise. Baseline ("normal behaviour") comes from a dry-run storm with no blockages.
- Hidden ground truth, stored separately and never shown in the normal UI:
  - about 10 drains with a local blockage (reduced outflow)
  - 1 downstream congestion event at a trunk junction affecting about 12 upstream drains
  - 3 faulty sensors (stuck or dropout)
- Reports: blocked drains get a report with probability about 0.5 within 30 to 90 minutes of onset. Add about 8 false reports and some duplicates.
- Use a fixed random seed so the demo is repeatable. Provide a "new random city" option as a stretch goal.

## 9. Scoring engine (pure functions, fully tested)
For each drain at time t compute these signals, each scaled 0 to 1:
1. **Anomaly:** (observed minus expected level for the rainfall so far) divided by the drain's normal spread. Clip to 0..4 then scale.
2. **Persistence:** how long the level stays high after rain eases.
3. **Neighbour context:** share of nearby drains (about 300 m, plus upstream and downstream in the graph) that are also anomalous.
4. **Report corroboration:** recency-weighted reports within about 75 m, capped.
5. **History:** days since last inspection, past blockages, silt-prone.
6. **Consequence:** low elevation, zone importance, nearby critical sites (underpass, hospital, school).

Weights to start with: anomaly 35, persistence 15, reports 20, history 15, consequence 15. Multiply by 1.2 (cap at 100) when reports and sensor signals agree. Keep weights in one config object so they can be tuned.

Classification label:
- High anomaly, normal neighbours: **Likely local blockage**
- Many nearby drains high: **Possible downstream congestion or widespread flooding** (different crew action)
- Report only, no sensor support: **Unverified report**
- No sensor on this drain: lower confidence and say why

Bands: Critical 75 or more, High 55 to 74, Medium 35 to 54, Low below 35.
Explanation text is generated from the top three contributing signals in plain language.
Confidence depends on sensor availability, data freshness and corroboration.

Validation panel: compare the top 10 and top 20 ranked drains with the hidden ground truth. Show precision at 10, recall at 20, and a random-ranking baseline. Label it clearly: "Simulated data. Shows how the method behaves, not real-world accuracy."

## 10. Live behaviour
- The storm control drives a timer that advances the simulation. Pages update through NiceGUI timers and binding.
- A new report or a status change triggers a rescore and updates board, map, KPIs and feed without a page reload.
- Clearing a work order records an inspection and lowers that drain's priority.

## 11. Folder structure
```
DrainWatch-by-Error404/
  app.py                  # entry point, routes, theme setup
  static/                 # fonts, css, icons, demo photos
  drainwatch/
    models.py             # SQLModel tables and schemas
    db.py                 # engine and session helpers
    simulate.py           # city, drains, rain, readings, reports, ground truth
    scoring.py            # signals, weights, labels, explanations
    network.py            # networkx graph and neighbour logic
    allocation.py         # crew planner
    service.py            # functions the UI calls (single data access layer)
    auth.py               # demo login
    theme.py              # tokens, dark and light, echart themes, map tiles
  ui/
    layout.py             # shell, sidebar, header, theme toggle
    components.py         # KPI card, drain card, badge, gauge, feed item
    pages/                # overview, board, map, workorders, planner, analytics, crew, report, about
  tests/                  # scoring, simulator, allocation tests
  README.md
  CLAUDE.md
  pyproject.toml
```
Rule: UI files call only `service.py`. The UI never touches the database or scoring directly.

## 12. Team split (4 people) and git workflow
- Person A, engine: `simulate.py`, `scoring.py`, `network.py`, tests.
- Person B, shell and design: `theme.py`, `layout.py`, `auth.py`, `components.py`, overview page.
- Person C, operator views: board, drawer, map, charts.
- Person D, workflow: crew pages, report form, work orders, planner, README, demo script.

Workflow:
1. One person builds the skeleton first: models, `service.py` function signatures, and fake sample data. Push to `main` within the first 45 minutes.
2. Everyone then works on their own branch (`feature/<part>`), commits small and often, and merges into `main` through pull requests.
3. Nobody edits another person's files without telling them.

## 13. Build order (about 5 hours)
1. 45 min: skeleton, models, `service.py` stubs, theme tokens, shell with sidebar, login, theme toggle.
2. 60 min: simulator and scoring engine with tests (parallel with step 3).
3. 90 min: overview, map, board, drain drawer.
4. 60 min: report form, work orders, crew pages, storm control, live updates.
5. 45 min: crew planner, validation panel, polish in both themes.
6. 30 min: README, screenshots, demo rehearsal.

Must have: steps 1 to 4. Should have: crew planner, validation panel. Stretch: wall mode, flow animation, command palette, PDF briefing, sanitation-risk layer.

## 14. Demo script (3 minutes)
1. Sign in as operator. State the problem in one sentence.
2. Start the Cloudburst scenario and watch the board and map fill.
3. Open the top drain. Show the reason, the score contributions and the confidence.
4. Submit a report as crew and watch the priority rise.
5. Use the crew planner to assign work orders.
6. Show the validation panel and the limits statement.
7. Toggle light and dark mode.

## 15. Definition of done
- `uv run app.py` starts the app and both demo logins work.
- Both themes look intentional on every screen.
- The scoring tests pass.
- README has: what it is, screenshots, how to run, demo accounts, method summary, limitations, team.
- No secrets in the repo. Demo credentials are labelled as demo only.

## 16. Open items to confirm with the team
- Is custom CSS allowed under the Python-only rule?
- Wall mode: include it or cut it?
- Final city name and zone names.
- Map tiles provider and offline fallback.
