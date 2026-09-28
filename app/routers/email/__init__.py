"""Inbox: one router per job, combined here. `recent_threads` feeds the Home page card."""
from fastapi import APIRouter

from . import accounts, actions, attachments, compose, inbox, thread
from .common import recent_threads  # noqa: F401

router = APIRouter()
for _m in (inbox, actions, thread, attachments, compose, accounts):
    router.include_router(_m.router)
