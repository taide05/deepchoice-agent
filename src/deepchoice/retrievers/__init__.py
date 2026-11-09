from .arxiv_api import ArxivSearch
from .chroma_kb import ChromaKB
from .community import CommunitySearch
from .github_api import GitHubSearch
from .official import OfficialSearch
from .tavily_search import TavilySearch

RETRIEVER_REGISTRY = {
    "tavily": TavilySearch,
    "chroma": ChromaKB,
    "github": GitHubSearch,
    "arxiv": ArxivSearch,
    "community": CommunitySearch,
    "official": OfficialSearch,
}

__all__ = [
    "RETRIEVER_REGISTRY",
    "ArxivSearch",
    "ChromaKB",
    "CommunitySearch",
    "GitHubSearch",
    "OfficialSearch",
    "TavilySearch",
]
