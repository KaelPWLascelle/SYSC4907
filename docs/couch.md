# Couch mode (prototype)

Phones on the same Wi-Fi join by scanning a QR code on the TV. Everyone swipes through a shortlist
built from the host's current scene, votes stay hidden until everyone is done, and the group pick
appears on the TV. Any guest's phone then works as a remote. No app, no accounts, no internet.

```sh
python3 -m flicks --couch                                   # then press “Start a couch session”
python3 -m flicks --couch --couch-host 192.168.1.23         # if the address is detected wrongly
flicks --couch                                              # same, after pip install .
```

Guests open the QR code's link (`http://<your-address>:8770/join#<code>`) or type the address and
the 8-character code shown on the TV. macOS asks once to allow incoming connections for Python.

## How it is wired

```
TV / laptop browser ── 127.0.0.1:8765 ── host server (unchanged: ratings, voice, commands)
                                              │ start / stop / reveal / player
                                              ▼
phones on the Wi-Fi ── <LAN address>:8770 ── guest server (only while a session runs)
                                              join · state · vote · remote · its own page
```

The guest server is a separate `ThreadingHTTPServer` (`flicks/couch.py`) with its own routes. The
host's ratings, history, voice and command routes do not exist on it, so they cannot be reached
from the network at all. Clients poll every 1.5 s, and a poll that started before the client's own
action is dropped, so a stale response cannot overwrite a newer state. A tab polls only while it is
visible, and it catches up when it becomes visible again.

## Guarantees the code enforces (tests in `tests/test_couch.py`)

- **Off by default.** Without `--couch`, the couch routes return 404 and nothing listens on the network.
- **Home network only.** Only private or loopback IPv4 addresses are accepted, never a public interface.
- **Code to join.** The 8-character code comes from an alphabet with no look-alike characters. After
  10 wrong guesses it rotates, and the TV shows the new QR code. The QR code puts the code in the URL
  fragment, which browsers never send to the server, and the page removes it from the address bar.
- **Every request is authenticated.** Each guest gets a random 192-bit token, which the guest
  server stores only as a SHA-256 hash. It travels in an `X-Flicks-Guest` header, so another web page
  cannot replay it.
- **Host and Origin checks on both servers.** These defeat DNS rebinding and cross-site requests.
  Cross-origin calls in either direction get 403.
- **Guests see public catalogue fields only:** never the host's ratings, taste factors, evidence
  terms or editorial tags. A guest never sees another guest's votes, and nobody sees results until
  everyone has finished or the host presses Reveal.
- **Nothing is persisted.** Names and votes live in memory. Ending the session (or 3 hours passing)
  discards them and closes the guest server.

## Voting rule

Approval voting: the most yeses wins, then the fewest nos. Flicks' own ranking breaks remaining
ties. When every guest said yes, the title is flagged as a match. This is the simplest rule the group
can understand at a glance. Least-misery (fewest nos first) and average-score rules are
straightforward variants worth comparing in the evaluation.

## Limits and next steps

- **Playback is a stub.** The remote changes a shared player state (`playing`/`paused`/`stopped`
  plus who pressed it) that the real video player will subscribe to.
- **The phone mic is not used.** Browsers allow the microphone only on HTTPS or localhost, and a home
  device cannot easily get a trusted certificate. Voice stays on the TV's mic for now.
- **Campus and guest Wi-Fi.** These networks usually block device-to-device traffic (client isolation).
  For demos, use a travel router or a laptop hotspot.
- **Front-end tests use a fake DOM** (`tests/couch-ui.test.mjs`): join, token handling, stale-poll
  protection, results, and loading in a background tab. Real phones were tried by hand. There's no
  automated cross-browser run.
- **The QR encoder (`flicks/qr.py`) is stdlib only.** It covers byte mode, level M and versions 1–10.
  It was checked against Apple's CoreImage QR detector on 24 payloads, including every version at full
  capacity and a screenshot of the live page.
