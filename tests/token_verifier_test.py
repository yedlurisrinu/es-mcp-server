"""
tests/token_verifier_test.py

RateLimitTokenVerifier against a fake Keycloak served over httpx2.MockTransport:
  - a valid RS256 token → AccessToken (client_id, scopes, subject, expiry, resource)
  - rejected: wrong aud, wrong iss, expired, unpinned alg (HS256), no kid, garbage
  - discovery metadata whose issuer doesn't match is refused (M5)
  - key rotation: unknown kid triggers one JWKS refresh
  - Keycloak down: refused, and no refetch inside the 15s back-off window
"""

from __future__ import annotations

import time
from typing import Any

import httpx2
import pytest
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey

from server.token_verifier import RateLimitTokenVerifier

pytestmark = pytest.mark.anyio

ISSUER = "http://keycloak:8180/realms/es-mcp"
AUDIENCE = "http://es-mcp-lb:9599/mcp"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"


class FakeKeycloak:
    def __init__(self) -> None:
        self.keys = [RSAKey.generate_key(2048, parameters={"kid": "k1"})]
        self.metadata_issuer = ISSUER
        self.down = False
        self.requests: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.requests.append(url)
        if self.down:
            return httpx2.Response(503)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return httpx2.Response(200, json={"issuer": self.metadata_issuer, "jwks_uri": JWKS_URL})
        if url == JWKS_URL:
            return httpx2.Response(200, json={"keys": [k.as_dict(private=False) for k in self.keys]})
        return httpx2.Response(404)

    def token(self, key: RSAKey | None = None, alg: str = "RS256", **claims: Any) -> str:
        now = int(time.time())
        body = {"iss": ISSUER, "aud": AUDIENCE, "exp": now + 300, "iat": now, "sub": "svc",
                "azp": "news-summary-app-svc", "scope": "openid mcp"} | claims
        signing_key = key or self.keys[0]
        header = {"alg": alg, "kid": signing_key.kid} if signing_key.kid else {"alg": alg}
        return jwt.encode(header, body, signing_key)


@pytest.fixture()
def kc() -> FakeKeycloak:
    return FakeKeycloak()


@pytest.fixture()
async def verifier(kc: FakeKeycloak):
    v = RateLimitTokenVerifier(ISSUER, AUDIENCE, http_transport=httpx2.MockTransport(kc.handler))
    yield v
    await v.aclose()


async def test_valid_token_is_accepted(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    access = await verifier.verify_token(kc.token())
    assert access is not None
    assert access.client_id == "news-summary-app-svc" and access.subject == "svc"
    assert access.scopes == ["openid", "mcp"] and access.resource == AUDIENCE
    assert access.expires_at is not None and access.expires_at > time.time()


async def test_keys_are_cached_between_tokens(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    await verifier.verify_token(kc.token())
    await verifier.verify_token(kc.token())
    assert kc.requests.count(JWKS_URL) == 1


@pytest.mark.parametrize(
    "claims",
    [{"aud": "http://other/mcp"}, {"iss": "http://keycloak:8180/realms/other"}, {"exp": int(time.time()) - 10}],
    ids=["wrong_aud", "wrong_iss", "expired"],
)
async def test_bad_claims_are_rejected(kc: FakeKeycloak, verifier: RateLimitTokenVerifier, claims: dict[str, Any]) -> None:
    assert await verifier.verify_token(kc.token(**claims)) is None


async def test_unpinned_algorithm_is_rejected(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    hs_key = OctKey.generate_key(256, parameters={"kid": "k1"})
    token = jwt.encode({"alg": "HS256", "kid": "k1"}, {"iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 300}, hs_key)
    assert await verifier.verify_token(token) is None


async def test_token_without_kid_is_rejected(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    no_kid = RSAKey.generate_key(2048)
    assert await verifier.verify_token(kc.token(key=no_kid)) is None
    assert kc.requests == []  # refused before any key fetch


async def test_garbage_is_rejected(verifier: RateLimitTokenVerifier) -> None:
    assert await verifier.verify_token("not-a-jwt") is None


async def test_discovery_issuer_mismatch_is_refused(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    kc.metadata_issuer = "http://evil/realms/es-mcp"
    assert await verifier.verify_token(kc.token()) is None
    assert JWKS_URL not in kc.requests


async def test_key_rotation_refreshes_jwks(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    assert await verifier.verify_token(kc.token()) is not None
    new_key = RSAKey.generate_key(2048, parameters={"kid": "k2"})
    kc.keys.append(new_key)
    verifier._last_called = verifier._last_success = time.monotonic() - 31  # outside the 30s window
    assert await verifier.verify_token(kc.token(key=new_key)) is not None
    assert kc.requests.count(JWKS_URL) == 2


async def test_discovery_without_jwks_uri_is_refused(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    original = kc.handler

    def no_jwks(request: httpx2.Request) -> httpx2.Response:
        if str(request.url).endswith("/.well-known/openid-configuration"):
            return httpx2.Response(200, json={"issuer": ISSUER})
        return original(request)

    v = RateLimitTokenVerifier(ISSUER, AUDIENCE, http_transport=httpx2.MockTransport(no_jwks))
    try:
        assert await v.verify_token(kc.token()) is None
    finally:
        await v.aclose()


async def test_known_kid_after_window_is_served_from_cache(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    await verifier.verify_token(kc.token())
    verifier._last_called = verifier._last_success = time.monotonic() - 31
    assert await verifier._keyset("k1") is verifier._keys  # kid present: no refetch
    assert kc.requests.count(JWKS_URL) == 1


async def test_unknown_kid_inside_window_is_refused(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    await verifier.verify_token(kc.token())
    stranger = RSAKey.generate_key(2048, parameters={"kid": "k-unknown"})
    assert await verifier.verify_token(kc.token(key=stranger)) is None
    assert kc.requests.count(JWKS_URL) == 1  # inside the 30s window: no refetch


async def test_kid_of_unexpected_error_is_none(verifier: RateLimitTokenVerifier) -> None:
    assert verifier.kid_of(None) is None  # type: ignore[arg-type]


async def test_keycloak_down_refuses_and_backs_off(kc: FakeKeycloak, verifier: RateLimitTokenVerifier) -> None:
    kc.down = True
    assert await verifier.verify_token(kc.token()) is None
    fetches = len(kc.requests)
    assert await verifier.verify_token(kc.token()) is None
    assert len(kc.requests) == fetches  # inside the 15s back-off: no new fetch
