from data.article_hit import ArticleHit
from pydantic import BaseModel

class MGetResponse(BaseModel):
    article_hits: list[ArticleHit]
    content_length : int = 1000
    truncated : bool = True