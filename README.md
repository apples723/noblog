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
| `NOBLOG_WRITE_TOKEN` | _(empty)_  | Shared secret protecting write endpoints; doubles as the password for the NoBlog UI login at `/login`. Empty = no auth. |
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

Cookie-authenticated mutations additionally require a same-host `Origin` (or
`Referer`) header, so a third-party site cannot ride along on your session. The
bearer path skips that check, since non-browser clients send neither header.

Leaving `NOBLOG_WRITE_TOKEN` unset disables auth entirely and NoBlog behaves
exactly as it did before: everything open, no login page redirect. The token is a
single shared secret for one operator, not per-user auth.

## Project Structure

```
app.py              Flask application
static/css/style.css  Styles (light/dark themes)
templates/          Jinja2 templates
uploads/            User-uploaded images
instance/           SQLite database (auto-created)
```

## License

MIT
