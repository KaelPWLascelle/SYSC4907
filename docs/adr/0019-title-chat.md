# 0019. A small language model inside Flicks: ask about a title, and a corner chat (experimental)

**Status:** Experimental · amends [0013](0013-local-llm.md) (adds an in-process runtime) and [0014](0014-ask-student.md)

## Context
ADR 0013's language model ran as a separate server (Ollama) and froze the team's 8 GB laptop at 4B
parameters. The proposal plans a much smaller model *inside* Flicks that answers questions about the
recommendations and the catalogue. The first question to test: after opening a title, can a viewer ask
"Who's in it?", "Is it scary?" or "Why this pick?" and get a grounded answer fast enough to feel like
chat?

## Decision
- **Runtime in process** (`flicks/assistant/embedded.py`): llama.cpp through `llama-cpp-python` (the
  `llm` extra), a GGUF file given with `--llm-file`. It loads on the first question, unloads after five
  idle minutes, runs one generation at a time, and drops `<think>` blocks. It is a `Chat` like the
  loopback client, so the narrator and the Ask agent can use it too.
- **Grounded in one title** (`flicks/assistant/title_chat.py`): the model sees that title's catalogue
  entry (description, genres, moods, intensity as "gentle/balanced/intense", runtime or seasons), the
  recommender's reasons, and the viewer's evening. Code works out what small models get wrong: whether it
  fits the time available, and that the age rating is unknown. Nothing else about the viewer is sent.
- **Checked after streaming**: answers stream word by word (`POST /api/ask-title`, newline-delimited
  JSON). A finished answer that names a catalogue title it was not given (and that neither the question
  nor the description names), or contains a link, is withdrawn and the viewer sees why.
- **Never ranks or acts.** Answers are text only; the panel says they come from a small model on this
  computer and can be wrong. It appears in the details sheet only when a model is configured.
- **A corner chat that ends in three picks** (`flicks/assistant/concierge.py`, `Concierge.tsx`): a round
  button in the bottom corner of Home opens a short conversation. It asks at most two questions (the mood,
  then the time) and reads every answer with the readers Ask already has: search's understanding of
  genres, moods, decades, lengths and films-or-series, the rules (which may change an earlier answer) and
  the Ask student (which only fills gaps), plus "like <title>". The recommender ranks with what it learned;
  the viewer gets three picks with posters and reasons, can open any of them, ask for others (shown titles
  are skipped), or make the settings the scene on Home. **Code decides what to ask and what to pick; the
  model only words the question and the pitch** from facts the code chose, and a reply that names a title
  it was not given falls back to Flicks' own sentence. So the chat works without any model, and a weak
  model can only make the wording worse, never the picks.

## Evaluation
Three titles (Arrival, Toy Story, Breaking Bad) × 8 questions: director, cast, plot, why it was picked,
scary or OK for kids, fits tonight, composer (not in the facts) and "better than Alien?" (a comparison
the facts cannot support). Apple M2, 8 GB, 4 threads. Scored by hand: right and grounded (including a
correct "Flicks doesn't know"), partly right or true but not from the facts, wrong.

| Model (Q4_K_M) | File | Added memory | Metal: first words / full answer (median) | CPU only: first words / full (median, worst) | Right / partly / wrong |
|---|---:|---:|---|---|---|
| Qwen2.5 0.5B Instruct | 0.4 GB | 0.5 GB | 0.03 s / 0.37 s | 0.09 s / 0.33 s (1.1 s) | 14 / 6 / 4 |
| Llama 3.2 1B Instruct | 0.8 GB | 0.9 GB | 0.04 s / 0.28 s | 0.12 s / 0.39 s (2.4 s) | 17 / 3 / 4 |
| Qwen2.5 1.5B Instruct | 1.0 GB | 1.1 GB (1.4 GB CPU) | 0.06 s / 0.70 s | 0.14 s / 1.0 s (9.7 s) | 16 / 4 / 4 |

The first question about a title is the slow one: the model reads about 700 tokens of facts (0.7 s on
Metal, 2 to 6 s on the CPU). Follow-ups reuse that work. Loading takes 1 to 3 s from a warm disk and up to
10 s the first time.

What goes wrong: age suitability (invented "PG-13", "suitable for kids"), answers to "Why this pick?" that
pad the reasons with plot, and true facts the catalogue does not hold (Randy Newman scored Toy Story).
Telling the model the age rating is unknown fixed the worst of it. Llama 3.2 1B often starts with a stray
"You." and once said "You liked Breaking Bad" as the reason for Breaking Bad.

**Choice for now: Qwen2.5 1.5B Instruct** (Apache 2.0, so it can ship with Flicks). It answers factual
questions best and is honest about gaps, within the proposal's 1.5 GB and 5 s targets on Metal; on a CPU
its long answers can exceed 5 s. Qwen2.5 0.5B is the fallback for low-memory machines. None reaches the
proposal's 95% groundedness target yet.

## Next
- Answer the predictable questions in code (fits tonight, why this pick, who directed it, when the
  description says), like the Ask rules, and keep the model for open questions.
- Grow the question set to about 50 across many titles, and score groundedness automatically where the
  answer is in the facts.
- Try Qwen3 1.7B and Gemma 3 1B, and the same model for narrated explanations.
- Other places the same pattern fits (code decides, the model words it): a spoken summary of "Your
  taste", a one-line reason on each Discover card, and an icebreaker in couch mode ("Two of you liked
  heist films…").

## Consequences
- `pip install 'flicks[llm]'` builds or downloads llama.cpp (prebuilt Metal wheels were corrupt on
  2026-10-22; building from source needs CMake, installable with pip). Model files are downloaded by the
  user, about 1 GB, and are not redistributed by Flicks.
- Without `--llm-file` nothing changes: no panel, no extra memory.
