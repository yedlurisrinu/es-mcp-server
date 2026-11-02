
__all__ = ["search"]

from contextvars import Context
from mcp.server.mcpserver import Context
from pydantic.fields import Field
from typing import Annotated, Any


from data.app_resource import AppResources
from data.search_result import SearchResult
from data.news_query import NewsQuery

# def search(query: Annotated[NewsQuery, Field(description=" Query for searching the Elasticsearch ")] , ctx: Context[AppResources, Any]) -> SearchResult:
#     print(f" Search called ... {ctx.request_context.lifespan_context.es}")
#     return ctx.request_context.lifespan_context.search(query=query)

def search(query: Annotated[str, Field(description=" Query for searching the Elasticsearch ")]) -> str:
    print(f" Search called ...")
    return "success"

# def get(article_id: Annotated[str, Field(description=" Elasticsearch record _id for fetching by id ")]) -> :
#     print(" Get called ... ")


# def mget(id: Annotated[list[str], Field(description=" Elasticsearch record _id for fetching by id ")]):
#     print(" Get called ... ")
