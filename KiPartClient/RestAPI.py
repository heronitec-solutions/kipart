import json
import requests
from requests.exceptions import ConnectionError
import urllib.parse


class ApiError(Exception):
    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _format_in_use(body):
    lines = [body.get('error') or 'Delete rejected: still in use']
    for item in body.get('inUse') or []:
        users = ", ".join(
            f"{ref.get('entity')} '{ref.get('name')}'" for ref in (item.get('usedBy') or [])
        )
        lines.append(
            f"  {item.get('entity')} '{item.get('name') or item.get('uuid')}' is still used by {users}."
        )
    return "\n".join(lines)


class CommitConflict(Exception):
    def __init__(self, conflicts, message=None):
        super().__init__(message or "Commit conflict")
        self.conflicts = conflicts or []


_access_cache = {}


class RestAPI:
    def __init__(self, config, api_name=""):
        self._config = config
        self._api_name = api_name
        self.lastInfo = None
        self._access = None

    def _token(self):
        return self._config.get('api_user_token') or ''

    def permissions(self):
        """Rights of the configured API token. Cached per token for this process."""
        if self._access is not None:
            return self._access
        token = self._token()
        cached = _access_cache.get(token)
        if cached is not None:
            self._access = cached
            return cached
        try:
            response = requests.get(self._base() + '/auth/me', headers=self._headers())
        except ConnectionError:
            raise ApiError('Failed to connect to API')
        if response.status_code == 200:
            self._access = response.json()
        elif response.status_code == 401:
            self._access = {
                'authenticated': False,
                'canRead': False,
                'canWrite': False,
                'error': 'invalid token',
            }
        elif response.status_code == 404:
            self._access = {
                'authenticated': False,
                'canRead': True,
                'canWrite': True,
                'legacy': True,
            }
        else:
            raise self._apiError(response)
        _access_cache[token] = self._access
        return self._access

    def _known_access(self):
        if self._access is not None:
            return self._access
        return _access_cache.get(self._token())

    def _require_write(self):
        access = self._known_access()
        if not access or access.get('legacy') or access.get('canWrite'):
            return
        if access.get('error') == 'invalid token':
            raise ApiError(
                'The API token was rejected. Create a token in your KiPart account.',
                status_code=401,
            )
        if not access.get('authenticated'):
            raise ApiError(
                'Uploads require an API token with write permission.',
                status_code=401,
            )
        if access.get('authType') == 'api-token':
            raise ApiError(
                'This API token is read-only. Create a token with write permission under My Account.',
                status_code=403,
            )
        name = access.get('username') or 'This account'
        raise ApiError(f"{name} has read-only access. Uploads were not sent.", status_code=403)

    def _headers(self, extra=None):
        headers = {'AUTHORIZATION': self._config.get('api_user_token') or ''}
        if extra:
            headers.update(extra)
        return headers

    def _base(self):
        return self._config['api_url'].rstrip('/')

    def _apiError(self, response):
        body = response.text.strip().replace('\n', ' ')
        if len(body) > 500:
            body = body[:500] + '...'
        parsed = None
        try:
            parsed = response.json()
        except Exception:
            parsed = body
        return ApiError(
            f"API communication failed: {response.request.method} {response.url} -> {response.status_code} {response.reason}: {body}",
            status_code=response.status_code,
            body=parsed,
        )

    def checkConnectionStatus(self):
        try:
            info = self.info()
            self.lastInfo = info
            if not info:
                return False
            api_version = info.get('apiVersion', 0)
            if api_version is None:
                api_version = 0
            if int(api_version) < 2:
                return False
            return True
        except Exception:
            return False

    def info(self):
        try:
            response = requests.get(self._base() + '/info', headers=self._headers())
            if response.status_code == 200:
                self.lastInfo = response.json()
                return self.lastInfo
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def getList(self, sort_by='id', sort_order='asc'):
        try:
            response = requests.get(
                self._base() + '/' + self._api_name
                + '?_sort=' + urllib.parse.quote_plus(sort_by)
                + '&_order=' + urllib.parse.quote_plus(sort_order),
                headers=self._headers(),
            )
            if response.status_code == 200:
                return response.json()
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def getFilteredList(self, filter_by, filter_value, sort_by='id', sort_order='asc'):
        try:
            response = requests.get(
                self._base() + '/' + self._api_name
                + '?_sort=' + urllib.parse.quote_plus(sort_by)
                + '&_order=' + urllib.parse.quote_plus(sort_order)
                + '&_filterby=' + urllib.parse.quote_plus(filter_by)
                + '&_filter=' + urllib.parse.quote_plus(str(filter_value)),
                headers=self._headers(),
            )
            if response.status_code == 200:
                return response.json()
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def getFiltered(self, filter_by, filter_value, sort_by='id', sort_order='asc'):
        return self.getFilteredList(filter_by, filter_value, sort_by, sort_order)

    def get(self, id):
        try:
            response = requests.get(
                self._base() + '/' + self._api_name + '/' + str(id),
                headers=self._headers(),
            )
            if response.status_code == 200:
                return response.json()
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def add(self, data):
        self._require_write()
        try:
            response = requests.post(
                self._base() + '/' + self._api_name,
                json=data,
                headers=self._headers(),
            )
            if response.status_code in (200, 201):
                return response.json()
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def update(self, id, data):
        self._require_write()
        try:
            response = requests.put(
                self._base() + '/' + self._api_name + '/' + str(id),
                json=data,
                headers=self._headers(),
            )
            if response.status_code == 200:
                return response.json()
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def delete(self, id):
        self._require_write()
        try:
            response = requests.delete(
                self._base() + '/' + self._api_name + '/' + str(id),
                headers=self._headers(),
            )
            if response.status_code == 204:
                return True
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def searchForFilenameAndPath(self, filename, path):
        try:
            if path != '':
                if not path.endswith('/'):
                    path += '/'
                response = requests.get(
                    self._base() + '/' + self._api_name + '/searchbyfilename?_filename='
                    + urllib.parse.quote_plus(filename) + '&_path=' + urllib.parse.quote_plus(path),
                    headers=self._headers(),
                )
            else:
                response = requests.get(
                    self._base() + '/' + self._api_name + '/searchbyfilename?_filename='
                    + urllib.parse.quote_plus(filename),
                    headers=self._headers(),
                )

            if response.status_code == 200:
                data = response.json()
                return data if data else None
            if response.status_code == 404:
                return None
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def blobExists(self, hashes):
        try:
            response = requests.post(
                self._base() + '/blob/exists',
                json=list(hashes or []),
                headers=self._headers(),
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('missing', [])
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def putBlob(self, hash, data, media_type):
        self._require_write()
        try:
            response = requests.put(
                self._base() + '/blob/' + hash,
                data=data,
                headers=self._headers({'X-Media-Type': media_type, 'Content-Type': 'application/octet-stream'}),
            )
            if response.status_code in (200, 201):
                return True
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def getBlob(self, hash):
        try:
            response = requests.get(
                self._base() + '/blob/' + hash,
                headers=self._headers(),
            )
            if response.status_code == 200:
                return response.content
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def commit(self, payload):
        self._require_write()
        try:
            response = requests.post(
                self._base() + '/commit',
                json=payload,
                headers=self._headers(),
            )
            if response.status_code == 201:
                return response.json()
            if response.status_code == 409:
                body = {}
                try:
                    body = response.json()
                except Exception:
                    pass
                if body.get('inUse'):
                    raise ApiError(_format_in_use(body), status_code=409, body=body)
                raise CommitConflict(body.get('conflicts', []), message=str(body))
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def getHistory(self, entity, id):
        try:
            response = requests.get(
                self._base() + '/' + entity + '/' + str(id) + '/history',
                headers=self._headers(),
            )
            if response.status_code == 200:
                return response.json()
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')

    def getChangesSince(self, commit_id):
        try:
            response = requests.get(
                self._base() + '/sync/changes',
                params={'sinceCommitId': int(commit_id or 0)},
                headers=self._headers(),
            )
            if response.status_code == 200:
                return response.json()
            raise self._apiError(response)
        except ConnectionError:
            raise ApiError('Failed to connect to API')
