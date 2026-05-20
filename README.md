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

| Variable     | Default    | Description          |
|--------------|------------|----------------------|
| `BLOG_TITLE` | `My Blog`  | Site title in header |

Set via `docker-compose.yml` under `environment`, or export before running locally.

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
