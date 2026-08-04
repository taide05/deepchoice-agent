import httpx
from .base import BaseRetriever

# Mapping of known tech terms to their official documentation sites.
# Curated list — only entries with stable, well-known doc URLs.
TECH_DOCS: dict[str, dict[str, str]] = {
    "react": {"url": "https://react.dev", "title": "React — Official Documentation"},
    "vue": {"url": "https://vuejs.org", "title": "Vue.js — Official Documentation"},
    "angular": {"url": "https://angular.dev", "title": "Angular — Official Documentation"},
    "svelte": {"url": "https://svelte.dev", "title": "Svelte — Official Documentation"},
    "django": {"url": "https://docs.djangoproject.com", "title": "Django — Official Documentation"},
    "flask": {"url": "https://flask.palletsprojects.com", "title": "Flask — Official Documentation"},
    "fastapi": {"url": "https://fastapi.tiangolo.com", "title": "FastAPI — Official Documentation"},
    "sqlalchemy": {"url": "https://docs.sqlalchemy.org", "title": "SQLAlchemy — Official Documentation"},
    "postgresql": {"url": "https://www.postgresql.org/docs/", "title": "PostgreSQL — Official Documentation"},
    "mysql": {"url": "https://dev.mysql.com/doc/", "title": "MySQL — Official Documentation"},
    "redis": {"url": "https://redis.io/docs/", "title": "Redis — Official Documentation"},
    "mongodb": {"url": "https://www.mongodb.com/docs/", "title": "MongoDB — Official Documentation"},
    "docker": {"url": "https://docs.docker.com", "title": "Docker — Official Documentation"},
    "kubernetes": {"url": "https://kubernetes.io/docs/", "title": "Kubernetes — Official Documentation"},
    "nginx": {"url": "https://nginx.org/en/docs/", "title": "nginx — Official Documentation"},
    "pytorch": {"url": "https://pytorch.org/docs/", "title": "PyTorch — Official Documentation"},
    "tensorflow": {"url": "https://www.tensorflow.org/api_docs", "title": "TensorFlow — Official Documentation"},
    "langchain": {"url": "https://python.langchain.com/docs/", "title": "LangChain — Official Documentation"},
    "langgraph": {"url": "https://langchain-ai.github.io/langgraph/", "title": "LangGraph — Official Documentation"},
    "next.js": {"url": "https://nextjs.org/docs", "title": "Next.js — Official Documentation"},
    "nuxt": {"url": "https://nuxt.com/docs", "title": "Nuxt — Official Documentation"},
    "tailwind": {"url": "https://tailwindcss.com/docs", "title": "Tailwind CSS — Official Documentation"},
    "python": {"url": "https://docs.python.org/3/", "title": "Python — Official Documentation"},
    "go": {"url": "https://go.dev/doc/", "title": "Go — Official Documentation"},
    "rust": {"url": "https://doc.rust-lang.org/", "title": "Rust — Official Documentation"},
    "typescript": {"url": "https://www.typescriptlang.org/docs/", "title": "TypeScript — Official Documentation"},
}


class OfficialSearch(BaseRetriever):
    source = "official"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        keywords = (adapted_queries[0] if adapted_queries else query).lower().replace(" vs ", " ").split()
        results = []
        matched_techs = set()

        # Pass 1: check curated tech docs for known technologies
        for kw in keywords:
            kw_clean = kw.strip().rstrip(".").rstrip(",")
            if kw_clean in TECH_DOCS and kw_clean not in matched_techs:
                matched_techs.add(kw_clean)
                doc = TECH_DOCS[kw_clean]
                results.append({
                    "url": doc["url"],
                    "title": doc["title"],
                    "snippet": f"Official documentation site for {kw_clean}",
                    "date": "",
                })

        # Pass 2: PyPI search for packages (same as before)
        async with httpx.AsyncClient(timeout=15) as client:
            for kw in keywords[:3]:
                if len(kw) < 3:
                    continue
                resp = await client.get(f"https://pypi.org/pypi/{kw}/json")
                if resp.status_code != 200:
                    continue
                info = resp.json().get("info", {})
                results.append({
                    "url": info.get("package_url", f"https://pypi.org/project/{kw}/"),
                    "title": f"{kw} (PyPI)",
                    "snippet": f"Version: {info.get('version', 'N/A')}, Summary: {info.get('summary', '')}",
                    "date": "",
                })
        return results[:max_results]
