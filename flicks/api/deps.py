"""FastAPI dependencies."""
from dataclasses import dataclass

from fastapi import HTTPException, Request

from ..profiles import COOKIE
from ..repositories import Profile, RatingsRepository, WatchHistoryRepository
from ..services import Services


def services(request: Request) -> Services:
    return request.app.state.services


def catalogue_id(content_id: str, svc: Services) -> str:
    if content_id not in svc.ids:
        raise HTTPException(404, 'Unknown content ID')
    return content_id


@dataclass(frozen=True)
class Viewer:
    """The profile a request acts for, with its ratings and history."""
    profile: Profile
    chosen: bool            # signed in with the cookie, rather than the default profile
    ratings: RatingsRepository
    history: WatchHistoryRepository


PROFILE_HEADER = 'x-flicks-profile'


def viewer(request: Request) -> Viewer:
    """The signed-in profile, or else the first profile without a PIN. PIN profiles are never a default.

    The page sends the profile it was loaded for. If that is no longer who the cookie says (Flicks
    restarted, or another tab switched profiles), the request is refused rather than saved to the wrong
    person's ratings.
    """
    svc = services(request)
    signed_in = svc.sessions.profile(request.cookies.get(COOKIE))
    profile = svc.profiles.get(signed_in) if signed_in is not None else None
    chosen = profile is not None
    profile = profile or svc.profiles.default()
    if profile is None:
        raise HTTPException(401, 'Choose a profile to continue')
    expected = request.headers.get(PROFILE_HEADER)
    if expected is not None and expected != str(profile.id):
        raise HTTPException(409, 'The profile on this page is no longer signed in. Choose who is watching again.',
                            headers={'X-Flicks-Profile-Changed': '1'})
    return Viewer(profile, chosen, svc.ratings.for_profile(profile.id), svc.history.for_profile(profile.id))
