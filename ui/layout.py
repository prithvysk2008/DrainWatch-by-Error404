"""Shell for every operator page: top command bar, sidebar, storm control, banner, notifications.

Pages register callbacks with Page.on_live (simulation or data changed) and Page.on_theme (theme
changed). One timer per page polls service.version() and calls them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import app, ui

from drainwatch import service
from drainwatch.models import ReportSource, ReportType, Severity
from drainwatch.theme import Palette, palette
from ui import components as c

NAV = (
    ("overview", "/", "dashboard", "Overview"),
    ("map", "/map", "map", "Live monitoring map"),
    ("queue", "/queue", "format_list_numbered", "Priority risk queue"),
    ("incidents", "/incidents", "campaign", "Incidents and complaints"),
    ("work", "/work-orders", "local_shipping", "Crews and work orders"),
    ("analytics", "/analytics", "insights", "Analytics and hotspots"),
    ("sensors", "/sensors", "sensors", "Sensors and calibration"),
)
TONE_ICON = {"critical": "error", "warning": "warning", "info": "info", "ok": "check_circle"}


@dataclass
class Page:
    username: str
    display_name: str
    dark: bool
    reduced_motion: bool
    _live: list[Callable[[], None]] = field(default_factory=list)
    _theme: list[Callable[[], None]] = field(default_factory=list)
    open_drain: Callable[[str], None] | None = None
    version: int = -1

    @property
    def zone_id(self) -> str | None:
        return app.storage.user.get("zone") or None

    def palette(self) -> Palette:
        return palette(self.dark)

    def on_live(self, fn: Callable[[], None]) -> None:
        self._live.append(fn)

    def on_theme(self, fn: Callable[[], None]) -> None:
        self._theme.append(fn)

    def fire_live(self) -> None:
        for fn in list(self._live):
            fn()

    def fire_theme(self) -> None:
        for fn in list(self._theme):
            fn()


def require_user(role: str | None = None) -> dict | None:
    user = app.storage.user.get("user")
    if not user or (role and user.get("role") != role):
        ui.navigate.to("/login")
        return None
    return user


def head() -> None:
    ui.add_head_html('<link rel="stylesheet" href="/static/css/drainwatch.css">')
    # Quasar colours point at the design tokens, so they follow the theme without being reset.
    ui.colors(
        primary="var(--accent)",
        secondary="var(--info)",
        accent="var(--accent)",
        dark="var(--card)",
        dark_page="var(--main)",
        positive="var(--normal)",
        negative="var(--critical)",
        info="var(--info)",
        warning="var(--warning)",
    )
    ui.add_head_html('<meta name="color-scheme" content="light dark">')


async def detect_client(page_dark_pref: str) -> tuple[bool, bool]:
    """Ask the browser for its colour-scheme and reduced-motion preferences (one call)."""
    await ui.context.client.connected()
    result = await ui.run_javascript(
        "[matchMedia('(prefers-color-scheme: dark)').matches, matchMedia('(prefers-reduced-motion: reduce)').matches]"
    )
    system_dark, reduced = bool(result[0]), bool(result[1])
    dark = system_dark if page_dark_pref == "system" else page_dark_pref == "dark"
    return dark, reduced


async def shell(active: str, title: str) -> Page | None:
    """Build the operator shell. Returns None when the visitor is redirected to sign in."""
    user = require_user("operator")
    if user is None:
        return None
    head()
    pref = app.storage.user.get("theme", "system")
    dark, reduced = await detect_client(pref)
    dark_mode = ui.dark_mode(dark)
    page = Page(user["username"], user["display_name"], dark, reduced)
    ui.page_title(f"{title} | Drain Watch")

    def set_theme(choice: str) -> None:
        app.storage.user["theme"] = choice
        ui.navigate.reload() if choice == "system" else _apply(choice == "dark")

    def _apply(is_dark: bool) -> None:
        page.dark = is_dark
        dark_mode.value = is_dark
        page.fire_theme()
        theme_button.refresh()

    # ---------------------------------------------------------------- header
    with ui.header().classes("dw-topbar items-center no-wrap gap-3 px-4"):
        c.button(icon="menu", on_click=lambda: sidebar.toggle()).props(
            "flat dense round aria-label='Open menu'"
        ).classes("lg:hidden text-white")
        with (
            ui.link(target="/")
            .classes("flex items-center gap-3 no-underline shrink-0")
            .props('aria-label="Drain Watch overview"')
        ):
            with ui.element("div").classes("dw-brand-mark"):
                ui.icon("water_drop").classes("text-xl")
            with ui.column().classes("gap-0"):
                ui.label("Drain Watch").classes("dw-brand-name whitespace-nowrap")
                ui.label("Rivermere city drainage operations").classes("dw-brand-sub whitespace-nowrap max-2xl:hidden")

        with ui.row().classes("items-center gap-2 no-wrap ml-4 max-xl:hidden"):
            with (
                ui.element("span")
                .classes("dw-chip")
                .tooltip("Every reading, report and drain in this app is simulated for demonstration.")
            ):
                ui.icon("science").classes("text-base")
                ui.label("Simulated data")

            @ui.refreshable
            def storm_chip() -> None:
                st = service.state()
                with ui.element("span").classes("dw-chip"):
                    ui.element("span").classes("dw-live-dot " + ("is-live" if st.playing else "is-idle"))
                    ui.label(f"{st.scenario}, step {st.step + 1} of {st.total_steps}")

            storm_chip()
            zone_options = {"": "All zones"} | {zid: name for zid, name in service.zones()}

            def zone_changed(e) -> None:
                app.storage.user["zone"] = e.value or ""
                page.fire_live()

            ui.select(zone_options, value=app.storage.user.get("zone", ""), on_change=zone_changed).props(
                'dense borderless options-dense aria-label="Zone filter"'
            ).classes("dw-zone-select")

        ui.space()

        @ui.refreshable
        def weather() -> None:
            level, name = service.threat()
            rate = service.city_rain_mm_h()
            with ui.row().classes("items-center gap-4 no-wrap max-lg:hidden"):
                with ui.element("div").classes("dw-topbar-metric"):
                    ui.label("Rain rate").classes("k")
                    ui.label(f"{rate:.1f} mm/h").classes("v dw-mono")
                with ui.element("div").classes("dw-topbar-metric"):
                    ui.label("Flood threat").classes("k")
                    roman = {1: "I", 2: "II", 3: "III", 4: "IV"}[level]
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon({1: "check_circle", 2: "info", 3: "warning", 4: "error"}[level]).classes(
                            "text-sm"
                        ).style(f"color:var({['--normal', '--info', '--warning', '--critical'][level - 1]})")
                        ui.label(f"Level {roman}, {name}").classes("v")

        weather()

        @ui.refreshable
        def play_button() -> None:
            st = service.state()
            if st.playing:
                c.button("Pause storm", icon="pause", on_click=lambda: service.pause(page.username)).classes(
                    "dw-btn-primary"
                ).props("unelevated no-caps")
            else:
                done = st.step >= st.total_steps - 1
                c.button(
                    "Storm finished" if done else ("Resume storm" if st.step else "Start storm"),
                    icon="play_arrow",
                    on_click=lambda: service.play(page.username),
                ).classes("dw-btn-primary").props("unelevated no-caps" + (" disable" if done else ""))

        with ui.row().classes("items-center gap-2 no-wrap"):
            c.button(icon="tune", on_click=lambda: toggle_stormbar()).classes("dw-icon-btn max-md:hidden").props(
                'flat aria-label="Storm control"'
            ).tooltip("Storm control: scenario, intensity, speed and reset")
            play_button()
            c.button("Log incident", icon="add", on_click=lambda: log_incident_dialog(page)).classes(
                "dw-btn-secondary max-sm:hidden"
            ).props("unelevated no-caps")

            @ui.refreshable
            def bell() -> None:
                items = service.notifications()
                seen = app.storage.user.get("seen_notification", 0)
                unread = sum(1 for n in items if n.id > seen)
                with (
                    c.button(icon="notifications")
                    .classes("dw-icon-btn")
                    .props(f'flat aria-label="Notifications, {unread} unread"')
                ):
                    if unread:
                        ui.badge(str(min(unread, 99)), color=None).props("floating").classes("dw-mono").style(
                            "background:var(--critical);color:#fff"
                        )
                    with ui.menu().classes("w-[380px] max-w-[92vw]"):
                        with ui.row().classes("items-center justify-between px-4 pt-3 pb-2 w-full"):
                            ui.label("Notifications").classes("dw-section-title")
                            if items:
                                c.button("Mark all as read", on_click=lambda: mark_read(items[0].id)).props(
                                    "flat dense no-caps"
                                ).classes("dw-btn-ghost text-xs")
                        ui.separator()
                        if not items:
                            with ui.element("div").classes("p-4"):
                                c.empty_state(
                                    "No alerts yet. Start a storm to see drains change.", "notifications_none"
                                )
                        with ui.scroll_area().classes("h-[360px]") if items else ui.element("div"):
                            for n in items[:30]:
                                with ui.item(
                                    on_click=(lambda d=n.drain_id: page.open_drain(d))
                                    if n.drain_id and page.open_drain
                                    else None
                                ).classes("py-2"):
                                    with ui.item_section().props("avatar"):
                                        ui.icon(TONE_ICON.get(n.tone, "info")).style(
                                            f"color:var(--{'normal' if n.tone == 'ok' else n.tone})"
                                        )
                                    with ui.item_section():
                                        ui.label(n.title).classes(
                                            "font-semibold text-[13px]" + ("" if n.id > seen else " dw-muted")
                                        )
                                        ui.label(n.body).classes("dw-small dw-muted")
                                    with ui.item_section().props("side"):
                                        ui.label(f"{n.ts:%H:%M}").classes("dw-xs dw-mono dw-muted")

            def mark_read(latest: int) -> None:
                app.storage.user["seen_notification"] = latest
                bell.refresh()

            bell()

            @ui.refreshable
            def theme_button() -> None:
                icon = "light_mode" if page.dark else "dark_mode"
                label = "Switch to light mode" if page.dark else "Switch to dark mode"
                c.button(icon=icon, on_click=lambda: set_theme("light" if page.dark else "dark")).classes(
                    "dw-icon-btn"
                ).props(f'flat aria-label="{label}"').tooltip(label)

            theme_button()

            with c.button(icon="account_circle").classes("dw-icon-btn").props('flat aria-label="Account menu"'):
                with ui.menu().classes("min-w-[220px]"):
                    with ui.column().classes("px-4 py-3 gap-0"):
                        ui.label(page.display_name).classes("font-semibold")
                        ui.label("Operator, demo account").classes("dw-small dw-muted")
                    ui.separator()
                    ui.menu_item("Use system theme", on_click=lambda: set_theme("system"))
                    ui.menu_item("About and method", on_click=lambda: ui.navigate.to("/about"))
                    ui.menu_item("Field crew view", on_click=lambda: ui.navigate.to("/crew"))
                    ui.separator()
                    ui.menu_item("Sign out", on_click=sign_out)

    # ---------------------------------------------------------------- sidebar
    with (
        ui.left_drawer(value=None, fixed=True).classes("dw-sidebar p-0").props("width=256 breakpoint=1024") as sidebar,
        ui.column().classes("h-full w-full gap-0 no-wrap"),
    ):
        with ui.column().classes("w-full gap-0 grow overflow-y-auto pt-2"):
            ui.label("Operations").classes("dw-nav-group")

            @ui.refreshable
            def nav() -> None:
                k = service.kpis(page.zone_id)
                open_reports = service.open_incident_count()
                for key, href, icon, label in NAV:
                    with (
                        ui.link(target=href)
                        .classes("dw-nav-item" + (" is-active" if key == active else ""))
                        .props('aria-current="page"' if key == active else "")
                    ):
                        ui.icon(icon)
                        ui.label(label).classes("truncate")
                        if key == "map" and k["critical"]:
                            ui.label(str(k["critical"])).classes("dw-nav-badge is-critical").props(
                                f'aria-label="{k["critical"]} critical drains"'
                            ).tooltip("Critical drains")
                        if key == "incidents" and open_reports:
                            ui.label(str(open_reports)).classes("dw-nav-badge is-warning").props(
                                f'aria-label="{open_reports} new reports"'
                            ).tooltip("New reports")

            nav()
            ui.label("Reference").classes("dw-nav-group")
            with ui.link(target="/about").classes("dw-nav-item" + (" is-active" if active == "about" else "")):
                ui.icon("menu_book")
                ui.label("About and method")

        @ui.refreshable
        def footer() -> None:
            fs = service.fill_summary(page.zone_id)
            total = max(fs["normal"] + fs["warning"] + fs["critical"], 1)
            free, crews_total = service.crews_free()
            with ui.element("div").classes("dw-side-footer w-full"):
                with ui.row().classes("items-baseline justify-between w-full"):
                    ui.label("Catchment fill").classes("font-semibold")
                    ui.label(f"{fs['average']:.0f}% average").classes("dw-tabular")
                with (
                    ui.element("div")
                    .classes("dw-split-bar my-2")
                    .props(
                        f'role="img" aria-label="{fs["normal"]:.0f} normal, {fs["warning"]:.0f} warning, '
                        f'{fs["critical"]:.0f} critical"'
                    )
                ):
                    for key, var in (("normal", "--normal"), ("warning", "--warning"), ("critical", "--critical")):
                        if fs[key]:
                            ui.element("div").style(f"width:{100 * fs[key] / total:.1f}%;background:var({var})")
                with ui.element("div").classes("grid grid-cols-3 w-full gap-1"):
                    for key, var, text in (
                        ("normal", "--normal", "Normal"),
                        ("warning", "--warning", "Warning"),
                        ("critical", "--critical", "Critical"),
                    ):
                        with ui.column().classes("gap-0"):
                            with ui.row().classes("items-center gap-1 no-wrap dw-xs"):
                                ui.element("span").classes("dw-legend-dot").style(f"background:var({var})")
                                ui.label(text).style("color:var(--sidebar-muted)")
                            ui.label(f"{fs[key]:.0f}").classes("font-semibold dw-tabular text-[15px] pl-3")
                ui.label(f"{fs['unknown']:.0f} drains without a working sensor").classes("dw-xs mt-2").style(
                    "color:var(--sidebar-muted)"
                )
                with ui.element("div").classes("dw-side-card mt-3 flex justify-between items-center"):
                    ui.label("Crews free")
                    ui.label(f"{free} of {crews_total}").classes("font-semibold dw-tabular")

        footer()

    # ---------------------------------------------------------------- storm control and banner
    with ui.column().classes("w-full gap-0"):
        stormbar = ui.element("div").classes("dw-stormbar w-full")
        stormbar.set_visibility(app.storage.user.get("stormbar_open", False))
        with stormbar:
            storm_control(page)

        @ui.refreshable
        def banner() -> None:
            b = service.storm_banner()
            if not b:
                return
            tone, text = b
            with ui.element("div").classes("px-6 pt-4 w-full max-w-[1600px] mx-auto"):
                with ui.element("div").classes(f"dw-banner is-{tone}").props('role="status"'):
                    ui.icon({"info": "info", "advisory": "info", "warning": "warning", "critical": "error"}[tone])
                    ui.label(text)

        banner()

    def toggle_stormbar() -> None:
        stormbar.set_visibility(not stormbar.visible)
        app.storage.user["stormbar_open"] = stormbar.visible

    # ---------------------------------------------------------------- live polling
    def poll() -> None:
        v = service.version()
        if v == page.version:
            return
        page.version = v
        storm_chip.refresh()
        weather.refresh()
        play_button.refresh()
        bell.refresh()
        nav.refresh()
        footer.refresh()
        banner.refresh()
        page.fire_live()

    page.version = service.version()
    ui.timer(0.5, poll)
    return page


def storm_control(page: Page) -> None:
    """Scenario, intensity, speed, play, pause, step and reset. Only the progress line refreshes live."""
    st = service.state()
    with ui.row().classes("w-full max-w-[1600px] mx-auto items-end gap-x-6 gap-y-3 wrap"):
        with ui.column().classes("gap-1"):
            ui.label("Scenario").classes("dw-xs dw-muted")
            scenario = (
                ui.toggle(
                    list(service.scenarios()),
                    value=st.scenario,
                    on_change=lambda e: service.set_scenario(e.value, page.username),
                )
                .props("no-caps unelevated toggle-color=dw-on toggle-text-color=dw-on-text")
                .classes("dw-seg")
            )
        with ui.column().classes("gap-1 min-w-[220px]"):
            intensity_label = ui.label().classes("dw-xs dw-muted")
            intensity = (
                ui.slider(min=0.5, max=1.5, step=0.1, value=st.intensity)
                .props('label aria-label="Storm intensity"')
                .classes("w-[220px]")
            )
            intensity.on("change", lambda e: service.set_intensity(float(intensity.value), page.username))
            intensity_label.bind_text_from(intensity, "value", lambda v: f"Rain intensity from the next step: {v:.1f}x")
        with ui.column().classes("gap-1"):
            ui.label("Speed").classes("dw-xs dw-muted")
            ui.toggle(
                {s: f"{s:g}x" for s in service.SPEEDS},
                value=st.speed,
                on_change=lambda e: service.set_speed(float(e.value)),
            ).props("no-caps unelevated toggle-color=dw-on toggle-text-color=dw-on-text").classes("dw-seg")

        @ui.refreshable
        def buttons() -> None:
            now = service.state()
            with ui.row().classes("gap-2"):
                if now.playing:
                    c.button("Pause", icon="pause", on_click=lambda: service.pause(page.username)).classes(
                        "dw-btn-secondary"
                    ).props("unelevated no-caps")
                else:
                    c.button("Play", icon="play_arrow", on_click=lambda: service.play(page.username)).classes(
                        "dw-btn-secondary"
                    ).props("unelevated no-caps")
                c.button("Step forward", icon="skip_next", on_click=lambda: step_once()).classes(
                    "dw-btn-secondary"
                ).props("unelevated no-caps" + (" disable" if now.playing else ""))
                c.button("Reset", icon="restart_alt", on_click=lambda: confirm_reset()).classes(
                    "dw-btn-secondary"
                ).props("unelevated no-caps")

        buttons()

        @ui.refreshable
        def progress() -> None:
            now = service.state()
            with ui.column().classes("gap-1 grow min-w-[200px]"):
                with ui.row().classes("justify-between w-full dw-xs dw-muted"):
                    ui.label(f"{now.sim_time:%H:%M}, step {now.step + 1} of {now.total_steps}")
                    ui.label("10 simulated minutes per step")
                with (
                    ui.element("div")
                    .classes("dw-progress w-full")
                    .props(
                        f'role="progressbar" aria-valuemin="1" aria-valuemax="{now.total_steps}" '
                        f'aria-valuenow="{now.step + 1}" aria-label="Storm progress"'
                    )
                ):
                    ui.element("div").style(f"width:{100 * (now.step + 1) / now.total_steps:.1f}%")

        progress()

    def step_once() -> None:
        speed = max(service.state().speed, 0.01)
        service.play(page.username)
        service.tick(1.0 / speed)
        service.pause(page.username)

    def confirm_reset() -> None:
        with ui.dialog() as dialog, ui.card().classes("p-5 max-w-[420px]"):
            ui.label("Reset the storm?").classes("dw-card-title")
            ui.label(
                "This clears reports, work orders and inspections from this storm and starts again at step 1. "
                "Thresholds are kept."
            ).classes("dw-body dw-muted mt-1")
            with ui.row().classes("justify-end w-full gap-2 mt-4"):
                c.button("Keep storm", on_click=dialog.close).classes("dw-btn-secondary").props("unelevated no-caps")

                def do_reset() -> None:
                    service.reset(page.username)
                    dialog.close()
                    ui.notify("Storm reset to step 1.", type="info")

                c.button("Reset storm", on_click=do_reset).classes("dw-btn-primary").props("unelevated no-caps")
        dialog.open()

    def sync() -> None:
        now = service.state()
        if scenario.value != now.scenario:
            scenario.set_value(now.scenario)
        buttons.refresh()
        progress.refresh()

    page.on_live(sync)


def drain_options() -> dict[str, str]:
    return {r.info.id: f"{r.info.id}  {r.info.name}" for r in sorted(service.drain_rows(), key=lambda r: r.info.id)}


def log_incident_dialog(page: Page, drain_id: str | None = None) -> None:
    """Log a report from the control room. Submitting rescores the drain at once."""
    with ui.dialog() as dialog, ui.card().classes("p-0 w-[560px] max-w-[95vw]"):
        with ui.row().classes("items-center justify-between w-full px-5 pt-4 pb-3"):
            ui.label("Log field incident").classes("dw-card-title")
            c.button(icon="close", on_click=dialog.close).props('flat round dense aria-label="Close"')
        ui.separator()
        with ui.column().classes("w-full gap-3 px-5 py-4"):
            drain = (
                ui.select(drain_options(), value=drain_id, label="Drain or location", with_input=True)
                .props("outlined dense options-dense")
                .classes("w-full")
            )
            with ui.row().classes("w-full gap-3 no-wrap max-sm:flex-wrap"):
                kind = (
                    ui.select({t.name: t.value for t in ReportType}, value=ReportType.trash.name, label="Issue type")
                    .props("outlined dense")
                    .classes("grow")
                )
                severity = (
                    ui.select(
                        {s.name: c.SEVERITY_TEXT[s.value] for s in Severity}, value=Severity.high.name, label="Severity"
                    )
                    .props("outlined dense")
                    .classes("grow")
                )
            reporter = ui.input("Reporter", value="Control room").props("outlined dense").classes("w-full")
            notes = (
                ui.textarea("What was seen", placeholder="For example: water across both lanes at the inlet")
                .props("outlined dense autogrow")
                .classes("w-full")
            )
            error = ui.label().classes("dw-small").style("color:var(--critical-ink)")
        ui.separator()

        def submit() -> None:
            if not drain.value:
                error.set_text("Choose the drain this report is about.")
                return
            before = service.score_for(drain.value)
            report = service.log_report(
                drain.value,
                ReportType[kind.value],
                Severity[severity.value],
                ReportSource.operator,
                reporter.value or "Control room",
                notes.value or "Logged by the control room.",
                page.username,
            )
            after = service.score_for(drain.value)
            change = f" Priority {before.score:.0f} to {after.score:.0f}." if before and after else ""
            ui.notify(f"Report {report.id} logged for {drain.value}.{change}", type="positive")
            dialog.close()

        with ui.row().classes("justify-end w-full gap-2 px-5 py-3"):
            c.button("Cancel", on_click=dialog.close).classes("dw-btn-secondary").props("unelevated no-caps")
            c.button("Log incident", icon="check", on_click=submit).classes("dw-btn-primary").props(
                "unelevated no-caps"
            )
    dialog.open()


def sign_out() -> None:
    app.storage.user.pop("user", None)
    ui.navigate.to("/login")
