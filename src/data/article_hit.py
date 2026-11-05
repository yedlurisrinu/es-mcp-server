from typing import Annotated

from pydantic import BaseModel
from pydantic.fields import Field


class ArticleHit(BaseModel):
    """A single retrieved news article."""

    article_id: Annotated[str, Field(description="article unique id")]
    title: Annotated[str, Field(description="title of the article ")]
    source: Annotated[str, Field(description=" source from where article is received ")]
    published_at: Annotated[str, Field(description=" date published ")]
    link: Annotated[str, Field(description=" The article complete link ")]
    content: Annotated[
        str,
        Field(
            description=" The content of the article, it might be truncated and check truncated and content_length for details  "
        ),
    ]
