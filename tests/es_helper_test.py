"""
tests/es_helper_test.py

ES query builders and response mappers (moved here from news-summary-agent when the app
stopped talking to Elasticsearch directly):
  - build_search_query: user query on multi_match; categories as a should clause, dropped
    when there are none; the loaded template is never mutated
  - append_latest_query: 7-day published_at filter plus recency-first sort
  - category_query: one title match per category
  - get_article_refs / prepare_response: hits → refs, mget docs → ArticleHits
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import config.application_config as app_config
from config.application_config import get_config
from helpers.es_helper import (
    NO_ARTICLES_FOUND,
    append_latest_query,
    build_search_query,
    category_query,
    get_article_refs,
    prepare_response,
)
from tests.conftest import es_doc, es_hit


class TestBuildSearchQuery:
    def test_sets_user_query_on_multi_match(self) -> None:
        q = build_search_query("ai in healthcare", ["technology"])
        assert q["query"]["bool"]["must"][0]["multi_match"]["query"] == "ai in healthcare"

    def test_categories_joined_into_should(self) -> None:
        q = build_search_query("q", ["technology", "health"])
        assert q["query"]["bool"]["should"][0]["multi_match"]["query"] == "technology health"

    def test_should_dropped_when_no_categories(self) -> None:
        assert "should" not in build_search_query("q", [])["query"]["bool"]

    def test_does_not_mutate_template(self) -> None:
        before = copy.deepcopy(get_config("SEARCH_QUERY_TEMPLATE"))
        build_search_query("q", [])
        build_search_query("other", ["x"])
        assert get_config("SEARCH_QUERY_TEMPLATE") == before


class TestAppendLatestQuery:
    def test_adds_range_filter_and_sort(self) -> None:
        q = append_latest_query(build_search_query("q", []))
        since = q["query"]["bool"]["filter"][0]["range"]["published_at"]["gte"]
        age = datetime.now(timezone.utc) - datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        assert timedelta(days=7) - timedelta(minutes=1) < age < timedelta(days=7, minutes=1)
        assert q["sort"] == [{"published_at": {"order": "desc"}}, "_score"]


class TestCategoryQuery:
    def test_one_should_clause_per_category(self) -> None:
        q = category_query(["technology", "ai"])
        assert q["query"]["bool"]["should"] == [{"match": {"title": "technology"}}, {"match": {"title": "ai"}}]

    def test_aggregation_is_not_sent(self) -> None:
        q = category_query(["technology"])
        assert q["size"] == 0 and "aggs" not in q  # category_search only reads hits.total
        assert "aggs" in get_config("CATEGORY_QUERY")  # the definition stays in config

    def test_does_not_mutate_loaded_template(self) -> None:
        category_query(["technology"])
        assert get_config("CATEGORY_QUERY")["query"]["bool"]["should"] == []


class TestGetArticleRefs:
    def test_parses_hits(self) -> None:
        refs = get_article_refs({"hits": {"hits": [es_hit("a1", 2.0), es_hit("a2", 1.5)]}})  # type: ignore[arg-type]
        assert [(r.article_id, r.score) for r in refs] == [("a1", 2.0), ("a2", 1.5)]

    def test_empty_hits(self) -> None:
        assert get_article_refs({"hits": {"hits": []}}) == []  # type: ignore[arg-type]
        assert get_article_refs({}) == []  # type: ignore[arg-type]


class TestPrepareResponse:
    def test_maps_docs_and_truncates(self) -> None:
        resp = prepare_response({"docs": [es_doc("a1", content="x" * 1500)]})  # type: ignore[arg-type]
        (hit,) = resp.article_hits
        assert (hit.article_id, hit.title, hit.source) == ("a1", "Title a1", "TechNews")
        assert len(hit.content) == 1000 and resp.truncated is True and resp.content_length == 1000

    def test_no_truncation_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(app_config.app_config, "TRUNCATE", False)
        resp = prepare_response({"docs": [es_doc("a1", content="x" * 1500)]})  # type: ignore[arg-type]
        assert len(resp.article_hits[0].content) == 1500 and resp.truncated is False

    def test_skips_not_found_and_fails_when_none_found(self) -> None:
        resp = prepare_response({"docs": [es_doc("a1"), {"_id": "x", "found": False}]})  # type: ignore[arg-type]
        assert [h.article_id for h in resp.article_hits] == ["a1"]
        with pytest.raises(ToolError, match=NO_ARTICLES_FOUND):
            prepare_response({"docs": [{"_id": "x", "found": False}]})  # type: ignore[arg-type]
        with pytest.raises(ToolError, match=NO_ARTICLES_FOUND):
            prepare_response({"docs": []})  # type: ignore[arg-type]
