"""
tests/tools_test.py

The MCP contract and tool behaviour, through mcp's in-process Client against the real
ESMCPServer (Elasticsearch replaced by a MagicMock):
  - contract: server name/version, tool names, required args, ToolAnnotations
  - article_search / category_search / mget results and the ES calls behind them
  - expected failures → is_error with the fixed ToolError text
  - unexpected exceptions → is_error with generic text only (no hosts, ports or messages)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp import Client
from starlette.testclient import TestClient

from tests.conftest import es_doc, es_hit

pytestmark = pytest.mark.anyio

QUERY = {
    "user_query": {
        "query": "ai in healthcare",
        "categories": ["technology"],
        "fetch_latest": False,
    }
}


def _text(result: Any) -> str:
    return str(result.content[0].text)


class TestContract:
    async def test_server_name_and_version(self, client: Client) -> None:
        assert client.server_info is not None
        assert (client.server_info.name, client.server_info.version) == (
            "es-mcp-server",
            "1.0",
        )

    async def test_tool_names_and_required_args(self, client: Client) -> None:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"article_search", "category_search", "mget"}
        assert tools["article_search"].input_schema["required"] == ["user_query"]
        assert tools["category_search"].input_schema["required"] == ["categories"]
        assert tools["mget"].input_schema["required"] == ["ids"]
        user_query = tools["article_search"].input_schema["$defs"]["NewsQuery"]
        assert set(user_query["required"]) == {"query", "categories", "fetch_latest"}

    async def test_tools_are_annotated_read_only(self, client: Client) -> None:
        for tool in (await client.list_tools()).tools:
            a = tool.annotations
            assert a is not None, tool.name
            assert (
                a.read_only_hint,
                a.destructive_hint,
                a.idempotent_hint,
                a.open_world_hint,
            ) == (
                True,
                False,
                True,
                False,
            ), tool.name

    def test_health_route_reports_replica(self, mcp_server: Any) -> None:
        resp = TestClient(mcp_server.streamable_http_app()).get("/healthz")
        assert resp.status_code == 200 and resp.json() == {
            "status": "ok",
            "replica": "r-test",
        }
        assert resp.headers["x-replica-id"] == "r-test"


class TestArticleSearch:
    async def test_returns_refs_from_es_hits(
        self, client: Client, es: MagicMock
    ) -> None:
        es.search.return_value = {
            "hits": {"hits": [es_hit("a1", 2.5), es_hit("a2", 1.0)]}
        }
        result = await client.call_tool("article_search", QUERY)
        assert not result.is_error
        assert result.structured_content == {
            "article_refs": [
                {"article_id": "a1", "score": 2.5},
                {"article_id": "a2", "score": 1.0},
            ]
        }
        kwargs = es.search.call_args.kwargs
        assert kwargs["index"] == "news_articles"
        assert (
            kwargs["query"]["bool"]["must"][0]["multi_match"]["query"]
            == "ai in healthcare"
        )

    async def test_fetch_latest_adds_recency_filter_and_sort(
        self, client: Client, es: MagicMock
    ) -> None:
        args = {"user_query": {**QUERY["user_query"], "fetch_latest": True}}
        await client.call_tool("article_search", args)
        kwargs = es.search.call_args.kwargs
        assert "range" in kwargs["query"]["bool"]["filter"][0]
        assert kwargs["sort"][0] == {"published_at": {"order": "desc"}}

    async def test_es_failure_is_fixed_tool_error_without_internals(
        self, client: Client, es: MagicMock
    ) -> None:
        es.search.side_effect = ConnectionError("elasticsearch:9200 refused")
        result = await client.call_tool("article_search", QUERY)
        assert (
            result.is_error
            and _text(result)
            == "Error executing tool article_search: Article search is unavailable"
        )
        assert "9200" not in _text(result)

    async def test_invalid_arguments_are_rejected(
        self, client: Client, es: MagicMock
    ) -> None:
        result = await client.call_tool(
            "article_search", {"user_query": {"query": "q"}}
        )
        assert result.is_error
        es.search.assert_not_called()


class TestCategorySearch:
    async def test_returns_total_hits(self, client: Client, es: MagicMock) -> None:
        es.search.return_value = {"hits": {"total": {"value": 13}, "hits": []}}
        result = await client.call_tool(
            "category_search", {"categories": ["technology", "ai"]}
        )
        assert not result.is_error and result.structured_content == {"result": 13}
        should = es.search.call_args.kwargs["query"]["bool"]["should"]
        assert should == [
            {"match": {"title": "technology"}},
            {"match": {"title": "ai"}},
        ]

    async def test_zero_hits_is_not_an_error(
        self, client: Client, es: MagicMock
    ) -> None:
        es.search.return_value = {"hits": {"total": {"value": 0}, "hits": []}}
        result = await client.call_tool("category_search", {"categories": ["nothing"]})
        assert not result.is_error and result.structured_content == {"result": 0}

    async def test_es_failure_is_fixed_tool_error(
        self, client: Client, es: MagicMock
    ) -> None:
        es.search.side_effect = ConnectionError("elasticsearch:9200 refused")
        result = await client.call_tool(
            "category_search", {"categories": ["technology"]}
        )
        assert result.is_error
        assert (
            _text(result)
            == "Error executing tool category_search: Category search is unavailable"
        )


class TestMget:
    async def test_returns_articles_truncated_to_1000_chars(
        self, client: Client, es: MagicMock
    ) -> None:
        es.mget.return_value = {"docs": [es_doc("a1", content="x" * 1500)]}
        result = await client.call_tool("mget", {"ids": ["a1"]})
        assert not result.is_error
        body = result.structured_content
        assert (
            body is not None
            and body["truncated"] is True
            and body["content_length"] == 1000
        )
        assert len(body["article_hits"][0]["content"]) == 1000
        assert es.mget.call_args.kwargs == {"index": "news_articles", "ids": ["a1"]}

    async def test_missing_ids_are_skipped(self, client: Client, es: MagicMock) -> None:
        es.mget.return_value = {"docs": [es_doc("a1"), {"_id": "gone", "found": False}]}
        result = await client.call_tool("mget", {"ids": ["a1", "gone"]})
        assert not result.is_error
        assert [h["article_id"] for h in result.structured_content["article_hits"]] == [
            "a1"
        ]  # type: ignore[index]

    async def test_all_ids_missing_is_fixed_tool_error(
        self, client: Client, es: MagicMock
    ) -> None:
        es.mget.return_value = {"docs": [{"_id": "gone", "found": False}]}
        result = await client.call_tool("mget", {"ids": ["gone"]})
        assert result.is_error
        assert (
            _text(result)
            == "Error executing tool mget: No articles found for the given client ids"
        )

    async def test_es_failure_is_generic_error_without_internals(
        self, client: Client, es: MagicMock
    ) -> None:
        es.mget.side_effect = RuntimeError("api key rejected by elasticsearch:9200")
        result = await client.call_tool("mget", {"ids": ["a1"]})
        assert result.is_error and _text(result) == "Error executing tool mget"
