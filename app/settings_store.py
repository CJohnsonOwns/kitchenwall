"""Household-wide preferences, stored in the generic `settings` table.

Kept separate from `weather.py` (which owns the location keys) so routers
and templates have one place to read defaults from.
"""
from . import db

# key -> (default, allowed values). Values are stored as strings.
SETTING_SPECS = {
    "units": ("f", ("f", "c")),
    "week_start": ("sun", ("sun", "mon")),
    "lookahead_days": ("7", ("7", "14", "30")),
    "mail_sync_minutes": ("15", ("0", "15", "30", "60")),
    "display_refresh_minutes": ("5", ("0", "5", "15")),
}


def _valid(key: str, value: str | None) -> str:
    default, allowed = SETTING_SPECS[key]
    return value if value in allowed else default


def get_setting(key: str) -> str:
    return _valid(key, db.get_setting(key))


def set_setting(key: str, value: str) -> bool:
    """Returns False (and stores nothing) if the value isn't one of the allowed choices."""
    default, allowed = SETTING_SPECS[key]
    if value not in allowed:
        return False
    db.set_setting(key, value)
    return True


def get_settings(stored: dict | None = None) -> dict:
    """All household settings (one query; pass db.all_settings() if you have it)."""
    stored = db.all_settings() if stored is None else stored
    return {key: _valid(key, stored.get(key)) for key in SETTING_SPECS}


def get_int(key: str) -> int:
    return int(get_setting(key))
