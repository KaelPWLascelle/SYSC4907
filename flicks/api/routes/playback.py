"""Video streaming and watch progress (docs/adr/0005-video-playback.md)."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response

from ...services import Services
from ..deps import catalogue_id, services
from ..errors import client_errors
from ..schemas import ProgressIn

router = APIRouter()


@router.api_route('/media/{content_id}', methods=['GET', 'HEAD'])
def media(content_id: str, svc: Services = Depends(services)):
    # The path comes from the startup scan, never from the request; FileResponse serves Range requests.
    file = svc.media.get(content_id)
    if file is None or not file.path.is_file():
        raise HTTPException(404, 'This title has no playable file')
    return FileResponse(file.path, media_type=file.media_type, headers={'Cache-Control': 'private, no-cache'})


def _progress_json(progress):
    return {**asdict(progress), 'resumable': progress.resumable}


@router.get('/api/history')
def history(svc: Services = Depends(services)):
    return {'items': [_progress_json(p) for p in svc.history.recent() if p.content_id in svc.ids]}


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
