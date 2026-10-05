# Couch mode

Choose a film together. Phones on the same Wi-Fi scan a QR code on the TV, swipe through a shortlist
built from the host's scene, and the group pick appears on the TV. Any phone then works as a remote.
No app, no accounts, no internet.

```sh
.venv/bin/flicks --couch                              # then press "Start a couch session"
.venv/bin/flicks --couch --couch-host 192.168.1.23    # if the address is detected wrongly
```

Guests open the QR code's link (`http://<your-address>:8770/join#<code>`), or type the address and
the 8-character code shown on the TV. macOS asks once to allow incoming connections for Python.

## How it works

```
TV / laptop browser ── 127.0.0.1:8765 ──── host app (ratings, history, voice, commands)
                                              │ start · stop · reveal · player
                                              ▼
phones on the Wi-Fi ── <LAN address>:8770 ── guest app (only while a session runs)
                                              join · state · vote · remote · its own page
```

The guest app is a separate FastAPI app on its own port (`flicks/api/guest.py`); the session rules
are in `flicks/couch.py`. The host's ratings, history, voice and command routes do not exist on it,
so they cannot be reached from the network at all.

Phones and the TV poll every 1.5 seconds. A poll that started before the device's own action is
discarded, so a slow reply can never undo a vote or a remote press. A hidden tab pauses polling and
catches up as soon as it becomes visible.

## The remote

Choosing a title on a phone opens and plays it on the TV, when the title has a local file. Play,
pause and stop work in both directions: the phones control the TV, and the TV's own controls are
reported back to the phones. If the browser blocks autoplay because nobody clicked on the TV, the
player shows a "Press play" button rather than failing silently.

## Voting rule

Approval voting: the most yeses wins, then the fewest nos, and Flicks' own ranking breaks any
remaining tie. When every guest said yes, the title is flagged as a match. Least-misery (fewest nos
first) and average-score rules are natural variants to compare in a user study.

## Guarantees

Enforced in code and covered by `tests/test_couch.py` (including the guest app over a real socket)
and `web/src/guest/`:

- **Off by default.** Without `--couch`, the couch routes do not exist and nothing listens on the
  network.
- **Home network only.** Only private or loopback IPv4 addresses are accepted, never a public
  interface.
- **A code to join.** 8 characters from an alphabet with no look-alikes. After 10 wrong guesses it
  rotates, and the TV shows the new QR code. The QR code carries the code in the URL fragment, which
  browsers never send to a server, and the page removes it from the address bar.
- **Every request is authenticated.** Each guest gets a random 192-bit token, which the server keeps
  only as a SHA-256 hash. It travels in an `X-Flicks-Guest` header, so another web page cannot replay
  it.
- **Host and Origin checks on both servers,** against DNS rebinding and cross-site requests.
- **Guests see public catalogue fields only:** never the host's ratings, taste factors or editorial
  tags, and never another guest's votes. Results stay hidden until everyone has finished or the host
  presses Reveal.
- **Nothing is persisted.** Names and votes live in memory. Ending the session, or 3 hours passing,
  discards them and closes the guest app.

## Limits

- **Phones cannot use their microphones.** Browsers allow the microphone only over HTTPS or on
  localhost, and a home device cannot easily get a trusted certificate. Voice stays on the TV.
- **Campus and guest Wi-Fi** usually block device-to-device traffic (client isolation). Use a home
  network, a travel router or a phone hotspot.
- **Sessions do not survive a restart** or a change of address; guests scan again.

The QR encoder (`flicks/qr.py`) uses only the standard library: byte mode, error-correction level M,
versions 1–10. It was checked against Apple's CoreImage QR detector on 24 payloads, including every
version at full capacity.
