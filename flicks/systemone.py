"""System One decision client: typed questions in, validated calibrated answers out.

Speaks the TypeSafe ``/v1/systemone`` wire protocol that Jev (hosted), ``laya-serve`` and Kev
(self-hosted) all accept. Every backend returns that wire format, and every answer passes through
``parse_answers`` -- model output is untrusted input to this application.

Privacy rule enforced here, not by convention: text a user typed (``private=True``) may only be sent
to a backend running on this machine. Public catalogue text may go to any backend.
"""
from dataclasses import dataclass
import ipaddress
import json
import math
import re
from typing import Protocol
from urllib import error, request
from urllib.parse import urlsplit

TYPES = ('choice', 'score', 'noul')
MAX_QUESTIONS, MAX_OPTIONS, MAX_LEVELS, MAX_STATE_CHARS = 64, 100, 32, 50_000
NOUL_KEYS = ('false', 'true')


class SystemOneError(ValueError):
    """A backend was unreachable or returned something this application will not trust."""


class PrivacyError(PermissionError):
    """Refused to send user-authored text to a backend that is not on this machine."""


def choice(instructions, criteria):
    return {'type': 'choice', 'instructions': instructions, 'criteria': dict(criteria)}


def score(instructions, levels):
    return {'type': 'score', 'instructions': instructions, 'criteria': list(levels)}


def noul(instructions, no=None, yes=None):
    question = {'type': 'noul', 'instructions': instructions}
    if no or yes:
        question['criteria'] = {'false': no or 'no', 'true': yes or 'yes'}
    return question


def options(question):
    """Option keys in wire order: choice keys, score level indices as strings, or false/true."""
    if question['type'] == 'choice':
        return list(question['criteria'])
    if question['type'] == 'score':
        return [str(i) for i in range(len(question['criteria']))]
    return list(NOUL_KEYS)


def option_texts(question):
    """Human text for each option key (used by the lexical stand-in and by exports)."""
    kind, criteria = question['type'], question.get('criteria')
    if kind == 'choice':
        return {key: f'{key} {text}' for key, text in criteria.items()}
    if kind == 'score':
        return {str(i): text for i, text in enumerate(criteria)}
    labels = criteria or {'false': 'no', 'true': 'yes'}
    return {key: labels[key] for key in NOUL_KEYS}


def validate_questions(questions):
    if not isinstance(questions, dict) or not 0 < len(questions) <= MAX_QUESTIONS:
        raise ValueError(f'Questions must be an object with 1-{MAX_QUESTIONS} entries')
    for qid, q in questions.items():
        if not isinstance(qid, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', qid):
            raise ValueError(f'Question id {qid!r} must be lowercase snake_case')
        if not isinstance(q, dict) or q.get('type') not in TYPES:
            raise ValueError(f'Question {qid} needs a type of {", ".join(TYPES)}')
        if not isinstance(q.get('instructions'), str) or not q['instructions'].strip():
            raise ValueError(f'Question {qid} needs instructions')
        criteria = q.get('criteria')
        if q['type'] == 'choice':
            ok = isinstance(criteria, dict) and 2 <= len(criteria) <= MAX_OPTIONS
            if not ok or any(not isinstance(k, str) or not k or not isinstance(v, str) for k, v in criteria.items()):
                raise ValueError(f'Choice {qid} needs 2-{MAX_OPTIONS} named options with text')
        elif q['type'] == 'score':
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= MAX_LEVELS or any(not isinstance(v, str) or not v for v in criteria):
                raise ValueError(f'Score {qid} needs 2-{MAX_LEVELS} level descriptions')
        elif criteria is not None and (not isinstance(criteria, dict) or set(criteria) != set(NOUL_KEYS)):
            raise ValueError(f'Yes/no {qid} labels must use exactly the keys false and true')
    return questions


@dataclass(frozen=True)
class Answer:
    """One validated decision. ``value`` is the option key; for score it is the argmax level index."""
    type: str
    value: str
    probabilities: dict
    answer_confidence: float
    expected: float | None = None  # score: expected level index; noul: P(true)

    @property
    def normalized(self):
        """Score mapped to [0, 1]; P(true) for yes/no; P(value) for choice."""
        if self.type == 'score':
            return self.expected / (len(self.probabilities) - 1)
        if self.type == 'noul':
            return self.expected
        return self.probabilities[self.value]


def _distribution(qid, keys, raw):
    if not isinstance(raw, dict) or set(raw) != set(keys):
        raise SystemOneError(f'Answer {qid} has probabilities for the wrong options')
    values = {}
    for key in keys:
        p = raw[key]
        if type(p) not in (int, float) or not math.isfinite(p) or not -1e-6 <= p <= 1 + 1e-6:
            raise SystemOneError(f'Answer {qid} has an invalid probability')
        values[key] = min(max(float(p), 0.0), 1.0)
    total = sum(values.values())
    if not 0.98 <= total <= 1.02:  # wire values are rounded to 4 d.p.; anything further off is broken
        raise SystemOneError(f'Answer {qid} probabilities sum to {total:.3f}, not 1')
    return {key: v / total for key, v in values.items()}


def parse_answers(questions, response):
    """Validate a wire response against the questions that were asked."""
    if not isinstance(response, dict) or not isinstance(response.get('answers'), dict):
        raise SystemOneError('Response has no answers object')
    answers = response['answers']
    if set(answers) != set(questions):
        raise SystemOneError('Response answered a different set of questions')
    result = {}
    for qid, q in questions.items():
        raw, keys = answers[qid], options(q)
        if not isinstance(raw, dict) or raw.get('type') != q['type']:
            raise SystemOneError(f'Answer {qid} has the wrong type')
        if q['type'] == 'noul':
            p = raw.get('noul')
            if type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1:
                raise SystemOneError(f'Answer {qid} has an invalid yes probability')
            probs = {'false': 1 - float(p), 'true': float(p)}
            value = 'true' if p >= .5 else 'false'
            result[qid] = Answer('noul', value, probs, max(probs.values()), float(p))
            continue
        probs = _distribution(qid, keys, raw.get('probabilities'))
        value = max(keys, key=lambda k: (probs[k], -keys.index(k)))
        reported = raw.get('choice')
        if q['type'] == 'choice' and reported is not None and (
                not isinstance(reported, str) or reported not in probs or probs[reported] < probs[value] - 1e-3):
            raise SystemOneError(f'Answer {qid} reports a choice that is not its most probable option')
        expected = sum(int(k) * p for k, p in probs.items()) if q['type'] == 'score' else None
        result[qid] = Answer(q['type'], value, probs, probs[value], expected)
    return result


class Backend(Protocol):
    name: str
    local: bool

    def raw(self, state: str, questions: dict) -> dict: ...


def is_loopback(url):
    host = urlsplit(url).hostname or ''
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class HttpBackend:
    """Any server speaking POST /v1/systemone: laya-serve, Kev, or TypeSafe's hosted Jev API."""

    def __init__(self, base_url, api_key=None, timeout=10.0, model=None):
        parts = urlsplit(base_url)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            raise ValueError('System One URL must be http(s)://host[:port]')
        self.local = is_loopback(base_url)
        if parts.scheme == 'http' and not self.local:
            raise ValueError('Use https for a System One server that is not on this machine')
        self.url = base_url.rstrip('/')
        if not self.url.endswith('/v1/systemone'):
            self.url += '/v1/systemone'
        self.api_key, self.timeout, self.model = api_key, timeout, model
        self.name = f'{"local" if self.local else "remote"} System One ({parts.hostname})'

    def raw(self, state, questions):
        body = {'state': state, 'questions': questions}
        if self.model:
            body['model'] = self.model
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        req = request.Request(self.url, json.dumps(body).encode(), headers, method='POST')
        try:
            # A loopback backend must not be reached via http(s)_proxy: that would move user text off
            # the machine while the hostname still looks local. Remote backends honour the proxy.
            opener = request.build_opener(request.ProxyHandler({})) if self.local else request.build_opener()
            with opener.open(req, timeout=self.timeout) as reply:
                if reply.status != 200:
                    raise SystemOneError(f'System One server answered HTTP {reply.status}')
                return json.loads(reply.read(4 * 1024 * 1024))
        except error.HTTPError as exc:
            raise SystemOneError(f'System One server answered HTTP {exc.code}') from None
        except (error.URLError, TimeoutError, OSError) as exc:
            raise SystemOneError(f'System One server unreachable: {exc}') from None
        except json.JSONDecodeError:
            raise SystemOneError('System One server returned invalid JSON') from None


def state_text(state):
    """Canonical text of a state. Must match JSON.stringify in static/student.js for word features."""
    return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, separators=(',', ':'))


