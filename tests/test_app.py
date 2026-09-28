"""Tests for NoBlog: write-token enforcement, JSON validation, and existing
components (CRUD, soft-delete, readonly, tag/slug helpers)."""

import io
from urllib.parse import unquote

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


# ── Redirect target validation (ported from DailyPad's isValidRedirectUrl) ──────

def test_is_safe_redirect(app_module):
    is_safe_redirect = app_module.is_safe_redirect
    assert is_safe_redirect('/new')
    assert is_safe_redirect('/edit/1?x=1')
    for bad in ('', None, 5, 'http://evil.example', '//evil.example', '/a\\b',
                '/%2fevil', '/%2Fevil', '/%5cevil', '/%5Cevil'):
        assert not is_safe_redirect(bad)


# ── Bearer credential: unchanged behavior for server-to-server clients ─────────

def test_bearer_authorizes_every_mutation(client_token):
    created = client_token.post('/api/posts', json={'title': 'Bearer post'}, headers=auth())
    assert created.status_code == 200
    pid = created.get_json()['id']

    assert client_token.put(f'/api/posts/{pid}', json={'title': 'Bearer edit'}, headers=auth()).status_code == 200
    assert client_token.post(
        '/upload',
        data={'image': (io.BytesIO(b'png-bytes'), 'x.png')},
        content_type='multipart/form-data',
        headers=auth(),
    ).status_code == 200
    assert client_token.post('/api/settings/readonly', headers=auth()).status_code == 200
    assert client_token.delete(f'/api/posts/{pid}', headers=auth()).status_code == 200


# ── Cookie credential: NoBlog's own browser UI ─────────────────────────────────

def test_cookie_authorizes_posts_crud(client_cookie):
    created = client_cookie.post('/api/posts', json={'title': 'Cookie post'})
    assert created.status_code == 200
    pid = created.get_json()['id']

    assert client_cookie.put(f'/api/posts/{pid}', json={'title': 'Cookie edit'}).status_code == 200
    assert client_cookie.delete(f'/api/posts/{pid}').status_code == 200


