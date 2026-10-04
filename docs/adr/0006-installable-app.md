# 0006. Installable web app (manifest), no service worker

**Status:** Accepted

## Context
An installed app window (dock/taskbar icon, no browser chrome) makes the TV/laptop experience feel
native. Browsers treat `http://127.0.0.1` as a secure context, so the host app can be installed.
Couch guests use `http://<LAN address>`, which is not a secure context, so phones cannot install it.

## Decision
- Ship a web app manifest and icons for the host app.
- Do not ship a service worker. The server is always local, so offline caching adds nothing, and
  stale cached assets are a common source of hard-to-reproduce bugs.
- Electron/Tauri are out of scope: bundling Python inside them costs a lot for little gain.

## Consequences
Install works in Chromium browsers (Chrome, Edge, Arc). Safari users add it to the Dock instead.
Revisit a service worker only if a real offline need appears.