def tokens(text):
    words = re.findall(r'[a-z0-9]+', text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith('s') else w for w in words}


class LexicalBackend:
    """Deterministic keyword-overlap stand-in with the same wire format. NOT a model.

    It exists so the pipeline, tests and CI run offline, and as a floor any real System One model
    must beat. Probabilities are a softmax over option/state word overlap, so they are not calibrated.
    """
    name, local = 'lexical stand-in (not a model)', True

    def __init__(self, temperature=0.6):
        self.temperature = temperature

    def raw(self, state, questions):
        words = tokens(state_text(state))
        answers = {}
        for qid, q in questions.items():
            texts = option_texts(q)
            hits = {k: len(words & tokens(t)) for k, t in texts.items()}
            if q['type'] == 'noul' and not q.get('criteria'):
                hits = {'false': 0, 'true': 0}
            top = max(hits.values())
            exp = {k: math.exp((h - top) / self.temperature) for k, h in hits.items()}
            total = sum(exp.values())
            probs = {k: round(v / total, 6) for k, v in exp.items()}
            if q['type'] == 'noul':
                answers[qid] = {'type': 'noul', 'noul': probs['true']}
            else:
                answers[qid] = {'type': q['type'], 'probabilities': probs}
        return {'model': 'lexical', 'answers': answers}


class DecisionClient:
    def __init__(self, backend: Backend):
        self.backend = backend

    def decide(self, state, questions, *, private):
        """Ask typed questions about ``state``. ``private=True`` means a user wrote it."""
        if private and not self.backend.local:
            raise PrivacyError('User text is only sent to a System One model running on this machine')
        text = state_text(state)
        if not text.strip() or len(text) > MAX_STATE_CHARS:
            raise ValueError(f'State must be 1-{MAX_STATE_CHARS} characters')
        validate_questions(questions)
        return parse_answers(questions, self.backend.raw(state, questions))


def expected_calibration_error(confidences, correct, bins=10):
    """ECE over (answer_confidence, was-it-right) pairs, equal-width bins."""
    if len(confidences) != len(correct) or not confidences:
        raise ValueError('Need matching, nonempty confidence and correctness lists')
    total, error_sum = len(confidences), 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(confidences) if lo < c <= hi or (b == 0 and c == 0)]
        if idx:
            accuracy = sum(correct[i] for i in idx) / len(idx)
            confidence = sum(confidences[i] for i in idx) / len(idx)
            error_sum += len(idx) / total * abs(accuracy - confidence)
    return error_sum
