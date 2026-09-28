import os
import hmac
import time
import uuid
import sqlite3
from datetime import datetime
from urllib.parse import urlsplit
from flask import Flask, request, jsonify, render_template, redirect, url_for, abort, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
app.config['BLOG_TITLE'] = os.environ.get('BLOG_TITLE', 'My Blog')
app.config['SPELL_CHECK'] = os.environ.get('SPELL_CHECK', '').lower() in ('1', 'true', 'yes')
app.config['APP_VERSION'] = os.environ.get('APP_VERSION', 'dev')
# The single shared secret guarding all mutation endpoints. Empty/unset = auth
# disabled (open dev behavior). When set it is accepted through two equivalent
# credentials: an 'Authorization: Bearer <token>' header (used by server-to-server
# clients such as DailyPad's publish proxy) or the noblog_auth cookie issued by
# POST /login, which takes this same value as its password so NoBlog's own
# in-browser UI stays usable. Both grant identical rights; there is one operator,
# so there is no user table and no privilege separation to model.
NOBLOG_WRITE_TOKEN = os.environ.get('NOBLOG_WRITE_TOKEN', '')
AUTH_COOKIE_NAME = 'noblog_auth'
AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
# Failed-login throttle for POST /login. In-memory and per-process, so it slows a
# guessing run against the shared secret rather than stopping it; the token still
# has to be password-grade random (see README).
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 60
_login_failures = {}  # remote address -> (failure count, lockout expiry from time.monotonic())
DB_PATH = os.environ.get('NOBLOG_DB_PATH') or os.path.join(os.path.dirname(__file__), 'instance', 'blog.db')

# Behind a reverse proxy Flask otherwise sees the proxy's scheme and host, which
# would issue the auth cookie without Secure on a TLS-terminated site and make the
# same-origin check below compare the browser's Origin against an internal
# hostname. Set NOBLOG_TRUST_PROXY=1 only when exactly one trusted proxy sets
# X-Forwarded-For/Proto/Host (werkzeug ships with Flask, so this is no new dep).
TRUST_PROXY = os.environ.get('NOBLOG_TRUST_PROXY', '').lower() in ('1', 'true', 'yes')
if TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

@app.context_processor
def inject_globals():
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key = 'readonly'").fetchone()
        readonly = row['value'] == '1' if row else False
    return {
        'blog_title': app.config['BLOG_TITLE'],
        'spell_check': app.config['SPELL_CHECK'],
        'app_version': app.config['APP_VERSION'],
        'readonly_mode': readonly,
        'auth_required': bool(NOBLOG_WRITE_TOKEN),
        'authenticated': is_authenticated(),
    }

def _bearer_ok():
    """True when the request carries the correct 'Authorization: Bearer <token>'."""
    header = request.headers.get('Authorization', '')
    presented = header[7:] if header.startswith('Bearer ') else ''
    # Compare even a missing token so timing does not reveal whether one was sent.
    return hmac.compare_digest(presented, NOBLOG_WRITE_TOKEN)

def _cookie_ok():
    """True when the request carries the correct noblog_auth cookie."""
    # Same reasoning as _bearer_ok(): always run the compare.
    return hmac.compare_digest(request.cookies.get(AUTH_COOKIE_NAME, ''), NOBLOG_WRITE_TOKEN)

def is_authenticated():
    """Auth state used by templates to gate write affordances. True when auth is
    disabled altogether or either accepted credential is valid."""
    if not NOBLOG_WRITE_TOKEN:
        return True
    return _bearer_ok() or _cookie_ok()

def same_origin_ok():
    """CSRF check for cookie-authenticated requests: the request must look like it
    came from this host. Origin wins when present, Referer is the fallback. When
    neither header is present we accept: browsers always send at least one on
    cross-site form posts and fetch, SameSite=Strict already withholds the cookie
    cross-site, and non-browser clients (which send neither) authenticate with the
    bearer token instead, which never reaches this check.

    Failing closed on the header-less case would not buy anything here: the cookie
    value *is* NOBLOG_WRITE_TOKEN, so a client holding a stolen cookie can simply
    replay it as 'Authorization: Bearer <token>' and bypass this function entirely.
    The check exists to stop a third-party *page* from riding an authenticated
    browser session, and for that Origin/Referer is always present.

    Host comparison uses request.host, which reflects X-Forwarded-Host only when
    NOBLOG_TRUST_PROXY is enabled."""
    origin = request.headers.get('Origin')
    if origin:
        return urlsplit(origin).netloc == request.host
    referer = request.headers.get('Referer')
    if referer:
        return urlsplit(referer).netloc == request.host
    return True

def is_safe_redirect(target):
    """Only allow same-site relative redirect targets, mirroring DailyPad's
    isValidRedirectUrl() (server.js): must be a non-empty '/'-prefixed path that is
    not protocol-relative and carries no backslash or encoded slash/backslash."""
    if not target or not isinstance(target, str):
        return False
    if not target.startswith('/') or target.startswith('//'):
        return False
    if '\\' in target:
        return False
    return not any(seq in target for seq in ('%2f', '%2F', '%5c', '%5C'))

