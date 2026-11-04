
import time
from elastic_transport import ObjectApiResponse
from mcp.server.mcpserver import Context
from pydantic.fields import Field
from typing import Annotated, Any
from config.application_config import get_config
from data.app_resource import AppResources
from data.search_result import SearchResult
from data.news_query import NewsQuery
from data.mget_response import MGetResponse

import logging

from helpers.es_helper import append_latest_query, build_search_query, get_article_refs, category_query, prepare_response

log = logging.getLogger(__file__)

class NewsSearchTools:

    @staticmethod
    def article_search(user_query: Annotated[NewsQuery, Field(description=" Query for searching the Elasticsearch ")], ctx: Context[AppResources, Any]) -> SearchResult:
        start = time.time()
        log.debug(f'search intent incoming state : {user_query}')
        query = build_search_query(user_query.query, user_query.categories)
        if user_query.fetch_latest:
            query = append_latest_query(query)
        log.info(f'Query : {query}')
        try:
            response = ctx.request_context.lifespan_context.es.search(index=get_config("ES_INDEX"), **query)
        except Exception:
            log.exception('Exception while searching for articles for query: %s', query)
            raise

        log.info(f'Response from Elasticsearch : {response}, Duration in seconds (SEARCH) : { time.time() - start}')

        return SearchResult.model_validate({'article_refs': get_article_refs(response)})

    @staticmethod
    def category_search(categories: Annotated[list[str], Field(description=" Query for searching the Elasticsearch ")], ctx: Context[AppResources, Any]) -> int:
        """
        Run a terms aggregation on source.keyword to confirm at least one article
        exists for each requested category.  Falls back to returning the LLM
        categories as-is if ES has no 'category' field — the search agent will
        still use them as semantic query hints.
        """
        try:
            query = category_query(categories)
            log.info(f"Query getting executed: {query}")
            resp = ctx.request_context.lifespan_context.es.search(index=get_config("ES_INDEX"), **query)
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
        except Exception:  # noqa: BLE001
            log.exception("ES category verification failed skipping check.")

        return 0

    @staticmethod
    def mget(ids: Annotated[list[str], Field(description=" Elasticsearch record _id for fetching by id ")],
                    ctx: Context[AppResources, Any]) -> MGetResponse:
         result : ObjectApiResponse[Any] = ctx.request_context.lifespan_context.es.mget(
                    index=get_config("ES_INDEX"),
                    ids=ids)
        
         return prepare_response(result)

