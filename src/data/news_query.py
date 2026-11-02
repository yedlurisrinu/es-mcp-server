from typing import Annotated

from pydantic import BaseModel, Field

class NewsQuery(BaseModel):
    query: Annotated[str,Field(..., description="original user query should always present")]
    categories: Annotated[list[str], Field(..., description="extracted news categories")]
    fetch_latest: Annotated[bool, Field(description="recency intent")]