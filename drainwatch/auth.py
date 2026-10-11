"""Demo sign-in. Demonstration only: shared, published passwords and no real security."""

from __future__ import annotations

from sqlmodel import select

from drainwatch import db
from drainwatch.models import User

DEMO_PASSWORD = "demo"  # shown on the login screen on purpose


def sign_in(username: str, password: str) -> dict | None:
    """Returns a small session dict for a demo account, or None."""
    if password != DEMO_PASSWORD:
        return None
    with db.session_scope() as s:
        user = s.exec(select(User).where(User.username == username.strip().lower())).first()
    if user is None:
        return None
    return {
        "username": user.username,
        "role": user.role.value,
        "display_name": user.display_name,
        "crew_id": user.crew_id,
    }
