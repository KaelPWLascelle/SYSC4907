"""Typed and spoken commands: preview what the assistant understood, then apply it."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ...core import Session
from ...services import Services
from ...voice import VoiceBusy, VoiceUnavailable
from ..deps import services
from ..errors import client_errors
from ..schemas import CommandIn

router = APIRouter()


def _parse(body: CommandIn, svc: Services):
    with client_errors():
        return body.session.to_domain(), svc.interpreter.parse(body.text)


@router.post('/api/command/preview')
def preview(body: CommandIn, svc: Services = Depends(services)):
    session, command = _parse(body, svc)
    return {'command': command, 'session': asdict(session), 'feedback': svc.ratings.all()}


@router.post('/api/command/apply')
def apply(body: CommandIn, svc: Services = Depends(services)):
    session, command = _parse(body, svc)
    if command['intent'] == 'unknown':
        raise HTTPException(400, command['summary'])
    with client_errors():
        if command['intent'] == 'feedback':
            svc.ratings.set(command['id'], command['value'])
        else:
            session = Session(**{**asdict(session), **command['patch']})
    return {'command': command, 'session': asdict(session), 'feedback': svc.ratings.all()}


@router.post('/api/transcribe')
async def transcribe(request: Request, svc: Services = Depends(services)):
    # Content type and size are enforced by the request guard (RawBody policy for this path).
    data = await request.body()
    if not data:
        raise HTTPException(400, 'Audio must contain 1 byte to 5 MiB')
    try:
        return await run_in_threadpool(svc.speech.transcribe, data)  # CPU-bound; keep the event loop free
    except VoiceUnavailable as error:
        raise HTTPException(503, str(error)) from error
    except VoiceBusy as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
