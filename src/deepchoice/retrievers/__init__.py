from .tavily_search import TavilySearch
from .chroma_kb import ChromaKB
from .github_api import GitHubSearch
from .arxiv_api import ArxivSearch
from .community import CommunitySearch
from .official import OfficialSearch

RETRIEVER_REGISTRY = {
    "tavily": TavilySearch,
    "chroma": ChromaKB,
    "github": GitHubSearch,
    "arxiv": ArxivSearch,
    "community": CommunitySearch,
    "official": OfficialSearch,
}

__all__ = [
    "TavilySearch", "ChromaKB", "GitHubSearch",
    "ArxivSearch", "CommunitySearch", "OfficialSearch",
    "RETRIEVER_REGISTRY",
]
