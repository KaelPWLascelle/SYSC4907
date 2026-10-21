# 0012. Local profiles, and a profile's data moves as a file

**Status:** Accepted · amends [0003](0003-sqlite-migrations.md)

## Context
A household shares one Flicks, but taste is personal: one person's horror likes should not shape
another's picks. People also change computers and want to take their taste with them. ADR 0001 rules
out the usual answer, an online account, because it would move ratings and history off the device.

## Decision
- **Profiles are local.** Migration 3 adds a `profiles` table (name, optional PIN) and a `profile_id`
  on `feedback` and `watch_history`. Existing rows move to profile 1, "Me", so upgrading changes nothing
  for a single user. Deleting a profile removes its rows through the foreign keys.
- **Choosing a profile** sets a random sign-in token in an HttpOnly, SameSite=Strict cookie. Tokens
  live in memory, so restarting Flicks signs everyone out. A request without one acts for the first
  profile that has no PIN; a profile with a PIN is never that default. Five wrong PINs lock a profile
  for a minute. PINs are stored as salted scrypt hashes.
- **Every route reads ratings and history through the request's profile** (`api/deps.viewer`), so no
  route can mix profiles by accident. Couch guests still have no access to any profile.
- **Moving a profile is a file the user carries.** Export writes a versioned JSON document
  (`flicks-profile`, version 1) with each rating and watch position, keyed by content ID and also
  carrying title and year. Import validates it strictly (size cap 2 MiB, known fields only, version
  check), matches rows by ID or else by exact title and year, and either creates a new profile or
  merges into the current one, where the newer timestamp wins. Nothing is uploaded anywhere.
- **The export holds ratings, not model weights.** Every taste model is a pure function of the ratings
  and public data, so the ratings are the whole of the user's data and the file stays small.

## Alternatives considered
- **Online accounts with sync:** convenient, but contradicts ADR 0001 and needs a server and its security.
- **A separate database file per person (`--db`):** still works, but needs a restart and a command line
  to switch, and gives no way to move data between catalogues.
- **Sign-in from phones on the home network:** would expose the host app beyond loopback. If wanted
  later, pair a phone to one profile through the couch QR flow with a scoped token instead.

## Consequences
- A PIN separates people in a household; it is not protection against someone who can read the
  database file, which is not encrypted. The interface says so.
- An imported profile has no PIN; the user sets one after importing.
- Every new per-person table needs a `profile_id` and a test that profiles stay separate.
