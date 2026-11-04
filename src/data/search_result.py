from pydantic import BaseModel
from pydantic.fields import Field
from typing import Annotated

from data.article_reference import ArticleReference

class SearchResult(BaseModel):
    article_refs: Annotated[list[ArticleReference], Field(description="List of article references that have article_id and score")]
