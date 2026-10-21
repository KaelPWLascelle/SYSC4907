# 0013. An optional local language model: an Ask agent and narrated explanations, never the ranker

**Status:** Superseded at runtime by [0014](0014-ask-student.md): optional, off by default · amends [0001](0001-local-first.md)

> On the team's 8 GB laptop the 4B model froze the computer (swap) and took 5 to 20 s per request.
> ADR 0014 replaces it with a distilled classifier; this record stays as the design for machines with
> memory to spare.

## Context
The proposal promises explainable recommendations and natural requests ("something like Arrival but
shorter, nothing scary"). The rule-based parser and System One (docs/system-one.md) handle known
phrasings; free-form requests fall through to a keyword search. Language models read such requests
well, but they are slow on a laptop, can invent titles, and vary from run to run.

## Decision
Use a language model **only where its strengths matter and its failures are contained**, always on
this machine, always optional.

- **Runtime:** any OpenAI-compatible server on loopback (Ollama, llama.cpp's `llama-server`, LM
  Studio), chosen with `--llm-url` and `--llm-model`. `LocalChat` refuses any non-loopback address
  before a request and bypasses proxies, like the System One client. Without it, Flicks works exactly as
  before.
- **Ask agent, the third tier** (`flicks/assistant/agent.py`). Requests go to the cheapest reader that can
  answer: the rules (microseconds), then System One if configured (hundreds of milliseconds), then the
  agent (seconds). The agent is consulted only when nothing specific was understood (an unrecognised
  request, a plain keyword search, or a title the rules could not find). It may call one read-only tool,
  `lookup_title`, and must finish with one proposal of the kinds the rules already produce: a scene
  change, a search, titles like one it looked up, or a title to play. Flicks validates the proposal
  like a manual control (`Session`, known genres, only IDs it looked up) and sends errors back for
  another try, up to four turns. The user still previews and applies it. It cannot rate, delete or
  download anything. Preview and apply share a cache, so apply gets exactly what was previewed.
- **Narrated explanations** (`flicks/assistant/narrator.py`, `POST /api/explain`). The ranking's factors already
  explain each score exactly; the model only rewords them. It is given the pick's facts (title, genres,
  the catalogue's first sentence, the liked films that led to it, the strongest factors, the scene) and
  nothing else about the user. A reply that names a catalogue title it was not given, links somewhere,
  states a percentage or runs long is discarded, and the interface keeps its template reasons. Replies
  are cached per profile and facts, and the sheet never waits for one.
- **Not the ranker.** The model never scores or orders titles.

## Alternatives considered
- **An LLM as the recommender:** can recommend titles that are not in the catalogue or misremember the
  user's ratings; takes seconds to a minute per list on a laptop; cannot be evaluated with NDCG@10 like
  the ranker; and its explanations would no longer add up to the score.
- **Native tool calling:** small local models follow a one-JSON-object-per-turn protocol more reliably
  than function-calling formats, and the protocol works with every OpenAI-compatible runtime.
- **A hosted model:** faster and stronger, but user text would leave the device (ADR 0001).

## Evaluation
`python -m flicks.assistant.agent_eval` runs 11 team-written requests that the rules cannot read (none are the
prompt's examples) on the bundled catalogue. On an Apple M2 with 8 GB (Ollama, 2026-10-19):

| Model | Passed | Median / max latency |
|---|---:|---:|
| qwen3.5:4b (default) | 10 / 11 | 4.2 / 5.2 s |
| qwen3.5:2b | 6 / 11 | 1.8 / 8.3 s |

The 4B model's miss was "what time is it in Tokyo": it declined, but the rules' keyword search for "time" and "tokyo" stood instead of a plain "nothing matched". With the
9,349-title MovieLens catalogue and podcasts, a request took 9 to 19 s on the same machine: the
narrator and the agent share the runtime's single prompt cache, so each switch re-reads a ~500-token
prompt. It is off the critical path (rules answer first), but faster hardware or
`OLLAMA_NUM_PARALLEL=2` helps.

## Consequences
- The interface says when text was written or planned by the local model.
- Every new agent tool needs validation and a test that the model cannot bypass it.
