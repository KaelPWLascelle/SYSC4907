# Voice commands

Flicks can transcribe spoken requests on the device with Whisper and turn them into the same
reviewed changes as typed requests. Voice is optional: typing works without any of this.

```
Microphone or audio file (≤ 30 s, ≤ 5 MiB)
  → decoded to mono 16 kHz in memory (PyAV)
  → transcribed on the CPU (faster-whisper, int8, speech-activity filtering)
  → editable transcript
  → preview of exactly what will change
  → Apply
```

Whisper is the only neural model in this path. Interpreting the transcript is done by a bounded,
rule-based parser, not a chat model; an optional local [System One](system-one.md) model can help
with requests the rules don't recognize.

## Setup

From the repository root, after the [quick start](../README.md#quick-start):

```sh
.venv/bin/pip install -e ".[voice]"
.venv/bin/python scripts/download_voice_model.py
.venv/bin/flicks --voice-model .local/models/whisper-base.en
```

The download script fetches `Systran/faster-whisper-base.en` at a pinned revision and records the
revision and file SHA-256 hashes in `flicks-model.json`. That is the only network step. At runtime
Flicks loads only the directory you pass, with `local_files_only=True`; a missing or incomplete
model produces setup guidance, never a download. Set `HF_HUB_OFFLINE=1` to confirm Flicks does not
need the model hub after setup. Models, recordings and `.local/` are excluded from git.

For a smaller, less accurate model:

```sh
.venv/bin/python scripts/download_voice_model.py --model tiny.en
.venv/bin/flicks --voice-model .local/models/whisper-tiny.en
```

No system FFmpeg is needed; PyAV bundles its own decoder. `requirements-voice-tested.txt` pins the
exact versions CI tests against.

## Using voice

1. Press **Record command** and allow microphone access.
2. Speak a short English request, then press **Stop & transcribe**. Recording stops on its own just
   before 30 seconds.
3. Check the transcript, correct any words, and press **Preview**.
4. Read exactly what Flicks proposes, then press **Apply**.

You can also choose an audio file with **Use a recording**, or press <kbd>/</kbd> and type. If
microphone access is denied or the browser cannot record, typing and audio files still work.

There is no background listening, wake word or continuous streaming. Leaving the page stops the
microphone. **Cancel** discards a recording or an in-flight transcription; a transcription that has
already started on the server may finish, but its result is never applied. One transcription runs
at a time; a second request is asked to retry.

## Supported requests

| Say or type | Proposed change |
|---|---|
| "Something relaxing under ninety minutes, low intensity, no horror" | Relaxing; up to 89 minutes; intensity 20%; avoid horror |
| "Curious, two hours, surprise me" | Curious; 120 minutes; discovery 90% |
| "An hour and a half, familiar" | 90 minutes; discovery 10% |
| "No horror" | Avoid horror |
| "Allow all genres" / "Clear exclusions" | Avoid nothing |
| "Like Arrival" / "I liked Arrival" | Like *Arrival* |
| "Dislike Alien" / "I did not like Alien" | Pass on *Alien* |
| "Clear my rating for Arrival" | Remove that rating |
| "Show recommendations" | Refresh with the current scene |

- **Time** is in whole minutes. "Under 90" means strictly below, so up to 89; "90 minutes" and "at
  most 90 minutes" include 90. Use one duration per request.
- **Intensity:** low, medium and high mean 20%, 50% and 90%.
- **One mood per request.** Settings you don't mention stay as they are. A new "no …" request
  replaces the list of avoided genres.
- **Titles must match exactly** (ignoring punctuation and accents). Flicks never guesses from "like
  it", similar spellings or ambiguous matches, so a misheard word cannot silently become a rating.
- **"Flicks"** at the start of a request is ignored ("Hey Flicks, no horror").

## Privacy

Audio goes only to the Flicks server on this machine. It is decoded and transcribed in memory and is
never written to disk by Flicks. Transcripts are not stored in the database or the server logs. Only
applied ratings persist. Flicks does not use the browser's built-in speech recognition, which may
send audio to a remote service.

Preview never changes anything. Apply re-parses the text on the server and goes through the same
validated operations as the rest of the app; a request the parser does not understand cannot be
applied.

## Tests

```sh
.venv/bin/python -m pytest tests/test_voice.py   # audio decoding runs when the voice extras are installed
npm --prefix web test                             # the recording and command state machine
```

The interface tests use simulated microphones and permissions, never a real device. CI does not
download model weights; real transcription is checked separately (see [evaluation](evaluation.md)).

The parser's contract is small: `CommandInterpreter.parse(text)` returns a session change, an
exact-title rating, or "unknown". Any replacement (for example a local tool-calling model) must keep
that contract, its output validation, and the preview step.

References: [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[Whisper Base English](https://huggingface.co/Systran/faster-whisper-base.en),
[MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder).
