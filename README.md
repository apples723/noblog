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
| `NOBLOG_WRITE_TOKEN` | _(empty)_  | Shared bearer token protecting write endpoints. Empty = no auth.   |
| `NOBLOG_DB_PATH`     | `instance/blog.db` | Override the SQLite database location (used mainly by tests).      |

Set via `docker-compose.yml` under `environment`, or export before running locally.

### Write protection / DailyPad publishing

By default NoBlog is open: anyone who can reach it can create, edit, and delete
posts. Set `NOBLOG_WRITE_TOKEN` to require an `Authorization: Bearer <token>`
header on every mutation endpoint (`POST /api/posts`, `PUT /api/posts/<id>`,
`DELETE /api/posts/<id>`, `POST /upload`, `POST /api/settings/readonly`). Read
routes and HTML pages stay open. Requests with a missing or wrong token get a
JSON `401`.

**Consequence:** NoBlog's own in-browser editor (`templates/editor.html`) posts
without a token, so once `NOBLOG_WRITE_TOKEN` is set, saving from the native
editor will fail with `401`. Enabling the token effectively makes an external
client such as DailyPad the author. Building a NoBlog login/session system is
out of scope; the token is a single shared secret, not per-user auth.

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
