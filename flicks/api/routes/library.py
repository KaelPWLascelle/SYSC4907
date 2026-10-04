"""Catalogue state, ratings, recommendations and posters."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ...services import Services
from ..deps import services
from ..errors import client_errors
from ..schemas import FeedbackIn, RecommendIn

router = APIRouter()


@router.get('/api/state')
def state(svc: Services = Depends(services)):
    return {
        'catalog': [asdict(item) for item in svc.catalog],
        'feedback': svc.ratings.all(),
        'voice': svc.speech.status(),
        'assistant': svc.interpreter.name,
        'tagged': svc.tagged,
        'couch': svc.couch is not None,
        'posters': svc.posters.ids() if svc.posters else [],
        'media': [{'id': f.content_id, 'direct_play': f.direct_play} for f in svc.media.files.values()],
    }


@router.post('/api/feedback')
def feedback(body: FeedbackIn, svc: Services = Depends(services)):
    if body.id not in svc.ids:
        raise HTTPException(400, 'Unknown content ID')
    with client_errors():
        svc.ratings.set(body.id, body.value)
    return {'feedback': svc.ratings.all()}


@router.post('/api/recommend')
def recommend(body: RecommendIn, svc: Services = Depends(services)):
    feedback = svc.ratings.all()
    with client_errors():
        picks = svc.recommender.recommend(feedback, body.session.to_domain(), body.mode)
    return {'recommendations': picks, 'cold_start': not any(k in svc.ids and v == 1 for k, v in feedback.items())}


@router.get('/posters/{content_id}')
def poster(content_id: str, svc: Services = Depends(services)):
    # Only cached posters for catalogue IDs; browsing never fetches anything remotely (ADR 0001).
    image = svc.posters.read(content_id) if svc.posters else None
    if image is None:
        raise HTTPException(404, 'Not found')
    data, media_type = image
    return Response(data, media_type=media_type, headers={'Cache-Control': 'private, max-age=86400'})
