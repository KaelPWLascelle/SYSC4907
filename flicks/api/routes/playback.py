"""Playback (local files, and remote media through the relay) and watch progress.

docs/adr/0005-video-playback.md, docs/adr/0011-streaming.md.
"""
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from ...relay import RelayError
from ...services import Services
from ..deps import catalogue_id, services
from ..errors import client_errors
from ..schemas import ProgressIn

router = APIRouter()


@router.api_route('/media/{content_id}', methods=['GET', 'HEAD'])
def media(content_id: str, request: Request, svc: Services = Depends(services)):
    # A local file wins (a scanned video or a downloaded episode); its path comes from the startup scan or
    # the episode's ID, never from the request, and FileResponse serves Range requests.
    file = svc.media.get(content_id) or (svc.podcasts.file(content_id) if svc.podcasts else None)
    if file is not None and file.path.is_file():
        return FileResponse(file.path, media_type=file.media_type, headers={'Cache-Control': 'private, no-cache'})
    # Otherwise relay it from where it lives, forwarding the Range header so seeking works.
    try:
        relayed = svc.streams.open(content_id, request.headers.get('range'), request.method)
    except RelayError as error:
        return JSONResponse({'error': str(error)}, error.status)
    return StreamingResponse(relayed.chunks, status_code=relayed.status, headers=relayed.headers)


def _progress_json(progress, content=None):
    data = {**asdict(progress), 'resumable': progress.resumable}
    return {**data, 'content': asdict(content)} if content else data


@router.get('/api/history')
def history(svc: Services = Depends(services)):
    """Most recent first, each with its title's details (clients do not hold the whole catalogue)."""
    by_id = svc.titles.by_id
    return {'items': [_progress_json(p, by_id[p.content_id]) for p in svc.history.recent() if p.content_id in by_id]}


@router.put('/api/history/{content_id}')
def save_progress(content_id: str, body: ProgressIn, svc: Services = Depends(services)):
    catalogue_id(content_id, svc)
    with client_errors():
        return _progress_json(svc.history.save(content_id, body.position_seconds, body.duration_seconds))


@router.delete('/api/history/{content_id}', status_code=204)
def clear_progress(content_id: str, svc: Services = Depends(services)):
    catalogue_id(content_id, svc)
    svc.history.clear(content_id)
    return Response(status_code=204)
