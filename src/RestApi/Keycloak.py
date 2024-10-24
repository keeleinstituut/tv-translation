from urllib.error import URLError

import jwt
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

from flask_principal import Identity


class Keycloak:
    def __init__(self, url, realm, client_id, client_secret):
        self.url = url
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwk_client = jwt.PyJWKClient(uri="{}/realms/{}/protocol/openid-connect/certs".format(self.url, self.realm))
        self.jwt_client = JwtClient(
            uri="{}/realms/{}/protocol/openid-connect/token".format(self.url, self.realm),
            client_id=self.client_id,
            client_secret=self.client_secret,
            keycloak=self)

    def get_jwk(self, kid):
        return self.jwk_client.get_signing_key(kid)

    def get_service_account_jwt(self, refresh=False):
        return self.jwt_client.get_jwt(refresh=refresh)


class JwtClient:
    def __init__(
            self,
            uri,
            client_id,
            client_secret,
            keycloak: Keycloak,
            headers=None,
            timeout: int = 30,
            ssl_context=None,
    ):
        self.keycloak = keycloak
        self.uri = uri
        self.client_id = client_id
        self.client_secret = client_secret
        self.headers = headers or {}
        self.timeout = timeout
        self.ssl_context = ssl_context
        self.cached_token = None
        self.cached_token_parsed = None

    def get_jwt(self, refresh=False):
        if not self.cached_token or self.is_cache_expired(leeway=0) or refresh:
            self._fetch_jwt()
        return self.cached_token

    def is_cache_expired(self, leeway=0):
        now = datetime.now(tz=timezone.utc).timestamp()
        exp = int(self.cached_token_parsed["exp"])

        return exp <= (now - leeway)

    def _fetch_jwt(self):
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials'
        }
        payload = urllib.parse.urlencode(data).encode()

        try:
            r = urllib.request.Request(url=self.uri, headers=self.headers, method='POST', data=payload)
            with urllib.request.urlopen(
                    r, timeout=self.timeout, context=self.ssl_context
            ) as response:
                data = json.load(response)
                access_token = data['access_token']
        except (URLError, TimeoutError) as e:
            raise f'Fail to fetch data from the url, err: "{e}"'
        else:
            return access_token
        finally:
            self.cached_token = access_token
            self.cached_token_parsed = self._decode_token(access_token)

    def _decode_token(self, token):
        header = jwt.get_unverified_header(token)

        alg = header["alg"]
        kid = header["kid"]
        jwk = self.keycloak.get_jwk(kid)
        return jwt.decode(token, jwk.key, algorithms=[alg], audience=['account'])


class KeycloakIdentity(Identity):
    def __init__(self, access_token, auth_type=None):
        institution_user_id = access_token['sub']
        super().__init__(
            id=institution_user_id,
            auth_type=auth_type)

        self.access_token = access_token

    @property
    def is_physical_user(self):
        return 'tolkevarav' in self.access_token

    @property
    def _tolkevarav_claim(self):
        return self.access_token.get('tolkevarav', {})

    @property
    def realm_access_roles(self):
        return self.access_token['realm_access']['roles']

    @property
    def institution_id(self):
        return self._tolkevarav_claim.get('selectedInstitution', {}).get('id')

    @property
    def institution_user_id(self):
        return self._tolkevarav_claim.get('institutionUserId')

    @property
    def institution_user_forename(self):
        return self._tolkevarav_claim.get('forename')

    @property
    def institution_user_surname(self):
        return self._tolkevarav_claim.get('surname')

    @property
    def institution_user_pic(self):
        return self._tolkevarav_claim.get('personalIdentificationCode')

    @property
    def department_id(self):
        return self._tolkevarav_claim.get('department', {}).get('id')

    @property
    def department_name(self):
        return self._tolkevarav_claim.get('department', {}).get('name')

    @property
    def privileges(self):
        return self._tolkevarav_claim.get('privileges')

    # Backwards compatibility purposes
    @property
    def scopes(self):
        return None

    # Backwards compatibility purposes
    @property
    def role(self):
        # return 'admin'
        return None
