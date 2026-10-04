"""One error shape for every response: {"error": "<message a person can act on>"}."""
from contextlib import contextmanager
import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@contextmanager
def client_errors():
    """Domain validation (Session, ratings, commands...) raises ValueError; that is the caller's mistake: 400."""
    try:
        yield
    except (ValueError, TypeError) as error:
        raise HTTPException(400, str(error)) from error


def _describe(error):
    location = '.'.join(str(part) for part in error['loc'] if part != 'body')
    return f'{location}: {error["msg"]}' if location else error['msg']


def install(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException):
        return JSONResponse({'error': str(error.detail)}, error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, error: RequestValidationError):
        return JSONResponse({'error': '; '.join(_describe(e) for e in error.errors()[:3])}, 400)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(_request: Request, _error: sqlite3.Error):
        return JSONResponse({'error': 'Local storage is unavailable; retry or check the database path'}, 503)
