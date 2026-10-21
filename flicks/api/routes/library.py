"""Catalogue state and search, ratings, recommendations and posters."""
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ...assistant.llm import LLMError
from ...services import Services
from ..deps import Viewer, services, viewer
from ..errors import client_errors
from ..schemas import DiscoverIn, ExplainIn, FeedbackIn, PickIn, RecommendIn

router = APIRouter()


@router.get('/api/state')
def state(svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    # The catalogue itself is not sent: it can hold thousands of titles. Clients search /api/titles.
    return {
        'catalog_size': len(svc.titles),
        'genres': svc.titles.genres,
        'feedback': me.ratings.all(),
        'profile': {'id': me.profile.id, 'name': me.profile.name, 'locked': me.profile.locked, 'chosen': me.chosen,
                    'count': len(svc.profiles.all())},
        'llm': svc.llm_status(),
        'voice': svc.speech.status(),
        'assistant': svc.interpreter.name,
        'tagged': svc.tagged,
        'trailers': len(svc.discover.trailers),
        'collaborative': svc.collaborative,
        'couch': svc.couch is not None,
        'podcasts': svc.podcasts is not None,
        'posters': svc.posters.ids() if svc.posters else [],
        'media': _playable(svc),
    }


def _playable(svc: Services):
    """Every title that can be played: local files (scanned videos, downloaded episodes) and remote streams.

    `remote` means it plays from elsewhere through the relay; `source` and `page` credit where from.
    """
    entries = {}
    for content_id, remote in svc.streams.items():
        entries[content_id] = {'id': content_id, 'direct_play': True, 'audio': remote.audio, 'remote': True,
                               'source': remote.source, 'page': remote.page or None}
    for file in [*svc.media.files.values(), *(svc.podcasts.media() if svc.podcasts else ())]:
        credit = entries.get(file.content_id, {})
        entries[file.content_id] = {'id': file.content_id, 'direct_play': file.direct_play, 'audio': file.audio,
                                    'remote': False, 'source': credit.get('source'), 'page': credit.get('page')}
    return list(entries.values())


@router.get('/api/titles')
def titles(
    q: str = Query('', max_length=100),
    show: Literal['all', 'liked', 'passed', 'unrated'] = 'all',
    similar: str | None = Query(None, max_length=64),
    offset: int = Query(0, ge=0),
    limit: int = Query(48, ge=1, le=100),
    svc: Services = Depends(services),
    me: Viewer = Depends(viewer),
):
    """Search the catalogue (everyday language, see flicks/search.py), or list titles like `similar`.

    Without a query, titles come most popular first. Results can be limited by the user's ratings.
    """
    feedback = me.ratings.all()
    wanted = {'liked': 1, 'passed': -1}.get(show)
    keep = (None if show == 'all' else
            (lambda item: item.id not in feedback) if show == 'unrated' else
            (lambda item: feedback.get(item.id) == wanted))
    if similar is not None:
        seed = svc.titles.by_id.get(similar)
        if seed is None:
            raise HTTPException(404, 'Unknown content ID')
        scores = svc.similar.scores({similar: 1})
        ranked = sorted((item for item in svc.catalog if item.id != similar and (keep is None or keep(item))),
                        key=lambda item: (-scores[item.id]['taste'], item.id))
        return {'items': [asdict(item) for item in ranked[offset:offset + limit]], 'total': len(ranked),
                'understood': [f'Like {seed.title}']}
    page, total, understood = svc.titles.search(q, keep, offset, limit)
    return {'items': [asdict(item) for item in page], 'total': total, 'understood': understood.labels()}


@router.post('/api/feedback')
def feedback(body: FeedbackIn, svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    if body.id not in svc.ids:
        raise HTTPException(400, 'Unknown content ID')
    with client_errors():
        me.ratings.set(body.id, body.value)
    return {'feedback': me.ratings.all()}


@router.post('/api/recommend')
def recommend(body: RecommendIn, svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    feedback = me.ratings.all()
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


@router.post('/api/explain')
def explain(body: ExplainIn, svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    """A pick's factors in words from the local language model, or `narration: null` (keep the template reasons).

    A plain (sync) route, so FastAPI runs the slow model call in its thread pool.
    """
    if body.id not in svc.ids:
        raise HTTPException(404, 'Unknown content ID')
    with client_errors():
        session = body.session.to_domain()
        pick = svc.recommender.explain_item(me.ratings.all(), session, body.id)
    if svc.narrator is None:
        return {'id': body.id, 'narration': None, 'note': 'No local language model is configured'}
    try:
        narrated = svc.narrator.narrate(me.profile.id, pick, session)
    except LLMError as error:
        return {'id': body.id, 'narration': None, 'note': str(error)}
    return {'id': body.id, 'narration': narrated['text'], 'model': narrated['model'],
            'note': 'Written by a language model on this device from the factors above.'}


@router.get('/api/taste')
def taste(svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    """What the profile's ratings say, for the "Your taste" view (flicks/taste.py)."""
    return svc.taste.summarize(me.ratings.all())


@router.post('/api/discover')
def discover(body: DiscoverIn, svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    """A page of the Discover feed (flicks/discover.py): rated and already-shown titles are skipped."""
    with client_errors():
        items = svc.discover.feed(me.ratings.all(), body.session.to_domain(), body.seen,
                                  online=body.online, limit=body.limit)
    return {'items': items}


@router.post('/api/pick')
def pick(body: PickIn, svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    """"Pick for me": one title at random from the top picks or from anything the scene allows."""
    with client_errors():
        return svc.discover.pick(me.ratings.all(), body.session.to_domain(), body.pool)
