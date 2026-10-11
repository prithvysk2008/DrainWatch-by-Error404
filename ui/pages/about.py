"""About and method, privacy and terms. Readable without signing in."""

from __future__ import annotations

from nicegui import app, ui

from drainwatch import config
from ui import components as c
from ui.layout import head, shell

UPDATED = "11 October 2026"

ABOUT = f"""
<p><strong>Drain Watch ranks drains by inspection priority during heavy rain and explains every rank.</strong>
It is built for municipal drainage teams who have more drains than crews and need to know where to look first.</p>

<p><strong>All data is simulated.</strong> Rivermere is a fictional city. Drain Watch demonstrates a prioritisation
method. It does not predict floods and it does not confirm that a drain is blocked. It tells crews where to look
first.</p>

<h2>How a drain is scored</h2>
<p>Every ten simulated minutes each drain gets a score from 0 to 100, built from four factors.</p>
<table>
<thead><tr><th scope="col">Factor</th><th scope="col">Points</th><th scope="col">What it measures</th></tr></thead>
<tbody>
<tr><td>Water level</td><td>{config.WEIGHTS.water_level:.0f}</td><td>How far the level is above what this rain
normally produces at this drain, divided by the drain's normal spread. A small part comes from how far past the
warning threshold the drain is. Drains without a working sensor borrow half the anomaly of the drains around them.
</td></tr>
<tr><td>Rainfall</td><td>{config.WEIGHTS.rainfall:.0f}</td><td>Half is the rain falling on the drain's zone over the
last 30 minutes. Half is persistence: how long the level has stayed high, which matters most after rain eases.</td></tr>
<tr><td>Inspection history</td><td>{config.WEIGHTS.history:.0f}</td><td>Days since the last inspection, blockages in
the past year and whether the drain is silt-prone. A drain cleared in the last two hours gets none.</td></tr>
<tr><td>Reports</td><td>{config.WEIGHTS.reports:.0f}</td><td>Reports within {config.REPORT_RADIUS_M:.0f} m, weighted
by severity and halving in weight every {config.REPORT_HALF_LIFE_MIN:.0f} minutes. Possible duplicates count once.
</td></tr>
</tbody></table>
<p>When reports and the sensor agree, the total is multiplied by {config.WEIGHTS.agreement_multiplier}. Up to
{config.WEIGHTS.consequence_points:.0f} more points go to drains on low ground or serving an underpass, hospital,
school or market, mainly to break ties. The score is capped at 100.</p>

<h2>Priority bands</h2>
<ul>
<li><strong>Critical</strong>: {config.BANDS.critical:.0f} or more. Inspect now.</li>
<li><strong>High</strong>: {config.BANDS.high:.0f} to {config.BANDS.critical - 1:.0f}.</li>
<li><strong>Medium</strong>: {config.BANDS.medium:.0f} to {config.BANDS.high - 1:.0f}.</li>
<li><strong>Low</strong>: below {config.BANDS.medium:.0f}.</li>
</ul>

<h2>Classification labels</h2>
<ul>
<li><strong>Likely local blockage</strong>: the level is well above normal while nearby drains are normal.</li>
<li><strong>Possible downstream congestion or widespread flooding</strong>: many nearby drains (within
{config.NEIGHBOUR_RADIUS_M:.0f} m, plus the drains directly up and downstream) are high too. Send a crew to the
junction downstream rather than the inlet.</li>
<li><strong>Unverified report</strong>: a report without sensor support. Someone should look before acting.</li>
<li><strong>Low confidence (no sensor)</strong> and <strong>Low confidence (sensor fault)</strong>: the score relies
on reports, history and nearby drains. A sensor counts as faulty when it stops sending data, or keeps sending
exactly the same reading.</li>
<li><strong>No anomaly</strong>: levels match normal behaviour for the rain so far.</li>
</ul>
<p>Every score also carries a confidence from 0 to 100 percent, based on whether a working sensor is present, whether
reports agree with it and whether nearby sensors exist to compare against.</p>

<h2>Water level status and flood threat</h2>
<p>Water level status uses one threshold profile, set on the Sensors page. The defaults are Warning from
75 percent of drain depth and Critical from 85 percent. Below 45 percent water flows freely.</p>
<table>
<thead><tr><th scope="col">Flood threat</th><th scope="col">Starts when</th></tr></thead>
<tbody>
{
    "".join(
        f"<tr><td>Level {['I', 'II', 'III', 'IV'][t.level - 1]}, {t.name}</td><td>"
        + (
            "Always the starting level"
            if t.level == 1
            else f"Rain reaches {t.min_rain_mm_h:g} mm per hour, or {t.min_share_above_warning * 100:.0f} percent of "
            "drains with a working sensor are above the warning level"
        )
        + "</td></tr>"
        for t in config.THREAT_LEVELS
    )
}
</tbody></table>

<h2>The simulation</h2>
<ul>
<li>150 drains in four zones form a network that drains south to four river outfalls. 90 drains carry a
water-level sensor.</li>
<li>Three storms (light rain, heavy storm, cloudburst) each run six hours in 36 steps of ten minutes. Intensity can be
changed while a storm runs.</li>
<li>Normal behaviour for each drain comes from running the same storm with no faults.</li>
<li>Hidden in each run: ten local blockages, one congested trunk junction that backs up the drains upstream of it,
and three faulty sensors. In a heavy storm or cloudburst a blocked drain gets a report about half the time
(less often in light rain), 30 to 90 minutes after the blockage starts. The congested section produces two flooding
reports. Eight false reports and three duplicates are mixed in.</li>
<li>A fixed random seed makes every run repeatable.</li>
</ul>

<h2>Validation</h2>
<p>The Analytics page compares the ranking with the hidden simulation truth: precision at 10 and recall at 20,
against a random ranking. This shows how the method behaves on simulated data. It is not a measure of real-world
accuracy.</p>

<h2>Limits</h2>
<ul>
<li>All data is simulated, and the method has not been tested on real drains or real storms.</li>
<li>A high rank is a reason to look, not proof of a blockage. Crews confirm on site.</li>
<li>The map is a schematic of a fictional city, not a survey.</li>
<li>Sign-in uses shared demo accounts with no real security.</li>
</ul>

<h2>Team</h2>
<p>Built by Team Error404 for PySustain-2026, Track 2: water management and sanitation. Written in Python with
NiceGUI, FastAPI, SQLModel, NumPy and NetworkX.</p>
"""

