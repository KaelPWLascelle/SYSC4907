"""Profiles: who is watching, sign-in with an optional PIN, and the profile's data (export, import, delete).

docs/adr/0012-local-profiles.md. The sign-in cookie is HttpOnly and SameSite=Strict, and every
state-changing request already needs a same-origin JSON body (api/security.py), so another site cannot
switch profiles or read an export.
"""
from dataclasses import asdict
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from ...profiles import COOKIE, Locked, export_profile, plan_import
from ...repositories import hash_pin, merge_profile_data
from ...services import Services
from ..deps import Viewer, services, viewer
from ..errors import client_errors
from ..schemas import EmptyIn, ProfileIn, ProfileUpdateIn, SelectIn

router = APIRouter(prefix='/api/profiles')


def _listing(svc: Services, me: Viewer | None):
    counts = {p.id: len(svc.ratings.for_profile(p.id).all()) for p in svc.profiles.all()}
    return {'profiles': [{**asdict(p), 'ratings': counts[p.id]} for p in svc.profiles.all()],
            'current': ({'id': me.profile.id, 'name': me.profile.name, 'locked': me.profile.locked} if me else None),
            'chosen': bool(me and me.chosen)}


def _signed_in(response, svc: Services, profile_id):
    token = svc.sessions.start(profile_id)
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict', path='/')
    return response


def _attempt(svc: Services, profile_id, pin):
    """One rate-limited PIN check (429 while the profile is locked out)."""
    try:
        return svc.sessions.attempt(profile_id, lambda: svc.profiles.verify(profile_id, pin))
    except Locked as error:
        raise HTTPException(429, str(error)) from error


def _optional_viewer(request: Request):
    try:
        return viewer(request)
    except HTTPException:
        return None  # every profile has a PIN and nobody has signed in yet


@router.get('')
def listing(svc: Services = Depends(services), me: Viewer | None = Depends(_optional_viewer)):
    return _listing(svc, me)


@router.post('', status_code=201)
def create(body: ProfileIn, svc: Services = Depends(services)):
    with client_errors():
        profile = svc.profiles.create(body.name, body.pin)
    response = JSONResponse({'profile': asdict(profile)}, 201)
    return _signed_in(response, svc, profile.id)


@router.post('/signout')
def sign_out(_body: EmptyIn, request: Request, svc: Services = Depends(services)):
    svc.sessions.end(request.cookies.get(COOKIE))
    response = JSONResponse({'ok': True})
    response.delete_cookie(COOKIE, path='/')
    return response


@router.post('/{profile_id}/select')
def select(profile_id: int, body: SelectIn, svc: Services = Depends(services)):
    profile = svc.profiles.get(profile_id)
    if profile is None:
        raise HTTPException(404, 'Unknown profile')
    ok = _attempt(svc, profile_id, body.pin)
    if not ok:
        raise HTTPException(403, 'Wrong PIN' if body.pin else 'This profile needs its PIN')
    return _signed_in(JSONResponse({'profile': asdict(profile)}), svc, profile_id)


@router.put('/current')
def update(body: ProfileUpdateIn, svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    """Rename, or set or remove the PIN. Changing a PIN needs the current one."""
    # Check everything before changing anything, so a refused request changes nothing.
    if body.pin != 'unchanged' and me.profile.locked and not _attempt(svc, me.profile.id, body.current_pin):
        raise HTTPException(403, 'Enter the current PIN to change it')
    with client_errors():
        if body.pin not in ('unchanged', None):
            hash_pin(body.pin)  # validates the new PIN before the name changes
        if body.name is not None:
            svc.profiles.rename(me.profile.id, body.name)
        if body.pin != 'unchanged':
            svc.profiles.set_pin(me.profile.id, body.pin)
    return {'profile': asdict(svc.profiles.get(me.profile.id))}


@router.delete('/current')
def delete(request: Request, svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    """Deletes the profile with its ratings and history. Flicks keeps at least one profile."""
    if not me.chosen:
        raise HTTPException(403, 'Choose this profile before deleting it')
    with client_errors():
        svc.profiles.delete(me.profile.id)
    svc.sessions.forget_profile(me.profile.id)
    response = JSONResponse(_listing(svc, None))
    response.delete_cookie(COOKIE, path='/')
    return response


@router.delete('/current/data', status_code=204)
def clear_data(me: Viewer = Depends(viewer)):
    me.ratings.clear_all()
    me.history.clear_all()
    return Response(status_code=204)


@router.get('/current/export')
def export(svc: Services = Depends(services), me: Viewer = Depends(viewer)):
    document = export_profile(me.profile, me.ratings, me.history, svc.titles.by_id)
    # Headers are Latin-1: keep the file name ASCII whatever the profile is called.
    safe = ''.join(c if c.isascii() and c.isalnum() else '-' for c in me.profile.name).strip('-') or 'profile'
    return Response(json.dumps(document, ensure_ascii=False, indent=1), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="flicks-{safe}.json"'})


@router.post('/import')
async def import_profile(request: Request, mode: Literal['new', 'merge'] = Query('new'),
                         svc: Services = Depends(services)):
    """A JSON export (up to 2 MiB, enforced by the request guard): into a new profile, or merged into this one."""
    try:
        document = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, 'The file is not valid JSON') from None
    with client_errors():
        plan = plan_import(document, svc.catalog)
    if mode == 'merge':
        me = viewer(request)
        profile, response_profile = me.profile, None
    else:
        with client_errors():
            profile = svc.profiles.create(svc.profiles.unique_name(plan.name))
        response_profile = profile
    try:
        with client_errors():
            ratings, history = merge_profile_data(svc.profiles.db, profile.id, plan.ratings, plan.history)
    except HTTPException:
        if response_profile:
            svc.profiles.delete(profile.id)  # no half-imported profile is left behind
        raise
    body = {'profile': asdict(profile), 'ratings': ratings, 'history': history, 'skipped': plan.skipped}
    response = JSONResponse(body, 201 if response_profile else 200)
    return _signed_in(response, svc, profile.id) if response_profile else response
