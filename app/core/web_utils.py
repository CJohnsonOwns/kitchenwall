"""Small helpers shared by the routers."""


def safe_next(next_url: str | None, default: str) -> str:
    """A redirect target from a form, limited to paths on this site.

    Rejects "//host" and "/\\host" (browsers treat a backslash like a slash,
    so "/\\evil.com" would leave the site).
    """
    if next_url and next_url.startswith("/") and not next_url.startswith("//") and "\\" not in next_url:
        return next_url
    return default