PRIVACY = f"""
<p>Last updated {UPDATED}.</p>
<p>Drain Watch is a hackathon demonstration that runs on simulated data. This page explains what the app stores
when you use it.</p>
<h2>What is stored</h2>
<ul>
<li><strong>A session cookie</strong> that keeps you signed in to a demo account and remembers your preferences:
theme, zone filter, table layout and which notifications you have read.</li>
<li><strong>What you enter</strong>: reports, notes, checklist ticks and work order changes go into a SQLite database
on the server running the demo. The database is rebuilt from scratch every time the app starts.</li>
<li><strong>Photos you upload</strong> are saved as files on that server, in the static/uploads folder, and stay
there until someone deletes them. Anyone using the demo can see them.</li>
</ul>
<h2>What is not collected</h2>
<ul>
<li>No analytics, advertising or tracking scripts.</li>
<li>Fonts and icons are served by the app itself, so your browser does not contact font services.</li>
<li>Nothing you enter is sent to any third party.</li>
</ul>
<h2>Please do not upload personal data</h2>
<p>Do not enter real names, phone numbers or addresses, and do not upload photos that show people or vehicle number
plates. The demo accounts are shared and nothing here is private.</p>
<h2>Questions</h2>
<p>Contact Team Error404 through the project's GitHub repository.</p>
"""

TERMS = f"""
<p>Last updated {UPDATED}.</p>
<h2>What this is</h2>
<p>Drain Watch is a demonstration built for the PySustain-2026 hackathon. Every drain, reading, report and storm in
it is simulated, and the city of Rivermere is fictional.</p>
<h2>Not for operational use</h2>
<p>Do not use Drain Watch to make real decisions about drainage, flooding or public safety. It does not predict
floods and does not confirm blockages. In an emergency, contact your local emergency services.</p>
<h2>Demo accounts</h2>
<p>The operator and crew accounts are shared and their password is published on the sign-in screen. There is no
real security. Anything you enter can be seen and changed by anyone else using the demo.</p>
<h2>Your content</h2>
<p>Only upload photos and text you have the right to share, and nothing that identifies a person. Uploaded content
may be removed at any time.</p>
<h2>No warranty</h2>
<p>The app is provided as is, without warranty of any kind. Team Error404 is not liable for any loss arising from
its use.</p>
<h2>Code</h2>
<p>The source code is published on GitHub by Team Error404. Unless a licence file in the repository says otherwise,
all rights are reserved by the authors.</p>
"""


def public_frame(title: str) -> None:
    head()
    ui.dark_mode(None)
    ui.page_title(f"{title} | Drain Watch")
    with ui.header().classes("dw-topbar items-center no-wrap gap-3 px-4"):
        with ui.link(target="/").classes("flex items-center gap-3 no-underline shrink-0"):
            with ui.element("div").classes("dw-brand-mark"):
                ui.icon("water_drop").classes("text-xl")
            ui.label("Drain Watch").classes("dw-brand-name whitespace-nowrap")
        ui.space()
        signed_in = bool(app.storage.user.get("user"))
        c.button(
            "Back to the app" if signed_in else "Sign in",
            icon="arrow_back" if signed_in else "login",
            on_click=lambda: ui.navigate.to("/" if signed_in else "/login"),
        ).classes("dw-btn-secondary").props("unelevated no-caps")


def prose(title: str, body: str, note: str | None = None) -> None:
    with ui.element("main").classes("dw-page w-full"):
        with ui.element("article").classes("dw-card px-6 py-6 md:px-10 md:py-8 max-w-[860px]"):
            ui.html(f'<h1 class="dw-h1">{title}</h1>', sanitize=False)
            if note:
                ui.label(note).classes("dw-muted mt-1")
            ui.html(f'<div class="dw-prose mt-4">{body}</div>', sanitize=False)
            with ui.row().classes("gap-4 mt-8 dw-small"):
                for text, href in (("About and method", "/about"), ("Privacy", "/privacy"), ("Terms", "/terms")):
                    ui.link(text, href).classes("dw-link")


@ui.page("/about")
async def about_page() -> None:
    user = app.storage.user.get("user")
    if user and user.get("role") == "operator":
        page = await shell("about", "About and method")
        if page is None:
            return
    else:
        public_frame("About and method")
    prose("About and method", ABOUT, "How Drain Watch ranks drains, what the labels mean and where the method stops.")


@ui.page("/privacy")
def privacy_page() -> None:
    public_frame("Privacy")
    prose("Privacy", PRIVACY)


@ui.page("/terms")
def terms_page() -> None:
    public_frame("Terms and conditions")
    prose("Terms and conditions", TERMS)
