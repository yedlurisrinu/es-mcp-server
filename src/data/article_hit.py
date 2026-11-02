from typing import TypedDict, Required

class ArticleHit(TypedDict):
    """A single retrieved news article."""
    title: Required[str]
    source: Required[str]
    published_at: Required[str]
    link: Required[str]