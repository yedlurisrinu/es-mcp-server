"""
conftest.py — shared fixtures for es-mcp-server tests (no Elasticsearch, Keycloak or Vault).

  - the real resources/application-config.yaml, loaded once
  - ``anyio_backend``: async tests use anyio's pytest plugin (``@pytest.mark.anyio``)
  - ``es``: a MagicMock Elasticsearch client
  - ``mcp_server`` / ``client``: the real ESMCPServer, with its lifespan swapped for one
    that yields ``AppResources(es=<the mock>)``, reached through mcp's in-process Client
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from data.app_resource import AppResources


@pytest.fixture(scope="session", autouse=True)
def _load_app_config() -> None:
    from config.application_config import load_config

    load_config()


@pytest.fixture(autouse=True)
def _symmetric_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Normally loaded from Vault (secret/CREDENTIALS) at startup.
    monkeypatch.setenv("ES_MCP_SERVER_SHARED_SYMMETRIC_KEY", "k" * 32)


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


def es_hit(article_id: str, score: float = 1.0) -> dict[str, Any]:
    return {"_source": {"article_id": article_id}, "_score": score}


def es_doc(article_id: str, content: str = "body text") -> dict[str, Any]:
    return {
        "_id": article_id,
        "found": True,
        "_source": {
            "article_id": article_id,
            "title": f"Title {article_id}",
            "source": "TechNews",
            "link": f"https://technews.example.com/{article_id}",
            "published_at": "2026-11-01T10:00:00Z",
            "content": content,
        },
    }


@pytest.fixture()
def es() -> MagicMock:
    es = MagicMock()
    es.search.return_value = {
        "hits": {"total": {"value": 1}, "hits": [es_hit("a1", 2.5)]}
    }
    es.mget.return_value = {"docs": [es_doc("a1")]}
    return es


@pytest.fixture()
def mcp_server(es: MagicMock) -> MCPServer[Any]:
    from server.mcp_server import ESMCPServer

    @asynccontextmanager
    async def fake_lifespan(
        server: MCPServer[AppResources],
    ) -> AsyncIterator[AppResources]:
        yield AppResources(es=es)

    return ESMCPServer(fake_lifespan).create_mcp_server(replica_id="r-test")


@pytest.fixture()
async def client(mcp_server: MCPServer[Any]) -> AsyncIterator[Client]:
    async with Client(mcp_server) as c:
        yield c
