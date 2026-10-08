"""Podcast episodes: show details and downloads (docs/adr/0010-podcasts.md). Only mounted with a podcast catalogue."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from ...podcasts import PodcastError
from ...services import Services
from ..deps import services
from ..schemas import EmptyIn

router = APIRouter(prefix='/api/podcasts')


def _episode(content_id: str, svc: Services):
    episode = svc.podcasts.get(content_id)
    if episode is None:
        raise HTTPException(404, 'Not a podcast episode')
    return episode


@router.get('/downloads')
def downloads(svc: Services = Depends(services)):
    return {'downloads': svc.podcasts.downloads()}


@router.get('/{content_id}')
def episode(content_id: str, svc: Services = Depends(services)):
    item = _episode(content_id, svc)
    return {'id': item.id, 'show': item.show, 'link': item.link, 'published': item.published,
            'download': svc.podcasts.status(content_id)}


@router.post('/{content_id}/download', status_code=202)
def download(content_id: str, _body: EmptyIn, svc: Services = Depends(services)):
    # The audio URL comes from the imported feed, never from this request (ADR 0010).
    _episode(content_id, svc)
    return svc.podcasts.start(content_id)


@router.delete('/{content_id}/download', status_code=204)
def remove(content_id: str, svc: Services = Depends(services)):
    _episode(content_id, svc)
    try:
        svc.podcasts.remove(content_id)
    except PodcastError as error:
        return JSONResponse({'error': str(error)}, 409)
    return Response(status_code=204)
