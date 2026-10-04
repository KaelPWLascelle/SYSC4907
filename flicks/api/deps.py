"""FastAPI dependencies."""
from fastapi import HTTPException, Request

from ..services import Services


def services(request: Request) -> Services:
    return request.app.state.services


def catalogue_id(content_id: str, svc: Services) -> str:
    if content_id not in svc.ids:
        raise HTTPException(404, 'Unknown content ID')
    return content_id
