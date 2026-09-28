"""/static with a cache policy.

Pages link files as /static/x?v=<mtime> (templating.static_url), so a
versioned URL never changes content: browsers may keep it for a year. Anything
fetched without ?v= (e.g. a JS module imported by another module) must be
revalidated each time (a cheap 304 via ETag), so a deploy never leaves a phone
running a stale mix of old and new modules.
"""
import mimetypes

from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

# Python's mimetypes can read .js as text/plain from the Windows registry;
# browsers refuse to run a module served that way.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/woff2", ".woff2")


class CachedStatic(StaticFiles):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        versioned = b"v=" in scope.get("query_string", b"")
        policy = b"public, max-age=31536000, immutable" if versioned else b"no-cache"

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", policy))
                message = {**message, "headers": headers}
            await send(message)

        await super().__call__(scope, receive, send_with_cache)
