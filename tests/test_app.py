"""Tests for NoBlog: write-token enforcement, JSON validation, and existing
components (CRUD, soft-delete, readonly, tag/slug helpers)."""

from conftest import TEST_TOKEN


def auth(token=TEST_TOKEN):
    return {'Authorization': f'Bearer {token}'}


# ── Helper unit tests (imported directly from the app module) ──────────────────

def test_parse_tags_normalization(app_module):
    parse_tags = app_module.parse_tags
    assert parse_tags('') == []
    assert parse_tags(None) == []
    assert parse_tags('  ') == []
    # dedupe, lowercase, sort, trim
    assert parse_tags('B, a, a ,  C ') == ['a', 'b', 'c']
    assert parse_tags('Foo,foo,FOO') == ['foo']


def test_slugify(app_module):
    slugify = app_module.slugify
    assert slugify('Hello World!') == 'hello-world'
    assert slugify('   ') == 'untitled'
    assert slugify('A B & C') == 'a-b-c'


def test_unique_slug(app_module):
    unique_slug = app_module.unique_slug
    with app_module.get_db() as db:
        now = '2020-01-01T00:00:00'
        db.execute(
            'INSERT INTO posts (title, slug, content, tags, created_at, updated_at) VALUES (?,?,?,?,?,?)',
            ('Hello', 'hello', '', '', now, now),
        )
        db.commit()
        assert unique_slug(db, 'hello') == 'hello-1'
        assert unique_slug(db, 'other') == 'other'


# ── Existing components: create / get / list / update / delete ─────────────────

def test_create_get_list(client):
    resp = client.post('/api/posts', json={'title': 'First Post', 'content': 'body', 'tags': 'b,a,a'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'id' in data and 'slug' in data
    slug = data['slug']

    got = client.get(f'/api/posts/{slug}')
    assert got.status_code == 200
    post = got.get_json()
    assert post['title'] == 'First Post'
    assert post['content'] == 'body'
    assert post['tags'] == ['a', 'b']

    listed = client.get('/api/posts').get_json()
    assert any(p['slug'] == slug for p in listed)


def test_create_defaults(client):
    resp = client.post('/api/posts', json={})
    assert resp.status_code == 200
    slug = resp.get_json()['slug']
    post = client.get(f'/api/posts/{slug}').get_json()
    assert post['title'] == 'Untitled'
    assert post['content'] == ''
    assert post['tags'] == []


def test_update_post(client):
    slug = client.post('/api/posts', json={'title': 'Orig'}).get_json()['slug']
    post = client.get(f'/api/posts/{slug}').get_json()
    pid = post['id']

    resp = client.put(f'/api/posts/{pid}', json={'title': 'Changed', 'content': 'new body', 'tags': 'x,y'})
    assert resp.status_code == 200
    new_slug = resp.get_json()['slug']

    updated = client.get(f'/api/posts/{new_slug}').get_json()
    assert updated['title'] == 'Changed'
    assert updated['content'] == 'new body'
    assert updated['tags'] == ['x', 'y']


def test_delete_soft_deletes(client):
    slug = client.post('/api/posts', json={'title': 'ToDelete'}).get_json()['slug']
    pid = client.get(f'/api/posts/{slug}').get_json()['id']

    resp = client.delete(f'/api/posts/{pid}')
    assert resp.status_code == 200
    assert resp.get_json() == {'ok': True}

    # hidden from get + list
    assert client.get(f'/api/posts/{slug}').status_code == 404
    assert all(p['slug'] != slug for p in client.get('/api/posts').get_json())

    # deleted_at is set in the DB (row still present)
    import app as app_module
    with app_module.get_db() as db:
        row = db.execute('SELECT deleted_at FROM posts WHERE id = ?', (pid,)).fetchone()
        assert row['deleted_at'] is not None


def test_readonly_toggle(client):
    first = client.post('/api/settings/readonly')
    assert first.status_code == 200
    assert first.get_json()['readonly'] is True
    second = client.post('/api/settings/readonly')
    assert second.get_json()['readonly'] is False


# ── JSON validation (400 not 500) ──────────────────────────────────────────────

def test_create_non_json_body(client):
    resp = client.post('/api/posts', data='not json', content_type='text/plain')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'Invalid JSON body'


def test_create_non_object_json(client):
    resp = client.post('/api/posts', json=[1, 2, 3])
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'Invalid JSON body'


def test_create_non_string_fields(client):
    for body in ({'title': 5}, {'content': ['a']}, {'tags': {'x': 1}}):
        resp = client.post('/api/posts', json=body)
        assert resp.status_code == 400
        assert 'must be strings' in resp.get_json()['error']


def test_update_invalid_json(client):
    slug = client.post('/api/posts', json={'title': 'Orig'}).get_json()['slug']
    pid = client.get(f'/api/posts/{slug}').get_json()['id']
    resp = client.put(f'/api/posts/{pid}', data='nope', content_type='text/plain')
    assert resp.status_code == 400
    resp2 = client.put(f'/api/posts/{pid}', json={'title': 42})
    assert resp2.status_code == 400


# ── Token disabled: mutations are open ─────────────────────────────────────────

def test_mutations_open_when_token_unset(client):
    assert client.post('/api/posts', json={'title': 'X'}).status_code == 200
    assert client.post('/api/settings/readonly').status_code == 200


# ── Token enforcement on each mutation endpoint ────────────────────────────────

def test_create_requires_token(client_token):
    assert client_token.post('/api/posts', json={'title': 'X'}).status_code == 401
    assert client_token.post('/api/posts', json={'title': 'X'}, headers=auth('wrong')).status_code == 401
    ok = client_token.post('/api/posts', json={'title': 'X'}, headers=auth())
    assert ok.status_code == 200


def test_update_requires_token(client_token):
    created = client_token.post('/api/posts', json={'title': 'X'}, headers=auth())
    slug = created.get_json()['slug']
    pid = client_token.get(f'/api/posts/{slug}').get_json()['id']

    assert client_token.put(f'/api/posts/{pid}', json={'title': 'Y'}).status_code == 401
    assert client_token.put(f'/api/posts/{pid}', json={'title': 'Y'}, headers=auth()).status_code == 200


def test_delete_requires_token(client_token):
    created = client_token.post('/api/posts', json={'title': 'X'}, headers=auth())
    slug = created.get_json()['slug']
    pid = client_token.get(f'/api/posts/{slug}').get_json()['id']

    assert client_token.delete(f'/api/posts/{pid}').status_code == 401
    assert client_token.delete(f'/api/posts/{pid}', headers=auth()).status_code == 200


def test_upload_requires_token(client_token):
    assert client_token.post('/upload').status_code == 401


def test_readonly_requires_token(client_token):
    assert client_token.post('/api/settings/readonly').status_code == 401
    assert client_token.post('/api/settings/readonly', headers=auth()).status_code == 200


def test_401_is_json(client_token):
    resp = client_token.post('/api/posts', json={'title': 'X'})
    assert resp.status_code == 401
    assert resp.is_json
    assert resp.get_json()['error'] == 'Unauthorized'


# ── Read routes stay open even with a token configured ─────────────────────────

def test_reads_open_with_token(client_token):
    assert client_token.get('/api/posts').status_code == 200
