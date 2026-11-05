import logging
import time
from asyncio import Lock
from typing import Any

import httpx2
from joserfc import jws, jwt
from joserfc.errors import DecodeError, InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet
from mcp.server.auth.provider import AccessToken

from config.application_config import get_config

logger = logging.getLogger(__name__)


class JWKSUnavailable(Exception): ...


class RateLimitTokenVerifier:
    def __init__(self, issuer: str, audience: str, http_transport: Any | None = None):
        self.issuer = issuer
        self.jwks_uri = None
        self.audience = audience
        self._keys: KeySet | None = None
        self._last_called: float = 0.0
        self._last_success: float = 0.0
        self._lock = Lock()
        # one client for all JWKS/discovery fetches; closed by aclose() at server shutdown.
        # http_transport is a test seam (e.g. httpx2.MockTransport); None means the real network.
        self._http = httpx2.AsyncClient(
            timeout=float(get_config("jwks_http_timeout_sec")), transport=http_transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _keyset(self, kid: str = "dummy") -> KeySet | None:
        async with self._lock:
            if self._keys is None and (time.monotonic() - self._last_called) > 15:
                # No JWKS loaded yet: fetch, but at most once every 15 s, so a failing Keycloak
                # is not hammered. Inside the window None is returned (caller raises JWKSUnavailable).
                return await self.key_call()
            elif (time.monotonic() - self._last_called) > 30 and (
                time.monotonic() - self._last_success
            ) > 30:
                # Refresh (unknown kid / rotation) at most once every 30 s: both the last attempt and the
                # last success must be older than 30 s. Once keys are cached, a failed refresh is
                # therefore retried only after 30 s, and the cached keys are returned in between.
                try:
                    if self._keys is not None:
                        key = self._keys.get_by_kid(kid)
                    if key is not None:
                        return self._keys
                except InvalidKeyIdError as ke:
                    logger.warning(
                        f" re-check failed kid not found, continue with refresh - {ke}"
                    )
                return await self.key_call()
        return self._keys

    async def key_call(self) -> KeySet:
        try:
            # check if jwks_uri exist if not Get the jwks_uri and cache it
            if self.jwks_uri is None:
                result = await self._http.get(
                    self.issuer + get_config("well_known_uri")
                )
                meta = result.raise_for_status().json()
                if meta.get("issuer") != self.issuer:
                    raise ValueError(
                        f"AS metadata issuer {meta.get('issuer')} does not match configured issuer {self.issuer}"
                    )
                self.jwks_uri = meta.get("jwks_uri", None)
                if self.jwks_uri is None:
                    raise ValueError(f"jwks key is missing in the AS response {meta}")
            self._keys = KeySet.import_key_set(
                (await self._http.get(self.jwks_uri)).raise_for_status().json()
            )
            self._last_called = time.monotonic()
            self._last_success = time.monotonic()
        except Exception as e:
            self._last_called = time.monotonic()
            logger.error(
                f" Exception while importing key set Exception Type: {type(e)}, Exception Message: {e}"
            )
            raise

        return self._keys

    def kid_of(self, token: str) -> str | None:
        try:
            header = jws.extract_compact(token.encode()).headers()
            return header.get("kid", None)
        except DecodeError as e:
            logger.warning(f"decode failure {e}")
            return None
        except Exception as e:  # noqa: BLE001 - any header failure means no kid, so the token is refused
            logger.error(f" error {e}")
            return None

    """RFC 7515 makes kid OPTIONAL, and an issuer with a single key may omit it. Requiring kid is therefore a policy choice. 
    It’s valid here because Keycloak always sets kid. """

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            token_kid = self.kid_of(token)
            if token_kid is None:
                return None
            try:
                keys = self._keys
                if self._keys is None:
                    keys = await self._keyset()
                elif not self._keys.get_by_kid(self.kid_of(token)):
                    # noting to do, if it raises invalid key id error, exception block will call _keyset
                    # otherwise, nothing to do, kid exist it will just proceed with decode
                    ...
                if keys is None:
                    raise JWKSUnavailable("missing keys")
                decoded = jwt.decode(token, keys, algorithms=["RS256"])
            except InvalidKeyIdError:
                keys = await self._keyset(token_kid)
                if keys is None:
                    raise JWKSUnavailable("missing keys")
                decoded = jwt.decode(token, keys, algorithms=["RS256"])  # key rotation

            jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": self.issuer},
                aud={"essential": True, "value": self.audience},
                exp={"essential": True},
            ).validate(decoded.claims)
        except (JoseError, ValueError) as e:
            logger.warning(
                f"    [{self.audience}] verifier refused: {type(e).__name__}: {e}"
            )
            return None
        except Exception as e:  # noqa: BLE001 - any verifier failure refuses the token (401), never a 500
            logger.error(
                f" Unknown Exception while verifying the token - Exception Type: {type(e)}, Exception Message: {e}"
            )
            return None
        d_claims: dict[str, Any] = dict(decoded.claims)
        return AccessToken(
            token=token,
            client_id=str(d_claims.get("azp", "")),
            scopes=str(d_claims.get("scope", "")).split(),
            expires_at=int(d_claims["exp"]),
            resource=self.audience,
            subject=str(d_claims.get("sub", "")),
            claims=d_claims,
        )
