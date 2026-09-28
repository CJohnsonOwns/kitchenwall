"""Settings → Server: read-only health page. Deploys, restarts and rollbacks
happen outside the app so its sandbox never needs loosening."""
from fastapi import APIRouter, Request

from .. import server_status
from ..core.templating import render

router = APIRouter()


@router.get("/settings/server")
def server_page(request: Request, log: str = "all"):
    problems = log == "problems"
    return render(request, "server.html", {
        "s": server_status.status(),
        "log_rows": server_status.logs(problems_only=problems),
        "log_filter": "problems" if problems else "all",
    })
