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
  model can only make the wording worse, never the picks. With a model it is now open (below).

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

**First choice (2026-10-22): Qwen2.5 1.5B Instruct.** It answered factual questions best and was honest
about gaps, within the proposal's 1.5 GB and 5 s targets on Metal.

### Qwen3.5 (2026-10-28)
The Qwen3.5 small models (March 2026, Apache 2.0) run on the same llama.cpp (llama-cpp-python 0.3.36).
The same 24 questions, now through the app's own prompt and answer check
(`python -m flicks.assistant.title_chat_eval MODEL.gguf [--cpu]`), with Qwen2.5 1.5B re-run alongside.
Same machine; scored by hand as above.

| Model (Q4_K_M) | File | Added memory, Metal (CPU) | Metal: first words / full answer (median, worst) | CPU only: first words / full (median, worst) | Right / partly / wrong |
|---|---:|---:|---|---|---|
| Qwen2.5 1.5B Instruct | 1.0 GB | 1.1 GB (2.0 GB) | 0.06 s / 0.70 s (2.1 s) | 0.08 s / 1.2 s (2.6 s) | 14 / 7 / 3 |
| Qwen3.5 0.8B | 0.6 GB | 0.8 GB (1.3 GB) | 0.31 s / 0.62 s (1.0 s) | 1.2 s / 1.6 s (2.4 s) | 15 / 3 / 6 |
| **Qwen3.5 2B** | 1.4 GB | 1.4 GB (2.3 GB) | 0.69 s / 1.4 s (2.1 s) | 2.5 s / 3.5 s (4.2 s) | **21 / 3 / 0** |

- **Qwen3.5 2B gets nothing wrong.** Asked whether a title is OK for kids, it says Flicks doesn't know the
  age rating, where Qwen2.5 1.5B still answered "suitable for kids" for Arrival and Toy Story. "Why was this
  recommended?" names the liked films ("because you liked Interstellar and Contact") instead of padding with
  plot, and it declines the Alien comparison. Its partly right answers add true facts that are not in the
  catalogue (Breaking Bad's meth cooking), and once it used markdown italics.
- **Qwen3.5 0.8B is not an upgrade:** it named Steven Spielberg as Breaking Bad's director, rated Toy Story
  "for kids aged 6 and up" and judged Breaking Bad "better than Alien".
- **Every answer starts later.** Qwen3.5 reads the title's facts again for each question (0.7 s on Metal,
  2.5 s on the CPU) where Qwen2.5 reuses them for follow-ups, likely because Qwen3.5's recurrent layers
  cannot reuse part of a cached prompt. Still well within 5 s, including the CPU's worst case.
- **No thinking.** With the `/no_think` the prompts already add for Qwen3 names, no answer opened a
  `<think>` block.
- **Memory is tight:** 1.43 GB added on Metal against the 1.5 GB target. On the CPU every model, Qwen2.5
  included, adds more than 1.5 GB.

**Choice now: Qwen3.5 2B** (Apache 2.0). It is the first model with no wrong answers on this set, within the
1.5 GB and 5 s targets on Metal and within 5 s on the CPU. Qwen2.5 0.5B remains the fallback for
low-memory machines (`--llm-file`). Twenty-four questions are too few to claim the proposal's 95%
groundedness target.

### An open corner chat (2026-10-28)
With only two questions to word, the chat could not answer "Do we have any RDJ movies?", "Iron Man", "Pixar"
or "what can you do?", and the Ask student read "Pixar" and "anime" as *no animation*. We accept a little
less accuracy in the wording for a chat that takes any question. Following the pattern that works for
1–4B models (one call to plan, code to act, one call to answer; TinyAgent, "Small LLMs Are Weak Tool
Learners"), with a model the chat now runs `flicks/assistant/open_chat.py`:
- **Plan:** one reply held to a JSON schema by llama.cpp's grammar: `find` (words to search, such as a
  person, franchise or topic, and/or a mood, genres, length, decade, films or series), `similar`, `about`
  one title, `previous` (the titles just shown) or `help`. Flicks' own readers overrule it for lengths
  ("an hour and a half"), decades, films or series and genres to avoid, and filters the viewer did not say
  are dropped: small models fill optional fields.
- **Act, in code:** search on the titles' own words (descriptions name casts and directors), titles
  most like one, the recommender's picks for a mood (as before), or a title's full entry. Results are
  ordered by Flicks' ranking, so "Robert Downey Jr." starts with Iron Man.
- **Answer:** the model writes a few sentences from the results only, told why each matched. Each sentence
  is checked when it finishes and shown only if every title it names is in the results, a title the
  search matched, or one the viewer said. Nothing shown is taken back, and the cards are always the tool's
  real titles. If the model cannot plan (busy or failed), the two questions above still work.

On 32 requests and 4 follow-ups (`python -m flicks.assistant.open_chat_eval MODEL.gguf`, empty profile,
Metal), Qwen3.5 2B answered about 27 of the 32 well, judged by hand, and all 4 follow-ups (the old chat
about 8 of the 32): Iron
Man found its sequels and the Avengers, RDJ his films, Pixar its films, Star Wars the original trilogy, "which of
those is the shortest?" the right one. The median reply took 4.0 s and the slowest 6.0 s, including a
2.4 s model load. The wording is less reliable than the cards: it sometimes adds a wrong detail (it gave The
Prestige Inception's running time), and a mood alone on an empty profile still gives crowd favourites.

## Next
- Answer the predictable questions in code (fits tonight, why this pick, who directed it, when the
  description says), like the Ask rules, and keep the model for open questions.
- Measure the open chat on the CPU, and score its answers automatically where the results hold the answer.
- Grow the question set to about 50 across many titles, and score groundedness automatically where the
  answer is in the facts.
- Try Gemma 3 1B, and the same model for narrated explanations.
- Other places the same pattern fits (code decides, the model words it): a spoken summary of "Your
  taste", a one-line reason on each Discover card, and an icebreaker in couch mode ("Two of you liked
  heist films…").

## Consequences
- `pip install 'flicks[llm]'` builds or downloads llama.cpp (prebuilt Metal wheels were corrupt on
  2026-10-22; building from source needs CMake, installable with pip). Model files are downloaded by the
  user, about 1.4 GB, and are not redistributed by Flicks.
- Without `--llm-file` nothing changes: no panel, no extra memory.
