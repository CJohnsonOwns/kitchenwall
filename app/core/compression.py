"""Gzip for pages, CSS, JS and JSON (they shrink 70-85%).

Media is skipped: photos and videos are already compressed, and videos are
served in byte ranges (phones seek with Range requests), which gzip would break.
"""
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

_MEDIA = ("/share/media/", "/board/photos/", "/inbox/att/", "/static/fonts/")


class Compress:
    def __init__(self, app: ASGIApp):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(_MEDIA) or any(
                k == b"range" for k, _ in scope["headers"]):
            return await self.app(scope, receive, send)
        await self.gzip(scope, receive, send)
