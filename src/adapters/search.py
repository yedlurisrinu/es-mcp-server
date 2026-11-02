
"""
TODO in phase-1 I will be using multi match; embeddings, inference and sematic search will be completed later
Responsibility:
  Search the news_articles index using Elasticsearch semantic_text queries
  (inference handled with client-side embedding). 
  
  When fetch_latest=True, results are filtered to the most recent 7 days
  and sorted by published_at descending before semantic re-ranking.

Technology: Elasticsearch Python client (semantic query), TODO tracing.
"""

import copy
from typing import Any
from datetime import datetime, timezone, timedelta

from elastic_transport import ObjectApiResponse
from data.article_reference import ArticleReference
from data.search_result import SearchResult
from data.news_query import NewsQuery
from elasticsearch import Elasticsearch
from config.application_config import get_config

import time
import logging

logger = logging.getLogger(__file__)

class Search:
    """ retrieve candidate article references from Elasticsearch."""

    def __init__(self, es: Elasticsearch):
            """Store the shared chat model and Elasticsearch client."""
            self.es = es

    def __call__(self, user_query: NewsQuery) -> SearchResult:
        """Run the multi_match search (optionally filtered to the last 7 days) and return article refs + timing."""
        # Search es with query for the results
        # capture response time
        start = time.time()
        logger.debug(f'search intent incoming state : {user_query}')
        query = Search._build_search_query(user_query.query, user_query.categories)
        if user_query.fetch_latest:
            query = Search._append_latest_query(query)
        logger.info(f'Query : {query}')
        try:
            response = self.es.search(index=get_config("ES_INDEX"), **query)
        except Exception:
            logger.exception('Exception while searching for articles for query: %s', query)
            raise

        logger.info(f'Response from Elasticsearch : {response}')
        return {'article_refs':Search._get_article_refs(response), 'duration_seconds':{"SEARCH": time.time() - start}}
        
    @staticmethod
    def _get_article_refs(response: ObjectApiResponse[Any]) -> list[ArticleReference]:
        """Extract (article_id, score) references from an ES search response."""
        article_ref:list[ArticleReference] = []
        records = response.get('hits', {}).get("hits",[])
        for record in records:
            article_ref.append({"article_id":record.get("_source", {}).get("article_id"), "score": record.get("_score")})

        return article_ref
       
    @staticmethod
    def _append_latest_query(base: dict[str, Any]) -> dict[str, Any]:
        """Add a 7-day ``published_at`` range filter and a recency-first sort to the query."""
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        base["query"]["bool"]["filter"] = [{"range": {"published_at": {"gte": since}}}]
        base["sort"] = [
            {"published_at": {"order": "desc"}},
            "_score",
        ]
        return base
    
    @staticmethod
    def _build_search_query(user_query: str, categories : list[str]) -> Any:
        """Build the multi_match query from the template; drop the should clause when no categories."""
        query = copy.deepcopy(get_config("SEARCH_QUERY_TEMPLATE"))                  # never mutate the loaded template
        base = query["query"]["bool"]
        base["must"][0]["multi_match"]["query"] = user_query
        terms = " ".join(c for c in categories)
        if terms:
            base["should"][0]["multi_match"]["query"] = terms
        else:
            base.pop("should")                                       # no categories → drop the clause
        return query
