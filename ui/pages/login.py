"""Sign-in screen with the demo accounts listed, so judges can get in quickly."""

from __future__ import annotations

from nicegui import app, ui

from drainwatch import service
from ui import components as c
from ui.layout import head

ACCOUNTS = (
    ("operator", "Control room operator", "Full dashboard, map, queue, work orders, analytics"),
    ("crew", "Field crew", "Assigned tasks, checklist, photos, report form. Works on a phone."),
)


@ui.page("/login")
def login_page() -> None:
    head()
    ui.dark_mode(None)
    ui.page_title("Sign in | Drain Watch")
    user = app.storage.user.get("user")
    if user:
        ui.navigate.to("/crew" if user["role"] == "crew" else "/")
        return

    def attempt(username: str, password: str) -> None:
        result = service.sign_in(username, password)
        if result is None:
            error.set_text("That username and password do not match a demo account.")
            return
        app.storage.user["user"] = result
        ui.navigate.to("/crew" if result["role"] == "crew" else "/")

    with ui.element("main").classes("dw-login-bg"):
        with ui.column().classes("dw-login-card gap-4"):
            with ui.row().classes("items-center gap-3"):
                with ui.element("div").classes("dw-brand-mark"):
                    ui.icon("water_drop").classes("text-xl")
                with ui.column().classes("gap-0"):
                    ui.label("Drain Watch").classes("dw-brand-name")
                    ui.label("Rivermere city drainage operations").classes("dw-brand-sub")
            with ui.element("div").classes("dw-card p-6 w-full"):
                ui.html('<h1 class="dw-h1">Sign in</h1>', sanitize=False)
                ui.label("Ranks drains by inspection priority during heavy rain and explains every rank.").classes(
                    "dw-body dw-muted mt-1"
                )
                with ui.column().classes("w-full gap-3 mt-5"):
                    username = ui.input("Username").props('outlined autocomplete="username"').classes("w-full")
                    password = (
                        ui.input("Password", password=True, password_toggle_button=True)
                        .props('outlined autocomplete="current-password"')
                        .classes("w-full")
                    )
                    password.on("keydown.enter", lambda: attempt(username.value or "", password.value or ""))
                    error = ui.label().classes("dw-small").style("color:var(--critical-ink)").props('role="alert"')
                    c.button("Sign in", on_click=lambda: attempt(username.value or "", password.value or "")).classes(
                        "dw-btn-primary w-full dw-touch"
                    ).props("unelevated no-caps")
                ui.separator().classes("my-5")
                ui.label("Demo accounts").classes("dw-section-title")
                ui.label("For demonstration only. The password for both is demo. There is no real security.").classes(
                    "dw-small dw-muted"
                )
                with ui.column().classes("w-full gap-2 mt-3"):
                    for name, role, note in ACCOUNTS:
                        with (
                            ui.element("button")
                            .classes("dw-row-item w-full text-left")
                            .on("click", lambda n=name: attempt(n, "demo"))
                            .props(f'type="button" aria-label="Sign in as {name}"')
                        ):
                            with ui.row().classes("items-center justify-between w-full no-wrap"):
                                with ui.column().classes("gap-0"):
                                    with ui.row().classes("items-baseline gap-2"):
                                        ui.label(name).classes("dw-mono font-semibold")
                                        ui.label(role).classes("dw-small")
                                    ui.label(note).classes("dw-xs dw-muted")
                                ui.label("Sign in").classes("dw-small font-semibold whitespace-nowrap").style(
                                    "color:var(--accent-ink)"
                                )
            with ui.row().classes("gap-4 justify-center w-full dw-small"):
                ui.link("About and method", "/about").classes("dw-link").style("color:var(--topbar-muted)")
                ui.link("Privacy", "/privacy").classes("dw-link").style("color:var(--topbar-muted)")
                ui.link("Terms", "/terms").classes("dw-link").style("color:var(--topbar-muted)")
            ui.label("All data in this app is simulated.").classes("dw-small text-center w-full").style(
                "color:var(--topbar-muted)"
            )
