import os
import uuid
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, abort, send_from_directory

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
app.config['BLOG_TITLE'] = os.environ.get('BLOG_TITLE', 'My Blog')
app.config['SPELL_CHECK'] = os.environ.get('SPELL_CHECK', '').lower() in ('1', 'true', 'yes')
app.config['APP_VERSION'] = os.environ.get('APP_VERSION', 'dev')
DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'blog.db')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

@app.context_processor
def inject_globals():
    return {
        'blog_title': app.config['BLOG_TITLE'],
        'spell_check': app.config['SPELL_CHECK'],
        'app_version': app.config['APP_VERSION'],
    }

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
                updated_at TEXT NOT NULL
            )
        ''')
        # Migrate: add tags column if missing (existing databases)
        cols = [row[1] for row in db.execute('PRAGMA table_info(posts)').fetchall()]
        if 'tags' not in cols:
            db.execute("ALTER TABLE posts ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
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

def parse_tags(raw):
    """Normalize a comma-separated tag string into sorted, deduplicated, lowercase list."""
    if not raw:
        return []
    return sorted(set(t.strip().lower() for t in raw.split(',') if t.strip()))

@app.route('/')
def index():
    with get_db() as db:
        posts = db.execute(
            'SELECT id, title, slug, tags, created_at FROM posts ORDER BY created_at DESC'
        ).fetchall()
        all_tags = sorted(set(
            t for row in posts for t in parse_tags(row['tags'])
        ))
    return render_template('index.html', posts=posts, all_tags=all_tags)

@app.route('/post/<slug>')
def view_post(slug):
    with get_db() as db:
        post = db.execute('SELECT * FROM posts WHERE slug = ?', (slug,)).fetchone()
    if not post:
        abort(404)
    return render_template('post.html', post=post)

@app.route('/new')
def new_post():
    return render_template('editor.html', post=None)

@app.route('/edit/<int:post_id>')
def edit_post(post_id):
    with get_db() as db:
        post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        abort(404)
    return render_template('editor.html', post=post)

@app.route('/api/posts', methods=['POST'])
def create_post():
    data = request.json
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
    data = request.json
    title = (data.get('title') or '').strip() or 'Untitled'
    content = data.get('content', '')
    tags = ','.join(parse_tags(data.get('tags', '')))
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        existing = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
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
    with get_db() as db:
        db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
        db.commit()
    return jsonify({'ok': True})

@app.route('/upload', methods=['POST'])
def upload_image():
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

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5001, debug=True)
