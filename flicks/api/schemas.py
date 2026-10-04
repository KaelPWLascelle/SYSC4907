"""Request bodies. Strict types (no "1" -> 1 or true -> 1 coercion) and no unknown fields.

Range and enum rules live in the domain (core.Session, repositories) so there is one source of truth;
these models only check shape and types.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from ..core import Session

Number = StrictFloat | StrictInt


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class SessionIn(Body):
    mood: StrictStr = 'any'
    minutes: StrictInt = 120
    intensity: Number = 0.5
    novelty: Number = 0.3
    excluded_genres: list[StrictStr] = Field(default_factory=list)

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