def require_write_token():
    """Guard for mutation endpoints. Returns None when auth is disabled, the request
    carries the correct bearer token, or it carries a valid auth cookie from this
    origin; otherwise a Flask JSON error response tuple. The bearer path deliberately
    short-circuits before the CSRF check so server-to-server clients, which send no
    Origin header, are unaffected. Compares are constant-time."""
    if not NOBLOG_WRITE_TOKEN:
        return None
    if _bearer_ok():
        return None
    if _cookie_ok():
        if not same_origin_ok():
            return jsonify({'error': 'Invalid origin'}), 403
        return None
    return jsonify({'error': 'Unauthorized'}), 401

def _login_locked():
    """True when this client has used up LOGIN_MAX_ATTEMPTS failures and the lockout
    window has not expired yet."""
    count, expires = _login_failures.get(request.remote_addr, (0, 0.0))
    if expires <= time.monotonic():
        _login_failures.pop(request.remote_addr, None)
        return False
    return count >= LOGIN_MAX_ATTEMPTS

def _record_login_failure():
    now = time.monotonic()
    # Drop expired entries so a guessing run cannot grow this dict without bound.
    for addr, (_, expires) in list(_login_failures.items()):
        if expires <= now:
            del _login_failures[addr]
    count, expires = _login_failures.get(request.remote_addr, (0, 0.0))
    _login_failures[request.remote_addr] = (count + 1, now + LOGIN_LOCKOUT_SECONDS)

def require_ui_auth():
    """Guard for HTML editor pages. Returns None when the visitor may write,
    otherwise a redirect to the login page preserving the requested target. The
    HTML counterpart of require_write_token()'s JSON 401, same content-negotiation
    spirit as handle_404."""
    if is_authenticated():
        return None
    # full_path keeps the query string; Flask appends a bare '?' when there is none.
    target = request.full_path.rstrip('?') or request.path
    return redirect(url_for('login', next=target))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        # Migrate: add missing columns for existing databases
        cols = [row[1] for row in db.execute('PRAGMA table_info(posts)').fetchall()]
        if 'tags' not in cols:
            db.execute("ALTER TABLE posts ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
        if 'deleted_at' not in cols:
            db.execute("ALTER TABLE posts ADD COLUMN deleted_at TEXT")
        db.commit()

def slugify(title):
    import re
    slug = title.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_-]+', '-', slug)
    slug = re.sub(r'^-+|-+$', '', slug)
    return slug or 'untitled'

def unique_slug(db, base_slug):
    slug = base_slug
    counter = 1
    while db.execute('SELECT id FROM posts WHERE slug = ?', (slug,)).fetchone():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug

# ── Routes ────────────────────────────────────────────────────────────────────

@app.after_request
def add_auth_cache_headers(response):
    """Once a token is configured, HTML pages render differently depending on the
    request's credential (write affordances present or absent), so tell shared
    caches not to reuse one visitor's variant for another."""
    if NOBLOG_WRITE_TOKEN and response.mimetype == 'text/html':
        response.vary.add('Cookie')
        response.headers.setdefault('Cache-Control', 'private, no-cache')
    return response

@app.errorhandler(404)
def handle_404(error):
    # API clients (e.g. DailyPad's proxy) expect JSON, not Flask's default HTML page,
    # so a missing /api/ resource forwards a real 404 instead of collapsing into a 502.
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return error, 404

def parse_tags(raw):
    """Normalize a comma-separated tag string into sorted, deduplicated, lowercase list."""
    if not raw:
        return []
    return sorted(set(t.strip().lower() for t in raw.split(',') if t.strip()))

@app.route('/')
def index():
    with get_db() as db:
        posts = db.execute(
            'SELECT id, title, slug, tags, created_at, updated_at FROM posts WHERE deleted_at IS NULL ORDER BY created_at DESC'
        ).fetchall()
        all_tags = sorted(set(
            t for row in posts for t in parse_tags(row['tags'])
        ))
    return render_template('index.html', posts=posts, all_tags=all_tags)

@app.route('/post/<slug>')
def view_post(slug):
    with get_db() as db:
        post = db.execute('SELECT * FROM posts WHERE slug = ? AND deleted_at IS NULL', (slug,)).fetchone()
    if not post:
        abort(404)
    return render_template('post.html', post=post)

@app.route('/new')
def new_post():
    auth = require_ui_auth()
    if auth is not None:
        return auth
    return render_template('editor.html', post=None)

