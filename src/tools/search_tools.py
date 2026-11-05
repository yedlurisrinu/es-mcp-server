import logging
import time
from typing import Annotated, Any

from elastic_transport import ObjectApiResponse
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic.fields import Field

from config.application_config import get_config
from data.app_resource import AppResources
from data.mget_response import MGetResponse
from data.news_query import NewsQuery
from data.search_result import SearchResult
from helpers.es_helper import (
    append_latest_query,
    build_search_query,
    category_query,
    get_article_refs,
    prepare_response,
)

log = logging.getLogger(__name__)

CATEGORY_SEARCH_UNAVAILABLE = "Category search is unavailable"
ARTICLE_SEARCH_UNAVAILABLE = "Article search is unavailable"


class NewsSearchTools:
    @staticmethod
    def article_search(
        user_query: Annotated[
            NewsQuery,
            Field(
                description="The user query, its news categories and whether only recent articles are wanted"
            ),
        ],
        ctx: Context[AppResources, Any],
    ) -> SearchResult:
        start = time.time()
        log.debug(f"search intent incoming state : {user_query}")
        query = build_search_query(user_query.query, user_query.categories)
        if user_query.fetch_latest:
            query = append_latest_query(query)
        log.debug("Query : %s", query)
        try:
            response = ctx.request_context.lifespan_context.es.search(
                index=get_config("ES_INDEX"), **query
            )
        except Exception as exc:
            log.exception("Exception while searching for articles for query: %s", query)
            raise ToolError(ARTICLE_SEARCH_UNAVAILABLE) from exc

        article_refs = get_article_refs(response)
        log.info(
            "article_search: %d hits in %.3fs", len(article_refs), time.time() - start
        )
        return SearchResult.model_validate({"article_refs": article_refs})

    @staticmethod
    def category_search(
        categories: Annotated[
            list[str], Field(description="News categories, e.g. technology, politics")
        ],
        ctx: Context[AppResources, Any],
    ) -> int:
        """
        Count the indexed articles whose title matches any of the categories.

        An ES failure raises ``ToolError`` with fixed text (no hosts or messages).
        """
        try:
            query = category_query(categories)
            log.debug("Query getting executed: %s", query)
            resp = ctx.request_context.lifespan_context.es.search(
                index=get_config("ES_INDEX"), **query
            )
            total_hits = int(resp["hits"]["total"]["value"])
            if total_hits == 0:
                log.warning(
                    "No ES documents matched categories %s — proceeding anyway.",
                    categories,
                )
            else:
                log.info(
                    "Category check: %d documents matched for %s",
                    total_hits,
                    categories,
                )
            return total_hits
        except Exception as exc:
            log.exception("ES category verification failed")
            raise ToolError(CATEGORY_SEARCH_UNAVAILABLE) from exc

    @staticmethod
    def mget(
        ids: Annotated[
            list[str], Field(description="Article ids (as returned by article_search)")
        ],
        ctx: Context[AppResources, Any],
    ) -> MGetResponse:
        result: ObjectApiResponse[Any] = ctx.request_context.lifespan_context.es.mget(
            index=get_config("ES_INDEX"), ids=ids
        )

        return prepare_response(result)