def test_cookie_authorizes_upload(client_cookie):
    resp = client_cookie.post(
        '/upload',
        data={'image': (io.BytesIO(b'png-bytes'), 'x.png')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 200
    assert resp.get_json()['url'].startswith('/uploads/')


def test_cookie_authorizes_readonly_toggle(client_cookie):
    assert client_cookie.post('/api/settings/readonly').get_json()['readonly'] is True
    assert client_cookie.post('/api/settings/readonly').get_json()['readonly'] is False


def test_wrong_cookie_and_wrong_bearer_is_401(client_token):
    client_token.set_cookie('noblog_auth', 'nope')
    resp = client_token.post('/api/posts', json={'title': 'X'}, headers=auth('also-nope'))
    assert resp.status_code == 401
    assert resp.get_json()['error'] == 'Unauthorized'


# ── HTML editor routes redirect to /login instead of 401ing ────────────────────

def test_editor_pages_redirect_to_login_when_unauthenticated(client_token):
    created = client_token.post('/api/posts', json={'title': 'Guarded'}, headers=auth())
    pid = created.get_json()['id']

    for path in ('/new', f'/edit/{pid}'):
        resp = client_token.get(path)
        assert resp.status_code == 302
        location = unquote(resp.headers['Location'])
        assert location.startswith('/login')
        assert f'next={path}' in location


def test_editor_pages_render_with_cookie(client_cookie):
    created = client_cookie.post('/api/posts', json={'title': 'Guarded'})
    pid = created.get_json()['id']
    assert client_cookie.get('/new').status_code == 200
    assert client_cookie.get(f'/edit/{pid}').status_code == 200


def test_api_still_returns_json_401_not_a_redirect(client_token):
    resp = client_token.post('/api/posts', json={'title': 'X'})
    assert resp.status_code == 401
    assert resp.is_json


# ── Login page and form ────────────────────────────────────────────────────────

def test_login_page_renders_when_unauthenticated(client_token):
    resp = client_token.get('/login')
    assert resp.status_code == 200
    assert b'name="password"' in resp.data


def test_login_page_redirects_when_auth_disabled(client):
    resp = client.get('/login')
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'


def test_login_page_redirects_when_already_authenticated(client_cookie):
    resp = client_cookie.get('/login?next=/new')
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/new'


def test_login_success_sets_cookie_and_authorizes(client_token):
    resp = client_token.post('/login', data={'password': TEST_TOKEN, 'next': '/new'})
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/new'
    set_cookie = resp.headers['Set-Cookie']
    assert set_cookie.startswith('noblog_auth=')
    assert 'HttpOnly' in set_cookie
    assert 'SameSite=Strict' in set_cookie
    # the issued cookie is retained by the test client and authorizes a mutation
    assert client_token.post('/api/posts', json={'title': 'Via login'}).status_code == 200


def test_login_rejects_unsafe_next_target(client_token):
    resp = client_token.post('/login', data={'password': TEST_TOKEN, 'next': '//evil.example'})
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'


def test_login_failure_sets_no_cookie(client_token):
    resp = client_token.post('/login', data={'password': 'wrong'})
    assert resp.status_code == 401
    assert 'Set-Cookie' not in resp.headers
    assert client_token.post('/api/posts', json={'title': 'X'}).status_code == 401


def test_logout_clears_cookie(client_cookie):
    assert client_cookie.post('/api/posts', json={'title': 'Before logout'}).status_code == 200
    resp = client_cookie.post('/logout')
    assert resp.status_code == 302
    assert client_cookie.post('/api/posts', json={'title': 'After logout'}).status_code == 401


# ── CSRF: Origin check applies to the cookie path only ────────────────────────

def test_cross_origin_cookie_mutation_is_403(client_cookie):
    resp = client_cookie.post(
        '/api/posts', json={'title': 'CSRF'}, headers={'Origin': 'http://evil.example'}
    )
    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Invalid origin'


def test_cross_origin_bearer_mutation_still_succeeds(client_token):
    headers = auth()
    headers['Origin'] = 'http://evil.example'
    assert client_token.post('/api/posts', json={'title': 'Proxy'}, headers=headers).status_code == 200


def test_same_origin_cookie_mutation_is_allowed(client_cookie):
    resp = client_cookie.post(
        '/api/posts', json={'title': 'Same origin'}, headers={'Origin': 'http://localhost'}
    )
    assert resp.status_code == 200


def test_referer_fallback_allows_same_host_and_rejects_other_hosts(client_cookie):
    same_host = client_cookie.post(
        '/api/posts', json={'title': 'Referer'}, headers={'Referer': 'http://localhost/new'}
    )
    assert same_host.status_code == 200

    cross_host = client_cookie.post(
        '/api/posts', json={'title': 'Referer'}, headers={'Referer': 'http://evil.example/page'}
    )
    assert cross_host.status_code == 403
    assert cross_host.get_json()['error'] == 'Invalid origin'


def test_cookie_mutation_without_origin_or_referer_is_allowed(client_cookie):
    """Documents the deliberate fail-open when neither header is present: browsers
    always send one, and a non-browser client holding the cookie could replay the
    same value as a bearer token anyway, so failing closed would add no protection."""
    assert client_cookie.post('/api/posts', json={'title': 'No headers'}).status_code == 200


def test_cross_origin_login_is_403(client_token):
    resp = client_token.post(
        '/login', data={'password': TEST_TOKEN}, headers={'Origin': 'http://evil.example'}
    )
    assert resp.status_code == 403
    assert 'Set-Cookie' not in resp.headers


def test_cross_origin_logout_is_403(client_cookie):
    resp = client_cookie.post('/logout', headers={'Origin': 'http://evil.example'})
    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Invalid origin'
    # the cookie survives, so the session is untouched
    assert client_cookie.post('/api/posts', json={'title': 'Still logged in'}).status_code == 200


# ── Reverse-proxy awareness (NOBLOG_TRUST_PROXY) ───────────────────────────────

def test_forwarded_headers_ignored_without_trust_proxy(client_token):
    """Default deployment: forwarded headers are untrusted, so a spoofed
    X-Forwarded-Host cannot satisfy the origin check."""
    resp = client_token.post(
        '/login',
        data={'password': TEST_TOKEN},
        headers={'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'blog.example'},
    )
    assert resp.status_code == 302
    assert 'Secure' not in resp.headers['Set-Cookie']


def test_trusted_proxy_marks_cookie_secure(client_proxy):
    resp = client_proxy.post(
        '/login',
        data={'password': TEST_TOKEN},
        headers={
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': 'blog.example',
            'Origin': 'https://blog.example',
        },
    )
    assert resp.status_code == 302
    set_cookie = resp.headers['Set-Cookie']
    assert 'Secure' in set_cookie
    assert 'HttpOnly' in set_cookie
    assert 'SameSite=Strict' in set_cookie


def test_trusted_proxy_origin_check_uses_forwarded_host(client_proxy):
    client_proxy.set_cookie('noblog_auth', TEST_TOKEN)
    forwarded = {'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'blog.example'}

    ok = client_proxy.post(
        '/api/posts', json={'title': 'Behind proxy'},
        headers={**forwarded, 'Origin': 'https://blog.example'},
    )
    assert ok.status_code == 200

    # the proxy's own internal hostname is not the browser-visible origin
    bad = client_proxy.post(
        '/api/posts', json={'title': 'Behind proxy'},
        headers={**forwarded, 'Origin': 'http://localhost'},
    )
    assert bad.status_code == 403


# ── Login throttling ──────────────────────────────────────────────────────────

def test_login_locks_out_after_repeated_failures(client_token, app_module_token):
    for _ in range(app_module_token.LOGIN_MAX_ATTEMPTS):
        assert client_token.post('/login', data={'password': 'wrong'}).status_code == 401

    locked = client_token.post('/login', data={'password': 'wrong'})
    assert locked.status_code == 429
    assert locked.headers['Retry-After'] == str(app_module_token.LOGIN_LOCKOUT_SECONDS)
    # even the correct password is refused while the lockout holds
    assert client_token.post('/login', data={'password': TEST_TOKEN}).status_code == 429
    assert 'Set-Cookie' not in locked.headers


def test_successful_login_clears_failure_counter(client_token, app_module_token):
    client_token.post('/login', data={'password': 'wrong'})
    assert app_module_token._login_failures
    assert client_token.post('/login', data={'password': TEST_TOKEN}).status_code == 302
    assert app_module_token._login_failures == {}


# ── Template gating of write affordances ──────────────────────────────────────

def test_write_affordances_hidden_when_unauthenticated(client_token):
    slug = client_token.post(
        '/api/posts', json={'title': 'Gated post'}, headers=auth()
    ).get_json()['slug']

    home = client_token.get('/')
    assert home.status_code == 200
    assert b'href="/new"' not in home.data
    assert b'id="readonly-toggle"' not in home.data
    assert b'action="/logout"' not in home.data
    assert b'href="/login"' in home.data

    post_page = client_token.get(f'/post/{slug}')
    assert post_page.status_code == 200
    assert b'href="/edit/' not in post_page.data
    assert b'onclick="deletePost(' not in post_page.data


def test_write_affordances_visible_when_authenticated(client_cookie):
    slug = client_cookie.post('/api/posts', json={'title': 'Gated post'}).get_json()['slug']

    home = client_cookie.get('/')
    assert b'href="/new"' in home.data
    assert b'id="readonly-toggle"' in home.data
    assert b'action="/logout"' in home.data
    assert b'href="/login"' not in home.data

    post_page = client_cookie.get(f'/post/{slug}')
    assert b'href="/edit/' in post_page.data
    assert b'onclick="deletePost(' in post_page.data


def test_empty_state_write_link_is_gated(client_token, client_cookie):
    assert b'Write your first post' not in client_token.get('/').data
    assert b'Write your first post' in client_cookie.get('/').data


def test_auth_varying_html_is_not_shared_cacheable(client_token):
    resp = client_token.get('/')
    assert 'Cookie' in resp.headers['Vary']
    assert 'private' in resp.headers['Cache-Control']
    # JSON reads do not vary by credential
    assert 'Vary' not in client_token.get('/api/posts').headers


def test_open_mode_adds_no_cache_headers(client):
    assert 'Vary' not in client.get('/').headers


# ── Open mode (no token) is unchanged ─────────────────────────────────────────

def test_open_mode_allows_every_mutation_and_editor_pages(client):
    created = client.post('/api/posts', json={'title': 'Open'})
    assert created.status_code == 200
    pid = created.get_json()['id']

    assert client.get('/new').status_code == 200
    assert client.get(f'/edit/{pid}').status_code == 200
    assert client.put(f'/api/posts/{pid}', json={'title': 'Open edit'}).status_code == 200
    assert client.post(
        '/upload',
        data={'image': (io.BytesIO(b'png-bytes'), 'x.png')},
        content_type='multipart/form-data',
    ).status_code == 200
    assert client.post('/api/settings/readonly').status_code == 200
    assert client.delete(f'/api/posts/{pid}').status_code == 200
