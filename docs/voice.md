# Flicks voice commands (v0.2)

Flicks now has an optional on-device speech pipeline:

```
Browser microphone or audio file
  → MediaRecorder audio (maximum 30 seconds / 5 MiB)
  → local Python / PyAV decode to mono 16 kHz samples
  → faster-whisper / CTranslate2 CPU int8 transcription + speech activity filtering
  → editable transcript
  → deterministic command preview
  → Apply button
  → existing validated session/rating operations and recommendation engine
```

Whisper is the neural AI model in this release. Command interpretation is a
bounded local rules parser, not an LLM or a general conversational agent. Ratings
still personalize TF-IDF; session ranking remains transparent and deterministic.
No Ollama service, FunctionGemma model, or cloud account is required.

## Setup

The base app and typed commands still need only Python 3.10+. Voice was tested
with Python 3.12 on Apple Silicon macOS. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-voice.txt
.venv/bin/python scripts/download_voice_model.py
.venv/bin/python -m flicks --db .local/demo.sqlite3 --voice-model .local/models/whisper-base.en
```

Windows equivalents use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.
Open <http://127.0.0.1:8765>. Stop the previous Flicks process first if that port is
occupied, or add `--port 8766`. No system FFmpeg installation is required; PyAV
provides decoding. `requirements-voice-tested.txt` records the exact dependency
versions from the tested macOS/Python 3.12 environment; it is not a claim that
those versions support every Python/OS combination.

The setup script downloads `Systran/faster-whisper-base.en` from a pinned upstream
revision and records source revision plus file SHA-256 values in `flicks-model.json`.
It needs internet once. Runtime loads only the explicitly supplied local directory
with `local_files_only=True`. Missing/incomplete files produce setup guidance,
not an automatic download. `.venv`, `.local`, recordings, and model weights are
excluded from Git. The model is not distributed with the repository.

For a smaller, less accurate option:

```sh
.venv/bin/python scripts/download_voice_model.py --model tiny.en
.venv/bin/python -m flicks --voice-model .local/models/whisper-tiny.en
```

To verify runtime independence from Hugging Face, set `HF_HUB_OFFLINE=1` when
starting Flicks. The application does not need the model hub after setup.

## Using voice

1. Press **Record command** and allow microphone access in your browser/OS.
2. Speak a short English command. Press **Stop & transcribe** when finished.
   Capture stops just before 30 seconds to leave room for the final audio frame.
3. Check the transcript. Correct any words, then press **Preview command** again.
4. Read the exact settings/rating Flicks proposes. Press **Apply to Flicks**.

You can also choose an audio file or type directly. Microphone permission denial,
missing hardware, unsupported browser capture, and unavailable models leave the
text path usable. Browser and OS microphone permissions may both be needed. If an
embedded browser cannot provide microphone access, open the same local address
in a supported desktop browser or use a recording file.

No background listening, wake word, continuous streaming, speech synthesis, or
media playback is implemented. Closing/leaving the page stops active microphone
tracks. Cancel discards the recording or cancels the browser's pending request;
an already-started short server inference may finish, but cannot apply a command.
A single nonblocking inference lock prevents simultaneous model runs. Subsequent
requests receive a retry message. Browser requests time out after 120 seconds;
there is no hard termination of an in-process native model inference.

## Supported commands

| Say or type | Proposed change |
|---|---|
| “Something relaxing under ninety minutes, low intensity, no horror” | Relaxing; maximum 89 minutes; intensity 20%; exclude horror |
| “Curious, two hours, surprise me” | Curious; 120 minutes; novelty 90% |
| “An hour and a half, familiar” | 90 minutes; novelty 10% |
| “No horror” | Set excluded genres to horror |
| “Allow all genres” / “Clear exclusions” | Clear genre exclusions |
| “Like Arrival” / “I liked Arrival” | Save a positive rating |
| “Dislike Alien” / “I did not like Alien” | Save a negative rating |
| “Clear my rating for Arrival” | Remove that rating |
| “Show recommendations” | Refresh using the current settings |

Time is whole minutes. “Under/less than 90” is strictly below 90, so the maximum
integer runtime is 89; “90 minutes” and “at most 90 minutes” include 90.
Use one duration (e.g. 90 minutes instead of 1 hour 30 minutes). One mood per
request. Low/medium/high intensity map to 20/50/90%. Unmentioned session controls
remain unchanged. A new exclusion command replaces the current exclusion list;
the preview lists exactly what it will set. Exclusions apply in both ranking modes.

Titles must match a unique catalogue title after punctuation/accent normalization.
Flicks does not guess from “like it”, similar spellings, or multiple title matches.
This is intentional: speech errors must not silently become ratings. General chat,
compound rating commands, and unsupported negation may be rejected. Recognized
session phrases are extracted and listed; other wording is not interpreted. Always
review the proposed action. Typing works identically to a speech transcript.

## Privacy and boundaries

Audio is uploaded only to the local loopback Flicks process. It is decoded and
transcribed in memory, not written to an audio file by Flicks. Transcripts are not
stored in SQLite or server request logs. They remain visible in the current page
until edited/reloaded. Only applied ratings persist; session controls still reset
on reload. A recording file you upload already exists on disk and is not deleted.
The explicit model download is the only network setup step; Flicks does not use
browser SpeechRecognition, which may rely on a remote speech service.

Preview endpoints never alter ratings. Apply reparses the text server-side and
uses the existing validated domain operations. Unknown commands cannot be applied.
This review step is a product behavior for imperfect speech recognition, not a
substitute for authentication if the app is later deployed beyond loopback.

## Tests and extension points

```sh
python3 -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s tests -v
node --test tests/voice-ui.test.mjs
```

The first command skips optional audio-decoding tests when voice dependencies are
absent. The second includes them. Node 24 runs the isolated browser-state tests;
it is needed for those tests only, not to run Flicks. The UI tests use fake audio
and permissions, never the machine's microphone. Model weights are not downloaded
by CI. Actual inference is validated separately with generated speech samples.

`LocalWhisper.transcribe(bytes)` returns text/timing, with no application side effects.
`CommandInterpreter.parse(text)` returns a bounded session patch, exact-title feedback,
or an unknown result. A future FunctionGemma/local tool model can implement that
contract, with output validation, explicit review, and deterministic fallback. A
future context provider can supply timestamped, consented sensor observations;
manual user settings should take precedence. Voice transcription itself must never
silently infer alertness or other sensitive characteristics.

Implementation references:
[faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[Whisper Base English converted model](https://huggingface.co/Systran/faster-whisper-base.en),
[MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder).
