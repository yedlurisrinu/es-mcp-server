import copy
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from elastic_transport import ObjectApiResponse
from mcp.server.mcpserver.exceptions import ToolError

from config.application_config import get_config
from data.article_hit import ArticleHit
from data.article_reference import ArticleReference
from data.mget_response import MGetResponse

log = logging.getLogger(__name__)

NO_ARTICLES_FOUND = "No articles found for the given client ids"


def get_article_refs(response: ObjectApiResponse[Any]) -> list[ArticleReference]:
    """Extract (article_id, score) references from an ES search response."""
    article_ref: list[ArticleReference] = []
    records = response.get("hits", {}).get("hits", [])
    for record in records:
        article_ref.append(
            ArticleReference.model_validate(
                {
                    "article_id": record.get("_source", {}).get("article_id"),
                    "score": record.get("_score"),
                }
            )
        )

    return article_ref


def append_latest_query(base: dict[str, Any]) -> dict[str, Any]:
    """Add a ``published_at`` range filter and a recency-first sort to the query.

    The lower bound is an absolute UTC timestamp (now - 7 days, ``%Y-%m-%dT%H:%M:%SZ``)
    computed here, not ES date math. It replaces any existing ``bool.filter``.
    """
    since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base["query"]["bool"]["filter"] = [{"range": {"published_at": {"gte": since}}}]
    base["sort"] = [
        {"published_at": {"order": "desc"}},
        "_score",
    ]
    return base


def build_search_query(user_query: str, categories: list[str]) -> Any:
    """Build the multi_match query from the template; drop the should clause when no categories."""
    query = copy.deepcopy(
        get_config("SEARCH_QUERY_TEMPLATE")
    )  # never mutate the loaded template
    base = query["query"]["bool"]
    base["must"][0]["multi_match"]["query"] = user_query
    terms = " ".join(c for c in categories)
    if terms:
        base["should"][0]["multi_match"]["query"] = terms
    else:
        base.pop("should")  # no categories → drop the clause
    return query


def category_query(categories: list[str]) -> Any:
    """Build a bool-should title-match ES query from the template, one clause per category.

    category_search only reads hits.total, so the template's aggregation (kept in config for
    later use) is not sent: Elasticsearch would compute it on every call for nothing. It also
    targets ``source.keyword``, which does not exist under the strict mapping (``source`` is
    itself a keyword field).
    """
    q = copy.deepcopy(get_config("CATEGORY_QUERY"))  # never mutate the loaded template
    q.pop("aggs", None)
    q["query"]["bool"]["should"] = [{"match": {"title": c}} for c in categories]
    return q


def prepare_response(hits: ObjectApiResponse[Any]) -> MGetResponse:
    # ES returns {"_id": ..., "found": false} (no _source) for ids that don't exist: skip those.
    docs = [doc for doc in hits.get("docs", []) if doc.get("found")]
    if not docs:
        raise ToolError(NO_ARTICLES_FOUND)
    content_length = get_config("ARTICLE_CONTENT_MAX_CHARS")
    truncate = get_config("TRUNCATE")
    articleHits: list[ArticleHit] = []
    for doc in docs:
        source: dict[str, str] = doc.get("_source", {})
        article_id = source.get("article_id")
        title = source.get("title")
        news_source = source.get("source")
        link = source.get("link")
        published_at = source.get("published_at")
        if truncate:
            content = source.get("content", "")[:content_length]
        else:
            content = source.get("content", "")
        articleHits.append(
            ArticleHit.model_validate(
                {
                    "article_id": article_id,
                    "title": title,
                    "source": news_source,
                    "link": link,
                    "published_at": published_at,
                    "content": content,
                }
            )
        )

    return MGetResponse.model_validate(
        {
            "article_hits": articleHits,
            "content_length": content_length,
            "truncated": truncate,
        }
    )
