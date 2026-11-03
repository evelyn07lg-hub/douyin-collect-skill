"""Official API adapter. Endpoint fields require credentialed contract testing."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


class AuthError(RuntimeError):
    pass


class Official:
    def __init__(self, account, store):
        self.account, self.store = account, store
        prefix = account['token_env']
        self.token = store.get('token:' + account['id'], {})
        for k in ('access_token', 'refresh_token', 'expires_at', 'scopes'):
            value = os.getenv(prefix + '_' + k.upper())
            if value and k not in self.token:
                self.token[k] = value

    def request(self, path, params, body=None, oauth=False):
        url = 'https://open.douyin.com' + path + '?' + urllib.parse.urlencode(params)
        for attempt in range(3):
            req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type': 'application/json', 'access-token': self.token.get('access_token', '')})
            try:
                with urllib.request.urlopen(req, timeout=30) as res:
                    payload = json.load(res)
                data = payload.get('data', {})
                code = data.get('error_code', payload.get('extra', {}).get('error_code', 0))
                if code:
                    if str(code) in ('2190008', '2190014', '2190015', '2190016'):
                        raise AuthError('token_invalid; renew authorization')
                    raise RuntimeError(f'official API error code={code}')
                return data
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise AuthError('token_invalid or permission denied') from None
                if e.code != 429 and e.code < 500:
                    raise RuntimeError(f'official HTTP {e.code}') from None
            except (urllib.error.URLError, TimeoutError):
                pass
            if attempt < 2:
                time.sleep(2 ** attempt)
        raise RuntimeError('network_api_error: retries exhausted')

    def authorize(self):
        if not self.account['id'] or not self.token.get('access_token'):
            raise AuthError('authorization_required')
        if not {'video.list', 'video.data'} <= set(self.token.get('scopes', '').split(',')):
            raise AuthError('authorization_required: video.list,video.data permissions')
        if float(self.token.get('expires_at', 0)) < time.time() + 120:
            refresh = self.token.get('refresh_token')
            key = os.getenv('DOUYIN_CLIENT_KEY')
            if not refresh or not key:
                raise AuthError('token_invalid: refresh token/client key/expiry missing')
            data = self.request('/oauth/refresh_token/', {'client_key': key,
                'grant_type': 'refresh_token', 'refresh_token': refresh}, oauth=True)
            if not data.get('access_token'):
                raise AuthError('refresh failed')
            self.token.update(data)
            self.token['expires_at'] = time.time() + int(data['expires_in'])
            self.store.set('token:' + self.account['id'], self.token)

    def scan(self, historical=False):
        self.authorize()
        key = 'scan:' + self.account['id']
        complete = self.store.get(key + ':complete', False)
        cursor = self.store.get(key + ':cursor', 0) if not complete or historical else 0
        seen = set()
        while True:
            if cursor in seen:
                raise RuntimeError('pagination cursor repeated')
            seen.add(cursor)
            data = self.request('/video/list/', {'open_id': self.account['id'], 'cursor': cursor, 'count': 20})
            rows = data.get('list', [])
            # Stop incremental scan only after a whole known page, tolerating pinned posts.
            known = bool(rows) and all(self.store.db.execute('SELECT 1 FROM works WHERE account_id=? AND id=?',
                (self.account['id'], r['item_id'])).fetchone() for r in rows)
            yield rows
            cursor = data.get('cursor', 0)
            if not data.get('has_more') or (complete and not historical and known):
                self.store.set(key + ':complete', True)
                self.store.set(key + ':cursor', 0)
                break
            self.store.set(key + ':cursor', cursor)

    def recheck(self, ids):
        for start in range(0, len(ids), 20):
            yield self.request('/video/data/', {'open_id': self.account['id']},
                               {'item_ids': ids[start:start + 20]}).get('list', [])


def normalize(row, account):
    # Unknown official media types remain video; explicit import mapping can specify image.
    return {'account_id': account['id'], 'id': row['item_id'], 'title': row.get('title', ''),
        'description': row.get('description', ''), 'published_at': row.get('create_time', ''),
        'likes': row.get('statistics', {}).get('digg_count', 0), 'url': row.get('share_url', ''),
        'type': 'video', 'official_media_type': row.get('media_type')}
