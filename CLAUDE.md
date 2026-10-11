# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Drain Watch: a NiceGUI web app (Python only) that ranks drains by inspection priority during simulated storms in a
fictional city, Rivermere. Hackathon entry for PySustain-2026 Track 2. `DRAINWATCH_BRIEF.md` is the original brief;
the team's later design document overrides it where they differ (six operator views, four-factor scoring 40/30/20/10,
fill thresholds 75/85, schematic map instead of tiles, Inter plus JetBrains Mono with Saira Semi Condensed headings).

## Commands

```bash
uv run app.py                         # start on :8080 (DRAINWATCH_OPEN_BROWSER=0, PORT=... to adjust)
DRAINWATCH_DEV=1 uv run app.py        # also exposes GET /__dev/advance?steps=N&scenario=... for testing
uv run pytest                         # all tests
uv run pytest tests/test_scoring.py::test_band_edges   # one test
uv run ruff check . && uv run ruff format .
```

`app.py` runs with `reload=False`; restart it after code changes. The SQLite file in `.data/` is rebuilt from the seed
on every start.

## Architecture

- `drainwatch/simulate.py` builds the city (150 drains on a networkx tree draining to river outfalls), plants hidden
  faults (blockages, a congested trunk junction, faulty sensors) and computes a whole 6-hour storm up front as numpy
  arrays. Expected behaviour is the same storm run with no faults. Past steps never change on re-simulation (fixed
  noise matrix), so intensity changes and crew clearances re-run the storm from the current step onward.
- `drainwatch/scoring.py` is pure functions: signals, combination, labels, confidence, explanations, sensor
  diagnostics (judged only from the sensor's own data), validation metrics. Tunables live in `drainwatch/config.py`.
- `drainwatch/service.py` is the only module the UI may call. It owns the in-memory `World` (city, faults, run, clock,
  current scores, notifications) plus SQLite records, reveals one 10-minute step per tick, rescores, and bumps a
  module-level `_version` counter on every change. `GroundTruth` is read only by `service.validation()`.
- `ui/layout.py` builds the operator shell. Each page polls `service.version()` with a timer and calls callbacks
  registered through `Page.on_live` and `Page.on_theme`. Crew pages use `crew_shell` in `ui/pages/crew.py`.
- `ui/map_view.py` draws the schematic network with ECharts (cartesian axes, markArea blocks, `lines` pipes with an
  effect for flow, `effectScatter` pulses). Live refreshes send only `series` via `run_chart_method('setOption')` so
  the viewer's zoom survives; `restyle()` does a full redraw for theme changes. The CSS container keeps a 4:3 aspect.

## Styling gotchas (NiceGUI 3 + Quasar)

- Design tokens are CSS variables in `static/css/drainwatch.css` on `body` (light) and `body.body--dark`. Chart and
  map colours mirror them in `drainwatch/theme.py`.
- Quasar's colour and display utilities (`bg-primary`, `.block`, ...) are `!important` inside a CSS layer and beat
  unlayered `!important`. Use `c.button(...)` from `ui/components.py` (passes `color=None`) instead of `ui.button`,
  use `toggle-color=dw-on toggle-text-color=dw-on-text` on toggles, and never try to override Quasar utilities.
- `ui.colors(...)` in `layout.head()` points Quasar colours at `var(--accent)` etc., so they follow the theme.
- NiceGUI puts drawer classes on `.q-drawer__content`; style the drawer with `.q-drawer:has(> .dw-...)`.
- Inside a page function, define handlers before rendering any `@ui.refreshable` that references them (or call them
  through a lambda), otherwise the first render raises a free-variable NameError.

## Content rules from the team

Sentence case, plain action-led copy, no em dashes, no small all-caps labels, no pill-shaped buttons, no purple
gradients, no emoji icons, no fake metrics. Status is always colour plus icon plus text. All data is labelled as
simulated.
