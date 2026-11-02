from typing import Any

from mcp.server.auth.provider import AccessToken

from joserfc import jwt, jws
from joserfc.errors import DecodeError, InvalidKeyIdError
from joserfc.jwk import KeySet
from joserfc.errors import JoseError
from config.application_config import get_config
import httpx2 
import time
from asyncio import Lock
import logging 
logger = logging.getLogger(__file__)

class RateLimitTokenVerifier:

    def __init__(self, issuer: str, audience :str):
        self.issuer = issuer
        self.jwks_uri = None
        self.audience = audience
        self._keys : KeySet | None = None
        self._last_called : float = 0.0
        self._last_success : float = 0.0
        self._lock = Lock()

    async def _keyset(self, kid: str = "dummy") -> KeySet | None:
        async with self._lock:
            if self._keys is None and (time.monotonic() - self._last_called) > 15:
                # call when the keys are none and _last_called more than 15 sec back, this will allow 15 sec 
                # window not to continuously trying if for any reason keycloak call is failing
                return await self.key_call()
            elif (time.monotonic() - self._last_called) > 30 and (time.monotonic() - self._last_success) > 30:
                # call when the keys are none and _last_called and _last_success more than 30 sec back, this will allow 30 sec 
                # window not to continuously trying if for any reason keycloak call is failing along with the last success call is more
                # than 30 sec ago
                try:
                    if self._keys is not None:
                        key = self._keys.get_by_kid(kid)
                    if key is not None:
                        return self._keys
                except InvalidKeyIdError as ke:
                    logger.error(f' re-check failed kid not found, continue with refresh - {ke}')          
                return await self.key_call()
        return self._keys          

    async def key_call(self) -> KeySet:
        try:
            async with httpx2.AsyncClient() as http:
                # check if jwks_uri exist if not Get the jwks_uri and cache it
                if self.jwks_uri is None:
                    result = await http.get(self.issuer+get_config('well_known_uri'))
                    meta = result.raise_for_status().json()
                    self.jwks_uri = meta.get('jwks_uri', None)
                    if self.jwks_uri is None:
                        raise ValueError(f"jwks key is missing in the AS response {meta}")
                self._keys = KeySet.import_key_set((await http.get(self.jwks_uri)).raise_for_status().json())       
                self._last_called = time.monotonic()
                self._last_success = time.monotonic()
        except Exception as e:
            self._last_called = time.monotonic()
            logger.error(f" Exception while importing key set Exception Type: {type(e)}, Exception Message: {e}")
            raise

        return self._keys
            
    def kid_of(self, token: str) -> str | None:
        try:
            # These are for reference
            # token.encode(encoding='utf-8',errors="strict")
            # token.encode()
            # bytes(token, encoding='utf-8')
            header = jws.extract_compact(token.encode()).headers()
            return header.get('kid', None)
        except DecodeError as e:
           logger.error(f"decode failure {e}")
           return None
        except Exception as e:
           logger.error(f" error {e}")
           return None
        
    """RFC 7515 makes kid OPTIONAL, and an issuer with a single key may omit it. Requiring kid is therefore a policy choice. 
    It’s valid here because Keycloak always sets kid. """  

    async def verify_token(self, token: str) -> AccessToken | None: 
        try:
            token_kid = self.kid_of(token)
            if token_kid is None :
                return None
            try:   
                keys = self._keys
                if self._keys is None:
                    keys = await self._keyset()
                elif not self._keys.get_by_kid(self.kid_of(token)):
                    # noting to do, if it raises invalid key id error, exception block will call _keyset
                    # otherwise, nothing to do, kid exist it will just proceed with decode
                    ... 

                decoded = jwt.decode(token, keys, algorithms=["RS256"])
            except InvalidKeyIdError: 
                decoded = jwt.decode(token, await self._keyset(token_kid), algorithms=["RS256"])  # key rotation
            jwt.JWTClaimsRegistry(iss={"essential": True, "value": self.issuer},
                                    aud={"essential": True, "value": self.audience},
                                    exp={"essential": True}).validate(decoded.claims)
        except (JoseError, ValueError) as e:
            logger.error(f"    [{self.audience}] verifier refused: {type(e).__name__}: {e}")
            return None
        except Exception as e:
            logger.error(f" Unknown Exception while verifying the token - Exception Type: {type(e)}, Exception Message: {e}")
            return None
        d_claims: dict[str, Any] = dict(decoded.claims)
        return AccessToken(token=token, client_id=str(d_claims.get("azp", "")), scopes=str(d_claims.get("scope", "")).split(),
                            expires_at=int(d_claims["exp"]), resource=self.audience, subject=str(d_claims.get("sub","")), claims=d_claims)


