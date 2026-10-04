"""Host-side couch controls (loopback only). Guests use the separate app in flicks/api/guest.py."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ...services import Services
from ..deps import services
from ..errors import client_errors
from ..schemas import CouchStartIn, EmptyIn, PlayerIn

router = APIRouter(prefix='/api/couch')


def _live(svc: Services):
    session = svc.couch.active()
    if session is None:
        raise HTTPException(400, 'No couch session is running')
    return session


@router.get('')
def view(svc: Services = Depends(services)):
    svc.couch.active()  # closes an expired session before reporting
    return svc.couch.view()


@router.get('/qr.svg')
def qr(svc: Services = Depends(services)):
    with client_errors():
        image = svc.couch.qr_svg()
    return Response(image, media_type='image/svg+xml')


@router.post('/start')
def start(body: CouchStartIn, svc: Services = Depends(services)):
    with client_errors():
        shortlist = svc.recommender.recommend(svc.ratings.all(), body.session.to_domain(), 'session', limit=8)
        return svc.couch.start(shortlist)


@router.post('/stop')
def stop(_body: EmptyIn, svc: Services = Depends(services)):
    svc.couch.stop()
    return svc.couch.view()


@router.post('/reveal')
def reveal(_body: EmptyIn, svc: Services = Depends(services)):
    _live(svc).reveal()
    return svc.couch.view()


@router.post('/player')
def player(body: PlayerIn, svc: Services = Depends(services)):
    session = _live(svc)
    with client_errors():
        session.control(body.action, body.id)
    return svc.couch.view()
