# NoBlog

A minimal markdown blog built with Flask and SQLite. Write posts in a clean editor with image paste support, and read them rendered on a simple, fast site.

> **Fair warning:** this was built fast to solve a problem, not to be secure. Treat it accordingly.

## Features

- Markdown editor (EasyMDE) with live preview
- Paste or drag-and-drop image uploads
- Light/dark theme with toggle (respects OS preference)
- Customizable blog title via environment variable
- SQLite storage, no external database needed
- Docker-ready

## Quick Start (Docker)

```bash
docker compose up --build
```

Visit `http://localhost:30001`

## Quick Start (Local)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Visit `http://localhost:5000`

## Configuration

| Variable             | Default    | Description                                                        |
|----------------------|------------|--------------------------------------------------------------------|
| `BLOG_TITLE`         | `My Blog`  | Site title in header                                               |
| `NOBLOG_WRITE_TOKEN` | _(empty)_  | Shared secret protecting write endpoints; doubles as the password for the NoBlog UI login at `/login`. Empty = no auth. Generate it with `openssl rand -hex 32`. |
| `NOBLOG_TRUST_PROXY` | _(empty)_  | Set to `1` when exactly one trusted reverse proxy fronts NoBlog and sets `X-Forwarded-For/Proto/Host`. Required, not optional, for any TLS-terminating deployment: without it the login cookie ships without `Secure` and cookie writes are rejected as cross-origin. NoBlog logs a warning when it detects either misconfiguration. |
| `NOBLOG_DB_PATH`     | `instance/blog.db` | Override the SQLite database location (used mainly by tests).      |

Set via `docker-compose.yml` under `environment`, or export before running locally.

### Write protection / DailyPad publishing

By default NoBlog is open: anyone who can reach it can create, edit, and delete
posts. Set `NOBLOG_WRITE_TOKEN` to protect every mutation endpoint
(`POST /api/posts`, `PUT /api/posts/<id>`, `DELETE /api/posts/<id>`,
`POST /upload`, `POST /api/settings/readonly`). Read routes and post pages stay
open.

Two credentials are accepted, and both grant the same full write rights:

- **`Authorization: Bearer <NOBLOG_WRITE_TOKEN>`** — for server-to-server clients
  such as DailyPad's publish proxy. Unchanged, and never subject to the CSRF
  check below.
- **The `noblog_auth` cookie** — for NoBlog's own browser UI. Visit `/login` and
  enter the `NOBLOG_WRITE_TOKEN` value as the password: it doubles as the UI
  password, so there is no second secret to manage. The cookie is `HttpOnly`,
  `SameSite=Strict`, `Secure` over HTTPS, holds the token itself and lasts 30
  days. `POST /logout` clears it.

Unauthenticated requests to the HTML editor routes `/new` and `/edit/<id>` are
redirected to `/login` with the original target in a `next` parameter, while
`/api/*` and `/upload` (both called by `fetch()`) return a JSON `401`. The UI
hides the New Post, Edit, Delete and readonly-toggle controls until you are
logged in.

If the cookie expires mid-edit, the editor stashes the title, tags and body in
`localStorage`, sends you to `/login?next=<the editor page>` and restores the draft
when you land back there, so an expired session does not cost you a post. A stash
only exists to survive that round-trip, so one older than 30 minutes is discarded
instead of overwriting whatever the post says now.

Cookie-authenticated mutations additionally require a same-host `Origin` (or
`Referer`) header, so a third-party site cannot ride along on your session. The
bearer path skips that check, since non-browser clients send neither header.

Failed credentials are throttled: after 5 failures from the same client, a further
**wrong** credential is turned away with HTTP `429` and `Retry-After` -- the login
page on `POST /login`, `{"error": "Too many attempts"}` on the mutation endpoints,
which otherwise keep answering `401 {"error": "Unauthorized"}`. A **correct**
credential is always checked first, so it still logs you in (or publishes) while
the throttle holds and resets the counter: a burst of guesses cannot shut the
operator out of their own UI, and cannot slow down DailyPad's publish proxy.
Throttled answers are immediate; NoBlog never delays a response server-side, so an
anonymous caller cannot tie up request-handling threads by guessing. `POST /login`
and the mutation endpoints share one counter, since they compare the same secret.

Two limits worth knowing: the counter lives in process memory (pruned each failure
and capped at 1024 entries), so with multiple workers it slows a guessing run
rather than stopping it; and it is keyed on the client address, which behind a
reverse proxy is only per-visitor when
`NOBLOG_TRUST_PROXY` is set (without it, NoBlog falls back to the untrusted
`X-Forwarded-For` value so visitors are still counted separately, but that header
is spoofable). Either way the real protection is token entropy: generate it with
`openssl rand -hex 32` rather than typing a passphrase, since it is now also a
password field on a public page.

Leaving `NOBLOG_WRITE_TOKEN` unset disables auth entirely and NoBlog behaves
exactly as it did before: everything open, no login page redirect. The token is a
single shared secret for one operator, not per-user auth.

#### Behind a reverse proxy

If NoBlog runs behind a proxy that terminates TLS -- the usual production setup --
`NOBLOG_TRUST_PROXY=1` is a **prerequisite**, not a tuning knob. Without it Flask
sees the proxy's scheme and hostname, so the auth cookie is issued without `Secure`
on an HTTPS site and the same-host check compares the browser's `Origin` against an
internal hostname, which makes every cookie-authenticated write fail with
`403 Invalid origin`. Set the flag when exactly one trusted proxy fronts NoBlog and
sets `X-Forwarded-Proto`, `X-Forwarded-Host` and `X-Forwarded-For`; do not set it
when NoBlog is reachable directly, because then those headers are
attacker-controlled.

Neither mistake is silent. When a write token is configured NoBlog logs a warning
(once per process) if it sees `X-Forwarded-*` headers while the flag is off, and if
the flag is on but a request arrives without `X-Forwarded-Proto` -- both of which
mean the login cookie is going out without `Secure`.

#### Rotating the token

The cookie stores the token verbatim, so it is the same credential DailyPad uses
and there is no per-browser session to revoke. To rotate, or to evict a browser:

1. Generate a new value: `openssl rand -hex 32`.
2. Set it as `NOBLOG_WRITE_TOKEN` here and as `BLOG_WRITE_TOKEN` on DailyPad, then
   restart both. Publishing from DailyPad stays broken until both sides match.
3. Log in again at `/login` with the new value. Existing `noblog_auth` cookies stop
   working immediately.

## Project Structure

```
app.py              Flask application
static/css/style.css  Styles (light/dark themes)
templates/          Jinja2 templates (base, index, post, editor, login)
uploads/            User-uploaded images
instance/           SQLite database (auto-created)
```

## License

MIT