@app.route('/edit/<int:post_id>')
def edit_post(post_id):
    auth = require_ui_auth()
    if auth is not None:
        return auth
    with get_db() as db:
        post = db.execute('SELECT * FROM posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone()
    if not post:
        abort(404)
    return render_template('editor.html', post=post)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Minimal single-field login. The password is NOBLOG_WRITE_TOKEN itself; on
    success the same value is stored in an HttpOnly SameSite=Strict cookie."""
    target = request.values.get('next', '')
    if not is_safe_redirect(target):
        target = '/'

    if request.method == 'GET':
        if is_authenticated():
            return redirect(target)
        return render_template('login.html', next_target=target, error=None)

    if not same_origin_ok():
        return render_template('login.html', next_target=target, error='Invalid origin'), 403
    if not NOBLOG_WRITE_TOKEN:
        return redirect(target)
    if _login_locked():
        locked = render_template(
            'login.html', next_target=target, error='Too many attempts. Try again in a minute.'
        )
        return locked, 429, {'Retry-After': str(LOGIN_LOCKOUT_SECONDS)}
    # Never log or echo the submitted password.
    if not hmac.compare_digest(request.form.get('password', ''), NOBLOG_WRITE_TOKEN):
        _record_login_failure()
        return render_template('login.html', next_target=target, error='Incorrect password'), 401

    _login_failures.pop(request.remote_addr, None)
    response = redirect(target)
    response.set_cookie(
        AUTH_COOKIE_NAME,
        NOBLOG_WRITE_TOKEN,
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite='Strict',
        secure=request.is_secure,
        path='/',
    )
    return response

@app.route('/logout', methods=['POST'])
def logout():
    if not same_origin_ok():
        return jsonify({'error': 'Invalid origin'}), 403
    response = redirect('/')
    response.delete_cookie(AUTH_COOKIE_NAME, path='/', samesite='Strict')
    return response

@app.route('/api/posts')
def api_list_posts():
    with get_db() as db:
        posts = db.execute(
            'SELECT id, title, slug, tags, created_at, updated_at FROM posts WHERE deleted_at IS NULL ORDER BY created_at DESC'
        ).fetchall()
    return jsonify([
        {
            'id': post['id'],
            'title': post['title'],
            'slug': post['slug'],
            'tags': parse_tags(post['tags']),
            'created_at': post['created_at'],
            'updated_at': post['updated_at'],
        }
        for post in posts
    ])

@app.route('/api/posts/<slug>')
def api_get_post(slug):
    with get_db() as db:
        post = db.execute('SELECT * FROM posts WHERE slug = ? AND deleted_at IS NULL', (slug,)).fetchone()
    if not post:
        abort(404)
    return jsonify({
        'id': post['id'],
        'title': post['title'],
        'slug': post['slug'],
        'content': post['content'],
        'tags': parse_tags(post['tags']),
        'created_at': post['created_at'],
        'updated_at': post['updated_at'],
    })

def validate_post_body(data):
    """Validate a decoded JSON post body. Returns a Flask JSON 400 response on
    invalid input, otherwise None."""
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400
    for field in ('title', 'content', 'tags'):
        if field in data and data[field] is not None and not isinstance(data[field], str):
            return jsonify({'error': 'title, content and tags must be strings'}), 400
    return None

@app.route('/api/posts', methods=['POST'])
def create_post():
    auth = require_write_token()
    if auth is not None:
        return auth
    data = request.get_json(silent=True)
    err = validate_post_body(data)
    if err is not None:
        return err
    title = (data.get('title') or '').strip() or 'Untitled'
    content = data.get('content', '')
    tags = ','.join(parse_tags(data.get('tags', '')))
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        base_slug = slugify(title)
        slug = unique_slug(db, base_slug)
        db.execute(
            'INSERT INTO posts (title, slug, content, tags, created_at, updated_at) VALUES (?,?,?,?,?,?)',
            (title, slug, content, tags, now, now)
        )
        db.commit()
        post = db.execute('SELECT * FROM posts WHERE slug = ?', (slug,)).fetchone()
    return jsonify({'id': post['id'], 'slug': post['slug']})

@app.route('/api/posts/<int:post_id>', methods=['PUT'])
def update_post(post_id):
    auth = require_write_token()
    if auth is not None:
        return auth
    data = request.get_json(silent=True)
    err = validate_post_body(data)
    if err is not None:
        return err
    title = (data.get('title') or '').strip() or 'Untitled'
    content = data.get('content', '')
    tags = ','.join(parse_tags(data.get('tags', '')))
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        existing = db.execute('SELECT * FROM posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone()
        if not existing:
            abort(404)
        db.execute(
            'UPDATE posts SET title=?, content=?, tags=?, updated_at=? WHERE id=?',
            (title, content, tags, now, post_id)
        )
        db.commit()
        post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    return jsonify({'id': post['id'], 'slug': post['slug']})

@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
def delete_post(post_id):
    auth = require_write_token()
    if auth is not None:
        return auth
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute('UPDATE posts SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL', (now, post_id))
        db.commit()
    return jsonify({'ok': True})

@app.route('/upload', methods=['POST'])
def upload_image():
    auth = require_write_token()
    if auth is not None:
        return auth
    if 'image' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['image']
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
    if ext not in ALLOWED_EXTENSIONS:
        ext = 'png'
    filename = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return jsonify({'url': f'/uploads/{filename}'})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/settings/readonly', methods=['POST'])
def toggle_readonly():
    auth = require_write_token()
    if auth is not None:
        return auth
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key = 'readonly'").fetchone()
        current = row['value'] == '1' if row else False
        new_val = '0' if current else '1'
        db.execute(
            "INSERT INTO settings (key, value) VALUES ('readonly', ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (new_val, new_val)
        )
        db.commit()
    return jsonify({'readonly': new_val == '1'})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5001, debug=True)
