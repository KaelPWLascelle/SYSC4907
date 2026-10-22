"""Request bodies. Strict types (no "1" -> 1 or true -> 1 coercion) and no unknown fields.

Range and enum rules live in the domain (core.Session, repositories) so there is one source of truth;
these models only check shape and types.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

from ..core import DEFAULT_MIX, Session

Number = StrictFloat | StrictInt


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class SessionIn(Body):
    mood: StrictStr = 'any'
    minutes: StrictInt = 120
    intensity: Number = 0.5
    novelty: Number = 0.3
    excluded_genres: list[StrictStr] = Field(default_factory=list)
    kind: StrictStr = 'any'
    playable: StrictBool = False
    mix: list[Number] = Field(default_factory=lambda: list(DEFAULT_MIX))

    def to_domain(self):
        return Session(**self.model_dump())  # raises ValueError for out-of-range values


class FeedbackIn(Body):
    id: StrictStr
    value: StrictInt


class RecommendIn(Body):
    session: SessionIn = Field(default_factory=SessionIn)
    mode: Literal['session', 'baseline'] = 'session'


class CommandIn(Body):
    text: StrictStr
    session: SessionIn = Field(default_factory=SessionIn)


class ProgressIn(Body):
    position_seconds: Number
    duration_seconds: Number


class CouchStartIn(Body):
    session: SessionIn = Field(default_factory=SessionIn)


class PlayerIn(Body):
    action: StrictStr
    id: StrictStr | None = None


class EmptyIn(Body):
    pass


class ProfileIn(Body):
    name: StrictStr
    pin: StrictStr | None = None


class SelectIn(Body):
    pin: StrictStr | None = None


class ProfileUpdateIn(Body):
    name: StrictStr | None = None
    pin: StrictStr | None = 'unchanged'   # a new PIN, None to remove it, or leave it as it is
    current_pin: StrictStr | None = None


class DiscoverIn(Body):
    session: SessionIn = Field(default_factory=SessionIn)
    seen: list[StrictStr] = Field(default_factory=list, max_length=300)  # newest last; keeps the body under 8 KiB
    online: StrictBool = False   # the viewer allows trailers from YouTube
    limit: StrictInt = Field(8, ge=1, le=20)


class PickIn(Body):
    session: SessionIn = Field(default_factory=SessionIn)
    pool: Literal['picks', 'anything'] = 'picks'


class ExplainIn(Body):
    id: StrictStr
    session: SessionIn = Field(default_factory=SessionIn)


class TurnIn(Body):
    question: StrictStr = Field(max_length=300)
    answer: StrictStr = Field(max_length=1000)


class AskTitleIn(Body):
    id: StrictStr
    question: StrictStr = Field(min_length=1, max_length=300)
    session: SessionIn = Field(default_factory=SessionIn)
    history: list[TurnIn] = Field(default_factory=list, max_length=6)


class MessageIn(Body):
    role: Literal['user', 'assistant']
    text: StrictStr = Field(max_length=600)


class ConciergeIn(Body):
    messages: list[MessageIn] = Field(min_length=1, max_length=12)
    session: SessionIn = Field(default_factory=SessionIn)
    shown: list[StrictStr] = Field(default_factory=list, max_length=30)
