from pydantic import BaseModel
from typing import Annotated
from pydantic.fields import Field
class ArticleReference(BaseModel):
    article_id: Annotated[str, Field(description=" A unique news article id ")]
    score: Annotated[float, Field(description=" the relevance score for the article ")]