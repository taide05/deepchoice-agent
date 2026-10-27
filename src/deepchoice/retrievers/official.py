import asyncio
import os
import re
from urllib.parse import urljoin, urlparse

from ..utils.candidate_identity import (
    constraint_discovery_terms,
    source_identity_verified,
    source_text_discusses_candidate,
    source_url_identity_match,
)
from ..utils.llm import call_model, summarize_usage
from .base import BaseRetriever
from .learned_docs import (
    learn,
    load_learned,
)
from .official_tech_docs_extra import EXTRA_TECH_DOCS
from .official_fetch import (
    OfficialFetchBudget,
    budget_for_research,
    fetch_official_page,
)

# Path hints used to pick one deeper documentation page from a navigation root.
# This runs only after an official page was fetched successfully but rejected as
# navigation; the derived page is fetched and identity-checked by the same rules,
# so a guessed path can never become evidence by itself.
_DOC_PATH_HINTS = (
    "/docs/", "/doc/", "/documentation/", "/reference/", "/api/", "/guide/",
    "/guides/", "/en/", "/stable/", "/latest/", "/manual/", "/tutorial",
)
_SKIP_LINK_HINTS = (
    "/login", "/signup", "/pricing", "/careers", "/jobs", "/search",
    "/download", "/contact", "/privacy", "/terms", "/blog/", "/news/",
    ".pdf", ".zip", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".css", ".js",
    ".xml", ".json",
)

# Index pages are link directories, not bodies: a derived index page would be
# rejected by the same navigation admission and waste a page attempt.
_INDEX_PATH_SUFFIXES = ("/index.html", "/index.htm", "/index", "/")


# Focused deep documentation pages fetched from a curated mapping root. A root
# overview page is enough to establish the candidate's identity, but decision-grade
# claims need the official page about the actual decision dimension (migration,
# rollback, security, performance, ...). Up to this many same-scope links are
# ranked by the question's dimensions and fetched within the existing page budget.
OFFICIAL_DEEP_DOC_PAGES_PER_CANDIDATE = 2

_FOCUS_TERM_GROUPS = {
    "migration": ("migration", "migrate", "upgrade", "迁移", "升级", "切换"),
    "rollback": ("rollback", "revert", "failover", "回滚", "回退", "恢复"),
    "deployment": ("deploy", "deployment", "production", "部署", "上线"),
    "persistence": ("persistence", "durable", "checkpoint", "持久", "检查点"),
    "interrupt": ("interrupt", "resume", "human-in-the-loop", "中断", "人工介入"),
    "security": ("security", "audit", "permission", "rbac", "acl", "安全", "审计", "权限"),
    "performance": ("performance", "benchmark", "latency", "throughput", "性能", "基准", "延迟"),
    "maintenance": ("maintenance", "release", "version", "support", "维护", "版本", "发布"),
}
_FOCUS_LINK_TERMS = {
    "migration": ("migration", "migrate", "upgrade", "changelog"),
    "rollback": ("rollback", "revert", "failover"),
    "deployment": ("deploy", "deployment", "production", "operations"),
    "persistence": ("persistence", "durable", "checkpoint", "state"),
    "interrupt": ("interrupt", "resume", "human-in-the-loop"),
    "security": ("security", "audit", "permission", "rbac", "acl", "authentication"),
    "performance": ("performance", "benchmark", "latency", "throughput"),
    "maintenance": ("maintenance", "release", "version", "support", "changelog"),
}


def _mapping_scope_root_path(mapping_root: str | None) -> str:
    """Directory scope of a curated mapping root (file mappings use their dir)."""
    path = urlparse(str(mapping_root or "")).path.rstrip("/")
    if path and "." in path.rsplit("/", 1)[-1]:
        path = path.rsplit("/", 1)[0]
    return path


def _url_in_mapping_scope(url: str, mapping_root: str | None) -> bool:
    if not mapping_root:
        return False
    root = urlparse(str(mapping_root))
    target = urlparse(str(url or ""))
    if (target.scheme not in ("http", "https")
            or target.netloc.lower() != root.netloc.lower()):
        return False
    root_path = _mapping_scope_root_path(mapping_root)
    target_path = target.path.rstrip("/")
    if not root_path:
        return True
    return target_path == root_path or target_path.startswith(root_path + "/")


def _deep_doc_focus_terms(*texts: str) -> tuple[str, ...]:
    """Link keywords for the decision dimensions this question actually names."""
    blob = " ".join(str(text or "") for text in texts).lower()
    terms: list[str] = []
    for group, markers in _FOCUS_TERM_GROUPS.items():
        if any(str(marker).lower() in blob for marker in markers):
            terms.extend(_FOCUS_LINK_TERMS[group])
    if not terms:
        # A general selection question still benefits from production/migration
        # documentation rather than only the marketing overview.
        terms = ["migration", "deployment", "production", "persistence",
                 "security", "performance"]
    return tuple(dict.fromkeys(terms))


def _links_in_text(text: str) -> list[str]:
    return [match.split("#", 1)[0] for match in re.findall(
        r"\[[^\]]*\]\((https?://[^)\s]+)\)", str(text or ""))]


def _deep_doc_links(base_url: str, body: str, links: list[str],
                    focus_terms: tuple[str, ...], mapping_root: str | None,
                    *, limit: int = 2) -> list[str]:
    """Rank same-scope documentation links by decision-dimension keywords."""
    base = urlparse(str(base_url or ""))
    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    candidates = list(links or []) + _links_in_text(body)
    for raw in candidates:
        target = urljoin(str(base_url), str(raw or ""))
        target = target.split("#", 1)[0].rstrip("/")
        if not target.startswith(("http://", "https://")):
            continue
        parsed = urlparse(target)
        if parsed.netloc.lower() != base.netloc.lower():
            continue
        if not _url_in_mapping_scope(target, mapping_root or base_url):
            continue
        if target in seen or target.rstrip("/") == str(base_url).rstrip("/"):
            continue
        lowered = target.lower()
        score = sum(1 for term in focus_terms if term in lowered)
        if score <= 0:
            continue
        seen.add(target)
        ranked.append((-score, len(ranked), target))
    ranked.sort()
    return [target for _score, _order, target in ranked[:limit]]


def _mapping_scope_identity(owner: str, url: str, title: str, body: str,
                            mapping_root: str | None) -> bool:
    """Body identity inside a hand-curated mapping root.

    A curated root is already an explicit statement that the site belongs to the
    candidate (e.g. ``microsoft.github.io/autogen/stable/`` for AutoGen, where the
    product name is in the path, not the host). A page fetched from under that
    exact host/path scope may therefore pass body identity even though the URL
    token check alone would reject a GitHub Pages host; the page body must still
    name the declared candidate. This is deliberately narrower than accepting
    any page on the host and never applies to learned or prior-search roots.
    """
    if not mapping_root:
        return False
    if not _url_in_mapping_scope(url, mapping_root):
        return False
    return source_text_discusses_candidate(owner, title, body)


def _fallback_doc_targets(base_url: str, *, limit: int = 3) -> list[str]:
    """Same-host static fallbacks for a curated root that only served a JS shell.

    Only same-host entry points are tried: the existing safe-fetch and body identity
    rules reject off-host README mirrors as official evidence. For a docs root with
    a path (e.g. a GitHub Pages project site), common static documentation paths are
    tried first, then llms.txt; the caller still admits only a page whose body names
    the declared candidate (see the curated-mapping-scope identity check).
    """
    from urllib.parse import urlparse

    parsed = urlparse(str(base_url or ""))
    scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
    host = parsed.netloc.lower()
    if not host:
        return []
    path = parsed.path.rstrip("/")
    root = f"{scheme}://{host}{path}" if path else f"{scheme}://{host}"
    targets = [f"{root}/stable/", f"{root}/latest/",
               f"{scheme}://{host}/llms.txt",
               f"{scheme}://{host}/llms-full.txt"]
    targets += [f"{root}/docs/", f"{root}/en/latest/"]
    if path:
        targets.append(f"{root}/llms.txt")
    return targets[:limit]


def _derived_doc_links(base_url: str, links: list[str], *, limit: int = 2) -> list[str]:
    """Deeper same-site documentation links from a navigation page.

    A documentation root is often a link directory; the prose lives one hop
    deeper. This only ranks already-fetched links (same host, documentation-like
    path, no asset/login links); the caller spends a bounded page attempt on one
    of them, and the derived page must still pass body admission and identity
    verification before it can be cited.
    """
    from urllib.parse import urlparse

    host = urlparse(base_url).netloc.lower()
    ranked: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()
    for href in links or []:
        try:
            parsed = urlparse(str(href))
        except ValueError:
            continue
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != host:
            continue
        path = parsed.path.lower()
        if not path or path in ("/", "/index.html"):
            continue
        if path.endswith(_INDEX_PATH_SUFFIXES):
            continue
        if any(skip in path for skip in _SKIP_LINK_HINTS):
            continue
        hint_score = sum(1 for hint in _DOC_PATH_HINTS if hint in path)
        depth = path.count("/")
        if hint_score == 0 and depth < 2:
            continue
        clean = href.split("#", 1)[0].rstrip("/")
        if not clean or clean == base_url.rstrip("/") or clean in seen:
            continue
        seen.add(clean)
        # Deeper and documentation-like first; shorter path breaks ties.
        ranked.append((-hint_score, -depth, len(path), clean))
    ranked.sort()
    return [item[-1] for item in ranked[:limit]]

# A discovered official link is not a body. These are cumulative bounds for one
# research run: page attempts and actual HTTP requests are counted separately.
# Redirects consume the HTTP-request count; a proxy/forward route is rejected
# rather than being allowed to bypass IP pinning. Route selection is
# configuration-only and makes no network probe.
#
# Defaults restored to the caps the frozen paired diagnostics used (4 page
# attempts / 12 HTTP requests / 1 MiB retained): the earlier 2/6/200 KB values
# exhausted the page budget on the first candidate and truncated documentation
# pages mid-body. Each attempt remains bounded by the per-page deadline, size and
# redirect limits; the four attempts cover two candidates with one discovered page
# and one curated root each.
OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN = int(
    os.environ.get("OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", "4"))
OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN = int(
    os.environ.get("OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", "12"))
OFFICIAL_FETCH_TOTAL_DEADLINE_S = float(
    os.environ.get("OFFICIAL_FETCH_TOTAL_DEADLINE_S", "15"))
OFFICIAL_FETCH_MAX_BYTES = int(os.environ.get("OFFICIAL_FETCH_MAX_BYTES", "1048576"))
OFFICIAL_FETCH_MAX_REDIRECTS = 3
OFFICIAL_BODY_STORE_CHARS = int(os.environ.get("OFFICIAL_BODY_STORE_CHARS", "8000"))

# Mapping of known tech terms to their official documentation sites.
# Curated list — only entries with stable, well-known doc URLs.
# Self-updates at runtime: learned pairs (harvest + LLM fallback) persist
# to learned_docs.json and are consulted before this seed dict.

_LLM_FALLBACK_MAX = 4

_VS_MARKERS = (" vs ", " versus ", " 对比 ", " 比较 ")


def _is_vs_query(query: str) -> bool:
    return any(m in query.lower() for m in _VS_MARKERS)


def _normalize(s: str) -> str:
    """Lowercase, alphanumerics only — 'AWS Lambda' and 'aws-lambda' both normalize to 'awslambda'."""
    return "".join(c for c in s.lower() if c.isalnum())


# Bare-token aliases mapping to a curated TECH_DOCS key. Applied via normalized
# lookup so "postgres" resolves to "postgresql" without an LLM fallback. Only
# unambiguous shorthands are listed — ambiguous tokens are left to the LLM.
_TECH_ALIASES = {
    "next": "next.js",
    "transformers": "huggingface",
    "postgres": "postgresql",
    "k8s": "kubernetes",
    "golang": "go",
}
TECH_DOCS: dict[str, dict[str, str]] = {
    # Web frameworks
    "react": {"url": "https://react.dev", "title": "React — Official Documentation"},
    "vue": {"url": "https://vuejs.org", "title": "Vue.js — Official Documentation"},
    "angular": {"url": "https://angular.dev", "title": "Angular — Official Documentation"},
    "svelte": {"url": "https://svelte.dev", "title": "Svelte — Official Documentation"},
    "django": {"url": "https://docs.djangoproject.com", "title": "Django — Official Documentation"},
    "flask": {"url": "https://flask.palletsprojects.com", "title": "Flask — Official Documentation"},
    "fastapi": {"url": "https://fastapi.tiangolo.com", "title": "FastAPI — Official Documentation"},
    "django-ninja": {"url": "https://django-ninja.dev", "title": "Django Ninja — Official Documentation"},
    "bun": {"url": "https://bun.sh", "title": "Bun — Official Documentation"},
    "node.js": {"url": "https://nodejs.org", "title": "Node.js — Official Documentation"},
    "nodejs": {"url": "https://nodejs.org", "title": "Node.js — Official Documentation"},
    # Databases
    "postgresql": {"url": "https://www.postgresql.org/docs/", "title": "PostgreSQL — Official Documentation"},
    "mysql": {"url": "https://dev.mysql.com/doc/", "title": "MySQL — Official Documentation"},
    "redis": {"url": "https://redis.io/docs/", "title": "Redis — Official Documentation"},
    "mongodb": {"url": "https://www.mongodb.com/docs/", "title": "MongoDB — Official Documentation"},
    "sqlite": {"url": "https://sqlite.org", "title": "SQLite — Official Documentation"},
    "neo4j": {"url": "https://neo4j.com", "title": "Neo4j — Official Documentation"},
    "memcached": {"url": "https://memcached.org", "title": "Memcached — Official Documentation"},
    # ORM / DB tools
    "sqlalchemy": {"url": "https://docs.sqlalchemy.org", "title": "SQLAlchemy — Official Documentation"},
    "alembic": {"url": "https://alembic.sqlalchemy.org", "title": "Alembic — Official Documentation"},
    # Container / orchestration / CI/CD
    "docker": {"url": "https://docs.docker.com", "title": "Docker — Official Documentation"},
    "kubernetes": {"url": "https://kubernetes.io/docs/", "title": "Kubernetes — Official Documentation"},
    "docker-compose": {"url": "https://docs.docker.com/compose", "title": "Docker Compose — Official Documentation"},
    "minikube": {"url": "https://minikube.sigs.k8s.io", "title": "Minikube — Official Documentation"},
    "github-actions": {"url": "https://docs.github.com/en/actions", "title": "GitHub Actions — Official Documentation"},
    "jenkins": {"url": "https://jenkins.io", "title": "Jenkins — Official Documentation"},
    "gitlab-ci": {"url": "https://docs.gitlab.com/ee/ci", "title": "GitLab CI — Official Documentation"},
    # Web server / proxy / comms
    "nginx": {"url": "https://nginx.org/en/docs/", "title": "nginx — Official Documentation"},
    "caddy": {"url": "https://caddyserver.com", "title": "Caddy — Official Documentation"},
    "grpc": {"url": "https://grpc.io", "title": "gRPC — Official Documentation"},
    "websocket": {"url": "https://developer.mozilla.org", "title": "WebSocket API — MDN Documentation"},
    "uvicorn": {"url": "https://uvicorn.org", "title": "Uvicorn — Official Documentation"},
    "gunicorn": {"url": "https://docs.gunicorn.org", "title": "Gunicorn — Official Documentation"},
    # ML / AI frameworks
    "pytorch": {"url": "https://pytorch.org/docs/", "title": "PyTorch — Official Documentation"},
    "tensorflow": {"url": "https://www.tensorflow.org/api_docs", "title": "TensorFlow — Official Documentation"},
    "huggingface": {"url": "https://huggingface.co/docs/transformers", "title": "HuggingFace Transformers — Official Documentation"},
    "sentence-transformers": {"url": "https://sbert.net", "title": "Sentence-Transformers — Official Documentation"},
    "ollama": {"url": "https://ollama.com", "title": "Ollama — Official Documentation"},
    "vllm": {"url": "https://docs.vllm.ai", "title": "vLLM — Official Documentation"},
    "ray": {"url": "https://docs.ray.io", "title": "Ray — Official Documentation"},
    "dask": {"url": "https://dask.org", "title": "Dask — Official Documentation"},
    "tiktoken": {"url": "https://github.com/openai/tiktoken", "title": "tiktoken — Official Repository"},
    "sentencepiece": {"url": "https://github.com/google/sentencepiece", "title": "SentencePiece — Official Repository"},
    # Agent frameworks
    "langchain": {"url": "https://python.langchain.com/docs/", "title": "LangChain — Official Documentation"},
    "langgraph": {"url": "https://docs.langchain.com/oss/python/langgraph/overview.md", "title": "LangGraph — Official Documentation"},
    "llamaindex": {"url": "https://docs.llamaindex.ai", "title": "LlamaIndex — Official Documentation"},
    "crewai": {"url": "https://docs.crewai.com", "title": "CrewAI — Official Documentation"},
    "autogen": {"url": "https://microsoft.github.io/autogen/stable/", "title": "AutoGen — Official Documentation"},
    "semantic-kernel": {"url": "https://learn.microsoft.com/semantic-kernel", "title": "Semantic Kernel — Official Documentation"},
    "dify": {"url": "https://dify.ai", "title": "Dify — Official Documentation"},
    "langflow": {"url": "https://docs.langflow.org", "title": "LangFlow — Official Documentation"},
    "mcp": {"url": "https://modelcontextprotocol.io", "title": "MCP — Official Documentation"},
    # Vector DBs
    "chroma": {"url": "https://docs.trychroma.com", "title": "Chroma — Official Documentation"},
    "chromadb": {"url": "https://docs.trychroma.com", "title": "ChromaDB — Official Documentation"},
    "pinecone": {"url": "https://pinecone.io", "title": "Pinecone — Official Documentation"},
    "weaviate": {"url": "https://weaviate.io", "title": "Weaviate — Official Documentation"},
    "qdrant": {"url": "https://qdrant.tech", "title": "Qdrant — Official Documentation"},
    "milvus": {"url": "https://milvus.io", "title": "Milvus — Official Documentation"},
    "faiss": {"url": "https://github.com/facebookresearch/faiss", "title": "FAISS — Official Repository"},
    "elasticsearch": {"url": "https://elastic.co", "title": "Elasticsearch — Official Documentation"},
    "meilisearch": {"url": "https://meilisearch.com", "title": "Meilisearch — Official Documentation"},
    # Infra / messaging / config
    "kafka": {"url": "https://kafka.apache.org", "title": "Apache Kafka — Official Documentation"},
    "rabbitmq": {"url": "https://rabbitmq.com", "title": "RabbitMQ — Official Documentation"},
    "celery": {"url": "https://docs.celeryq.dev", "title": "Celery — Official Documentation"},
    "terraform": {"url": "https://terraform.io", "title": "Terraform — Official Documentation"},
    "pulumi": {"url": "https://pulumi.com", "title": "Pulumi — Official Documentation"},
    "ansible": {"url": "https://docs.ansible.com", "title": "Ansible — Official Documentation"},
    "airflow": {"url": "https://airflow.apache.org", "title": "Apache Airflow — Official Documentation"},
    "prefect": {"url": "https://prefect.io", "title": "Prefect — Official Documentation"},
    "prometheus": {"url": "https://prometheus.io", "title": "Prometheus — Official Documentation"},
    "datadog": {"url": "https://datadoghq.com", "title": "Datadog — Official Documentation"},
    "pydantic": {"url": "https://docs.pydantic.dev", "title": "Pydantic — Official Documentation"},
    "pydantic-settings": {"url": "https://docs.pydantic.dev", "title": "Pydantic Settings — Official Documentation"},
    "python-dotenv": {"url": "https://github.com/theskumar/python-dotenv", "title": "python-dotenv — Official Repository"},
    # Frontend / tools
    "streamlit": {"url": "https://streamlit.io", "title": "Streamlit — Official Documentation"},
    "gradio": {"url": "https://gradio.app", "title": "Gradio — Official Documentation"},
    "playwright": {"url": "https://playwright.dev", "title": "Playwright — Official Documentation"},
    "selenium": {"url": "https://selenium.dev", "title": "Selenium — Official Documentation"},
    "next.js": {"url": "https://nextjs.org/docs", "title": "Next.js — Official Documentation"},
    "nuxt": {"url": "https://nuxt.com/docs", "title": "Nuxt — Official Documentation"},
    "tailwind": {"url": "https://tailwindcss.com/docs", "title": "Tailwind CSS — Official Documentation"},
    # Languages
    "python": {"url": "https://docs.python.org/3/", "title": "Python — Official Documentation"},
    "go": {"url": "https://go.dev/doc/", "title": "Go — Official Documentation"},
    "rust": {"url": "https://doc.rust-lang.org/", "title": "Rust — Official Documentation"},
    "typescript": {"url": "https://www.typescriptlang.org/docs/", "title": "TypeScript — Official Documentation"},
    # Cloud / serverless
    "aws-lambda": {"url": "https://aws.amazon.com/lambda", "title": "AWS Lambda — Official Documentation"},
    "modal": {"url": "https://modal.com", "title": "Modal — Official Documentation"},
    # Auth
    "jwt": {"url": "https://jwt.io", "title": "JWT — Official Documentation"},
    # LLM APIs
    "openai": {"url": "https://platform.openai.com", "title": "OpenAI API — Official Documentation"},
    "anthropic": {"url": "https://docs.anthropic.com", "title": "Anthropic Claude API — Official Documentation"},
    # Version control / Git
    "gitlab": {"url": "https://about.gitlab.com", "title": "GitLab — Official Documentation"},
}

# Additional curated roots for the 2026-10 formal case technology set. These are
# discovery candidates only: the safe fetch, prose admission and body identity
# check still decide whether a URL becomes evidence.
TECH_DOCS.update(EXTRA_TECH_DOCS)


class OfficialSearch(BaseRetriever):
    source = "official"

    def __init__(self, *args, **kwargs):
        super().__init__()
        self._fetch_budget = None
        self._last_fetch_stats: dict = {}
        self._fallback_usage: list[dict] = []
        self._discovery_context: dict = {}

    async def search(self, query: str, sub_questions: list[str],
                     max_results: int = 7,
                     adapted_queries: list[str] | None = None,
                     candidate_techs: list[str] | None = None,
                     constraints: list[str] | None = None,
                     prior_results: list[dict] | None = None) -> dict:
        # The official source runs after the ordinary retrievers and may reuse
        # their already-paid result rows for source discovery. It never issues a
        # second search. The context is not a second source of truth; the safe
        # fetch below still verifies the page identity.
        self._discovery_context = {
            "constraints": list(constraints or []),
            "prior_results": list(prior_results or []),
        }
        result = await super().search(
            query, sub_questions, max_results,
            adapted_queries=adapted_queries, candidate_techs=candidate_techs)
        # Keep the base envelope; add the cumulative count record for this run's
        # official source. Source result rows and dispatched HTTP requests are
        # different counters and both remain explicit.
        result["fetch_stats"] = dict(self._last_fetch_stats)
        if self._fallback_usage:
            result["token_usage"] = [
                summarize_usage("official_fallback", self._fallback_usage)]
        return result

    async def _propose_official_url(self, term: str,
                                    usage: list | None = None) -> str | None:
        """LLM fallback: propose an official docs URL for an unmapped term."""
        result = await call_model(
            [
                {
                    "role": "system",
                    "content": (
                        "You map technology terms to their official documentation URLs. "
                        'Reply with JSON {"url": "https://..."} or {"url": null} if unsure. '
                        "Only well-known official sites — never guess or invent."
                    ),
                },
                {"role": "user", "content": f"Official documentation URL for: {term}"},
            ],
            model="deepseek-flash", tag="official_fallback",
            response_format="json", usage=usage,
        )
        if isinstance(result, dict):
            return result.get("url")
        return None

    async def _fetch_official_body(self, url: str, *,
                                   allow_navigation_intro: bool = False) -> dict:
        budget = self._fetch_budget
        if budget is None:
            budget = OfficialFetchBudget(
                max_page_attempts=OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN,
                max_http_requests=OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN,
            )
            self._fetch_budget = budget
        if budget.http_requests >= budget.max_http_requests:
            budget.record_failure("http_budget_exhausted")
            return {"ok": False, "url": url, "failure": "http_budget_exhausted",
                    "budget": budget.snapshot()}
        try:
            return await fetch_official_page(
                url, budget=budget,
                deadline_s=OFFICIAL_FETCH_TOTAL_DEADLINE_S,
                max_response_bytes=OFFICIAL_FETCH_MAX_BYTES,
                max_redirects=OFFICIAL_FETCH_MAX_REDIRECTS,
                store_chars=OFFICIAL_BODY_STORE_CHARS,
                allow_navigation_intro=allow_navigation_intro,
            )
        except Exception as exc:
            budget.record_failure(type(exc).__name__)
            return {"ok": False, "url": url,
                    "failure": type(exc).__name__, "budget": budget.snapshot()}

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None,
                         candidate_techs: list[str] | None = None) -> list[dict]:
        # Only declared candidates may introduce an official source. The adapted
        # queries are search aids: an ordinary word in them is not a research
        # target, and a learned-cache hit is not proof of candidacy either.
        from ..utils.candidate_identity import candidate_names_key, normalize_term

        candidates = [c for c in (candidate_techs or []) if str(c).strip()]
        self._fallback_usage = []
        learned = load_learned()
        # Curated seed always wins: a learned entry must never shadow a
        # hand-verified mapping (e.g. a harvested 'python' entry once
        # overrode docs.python.org with python.langchain.com).
        lookup = {**learned, **TECH_DOCS}
        results = []
        if self._fetch_budget is None:
            try:
                self._fetch_budget = budget_for_research(
                    max_page_attempts=OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN,
                    max_http_requests=OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN,
                )
            except LookupError:
                # No durable research identity (tests/direct callers): keep the
                # budget on this retriever instance rather than inventing one.
                self._fetch_budget = OfficialFetchBudget(
                    max_page_attempts=OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN,
                    max_http_requests=OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN,
                )
        self._last_fetch_stats = self._fetch_budget.snapshot()

        if not candidates:
            # No declared identity, so nothing may be promoted to "official".
            # Better an explicit gap than an unowned official-looking source.
            return []

        context = getattr(self, "_discovery_context", {}) or {}
        constraint_terms = constraint_discovery_terms(
            context.get("constraints") or [], candidates, lookup)
        targets: list[tuple[str, str]] = [(c, "candidate") for c in candidates]
        seen_targets = {c.strip().lower() for c in candidates}
        for term in constraint_terms:
            if term.strip().lower() in seen_targets:
                continue
            seen_targets.add(term.strip().lower())
            targets.append((term, "platform_constraint"))

        # Mapping entries that a declared target actually names. Longest match
        # wins, so a candidate naming both 'postgresql' and a more specific key
        # resolves to the more specific one. The mapping is the only source list
        # that carries hand-verified ownership; it is not inferred from a
        # lookalike domain.
        for owner, kind in targets:
            named = [k for k in lookup if candidate_names_key(owner, k)]
            if not named:
                continue
            # A hand-verified mapping outranks a learned cache entry even when the
            # learned key is a different casing/alias; stale learned URLs (e.g. a
            # formerly-working langgraph.dev path) must not shadow the curated
            # canonical docs root. Longest match still wins within each tier.
            named.sort(key=lambda k: (0 if k in TECH_DOCS else 1,
                                      -len(_normalize(k))))
            key = named[0]
            if key not in lookup:
                continue
            curated = key in TECH_DOCS
            if not curated:
                # A learned cache entry is a hint, not ownership proof. It may
                # resolve only the same full identity (e.g. learned "gVisor" for
                # gVisor), never a one-token fragment like "amazon" for a
                # multi-word target. Its page body is verified before admission.
                if normalize_term(key) != normalize_term(owner):
                    continue
            doc = lookup[key]
            entry = {
                "url": doc["url"],
                "title": doc["title"],
                "snippet": "",
                "has_body": False,
                "date": "",
                "_from_mapping": curated,
                "_from_learned": not curated,
                "_from_prior_search": False,
                "_mapping_root": doc["url"] if curated else None,
                "source_owner": owner,
                "source_kind": kind,
            }
            if entry["url"] not in {r["url"] for r in results}:
                results.append(entry)

        # Reuse already-paid ordinary-search rows. A row becomes an official
        # target only when its URL and visible snippet both name the declared
        # product/constraint; the safe-fetched page must confirm the same identity
        # before the body is admitted. No new search is issued for this.
        for owner, kind in targets:
            for channel in context.get("prior_results") or []:
                for item in channel.get("results") or []:
                    url = str(item.get("url") or "")
                    title = str(item.get("title") or "")
                    snippet = str(item.get("snippet") or item.get("content") or "")
                    if not url.startswith(("http://", "https://")):
                        continue
                    if not source_url_identity_match(owner, url):
                        continue
                    if not source_text_discusses_candidate(owner, title, snippet):
                        continue
                    if url in {r["url"] for r in results}:
                        continue
                    results.append({
                        "url": url,
                        "title": title or f"{owner} — discovered documentation",
                        "snippet": "",
                        "has_body": False,
                        "date": str(item.get("date") or ""),
                        "_from_mapping": False,
                        "_from_prior_search": True,
                        "source_owner": owner,
                        "source_kind": kind,
                    })
                    break
                if any(r.get("source_owner") == owner for r in results):
                    break

        # LLM fallback stays available for declared candidates and explicit
        # platform constraints that neither the mapping nor an existing search
        # row resolved. The URL must still pass the bounded identity gate, and
        # the fetched body must name the same owner.
        resolved_owners = {r.get("source_owner") for r in results}
        unresolved = [(owner, kind) for owner, kind in targets
                      if owner not in resolved_owners]

        async def _resolve_fallback(owner):
            url = await self._propose_official_url(
                owner, usage=self._fallback_usage)
            if not url or not source_url_identity_match(owner, url):
                return None
            return owner, url

        pending = unresolved[:_LLM_FALLBACK_MAX]
        resolved = await asyncio.gather(
            *[_resolve_fallback(owner) for owner, _kind in pending],
            return_exceptions=True)
        kind_by_owner = dict(targets)
        for item in resolved:
            if isinstance(item, Exception) or item is None:
                # One fallback failure is a source gap, not a reason to discard
                # successful candidate/platform rows from other targets.
                continue
            owner, url = item
            entry = {
                "url": url,
                "title": f"{owner} — Official Documentation",
                "snippet": "",
                "has_body": False,
                "date": "",
                "_from_mapping": False,
                "_from_prior_search": False,
                "source_owner": owner,
                "source_kind": kind_by_owner.get(owner, "candidate"),
            }
            if entry["url"] not in {r["url"] for r in results}:
                results.append(entry)

        # Candidate pages are attempted before platform-constraint pages. Within
        # each group, an actual retrieved document outranks a curated root and a
        # model-proposed URL: the search result is a discovered page, the model
        # proposal is not.
        def _priority(entry: dict) -> tuple[int, int, str]:
            kind_rank = 0 if entry.get("source_kind") == "candidate" else 1
            if entry.get("_from_prior_search"):
                origin_rank = 0
            elif entry.get("_from_mapping"):
                origin_rank = 1
            else:
                origin_rank = 2
            return kind_rank, origin_rank, entry.get("url", "")

        results.sort(key=_priority)

        # Fetch bounded bodies only after candidates/URLs are de-duplicated, so a
        # failed or seeded link cannot trigger duplicate network work. Page
        # attempts and dispatched HTTP requests are separate cumulative bounds;
        # redirects consume the HTTP count. Every attempt remains visible on the
        # saved source row; an exhausted budget is navigation.
        budget = self._fetch_budget
        found_candidate_owners = {r.get("source_owner") for r in results
                                  if r.get("source_kind") == "candidate"}
        missing_candidate_coverage = [
            candidate for candidate in candidates
            if candidate not in found_candidate_owners
        ]
        known_urls = {r.get("url") for r in results}
        derived_added = 0
        derived_owners: set[str] = set()
        fallback_added = 0
        fallback_owners: set[str] = set()
        for entry in results:
            if missing_candidate_coverage and entry.get("source_kind") != "candidate":
                # Do not spend the remaining page budget on a platform homepage
                # when a declared candidate still has no discovered source.
                entry["body_error"] = "candidate_coverage_incomplete"
                entry["fetch_status"] = "navigation"
                continue
            if not budget.begin_page():
                entry["body_error"] = "page_attempt_budget_exhausted"
                entry["fetch_status"] = "navigation"
                continue
            fetched = await self._fetch_official_body(
                entry["url"],
                allow_navigation_intro=bool(entry.get("_from_mapping")),
            )
            if not fetched.get("ok"):
                entry["has_body"] = False
                entry["snippet"] = ""
                entry["body_identity_verified"] = False
                entry["body_error"] = str(
                    fetched.get("failure") or fetched.get("error") or "fetch_failed")
                entry["fetch_status"] = "navigation"
                if fetched.get("page_chars") is not None:
                    entry["body_page_chars"] = fetched.get("page_chars")
                if fetched.get("prose_chars") is not None:
                    entry["body_prose_chars"] = fetched.get("prose_chars")
                for key in ("bytes_read", "bytes_retained",
                            "declared_content_length", "content_length_exceeded",
                            "page_truncated", "truncation_reason"):
                    if key in fetched:
                        entry[key] = fetched.get(key)
                # A successful fetch rejected as a navigation page may still link
                # to the prose documentation one hop deeper. Spend a bounded extra
                # attempt on it, never on a page derived from a derived page.
                body_error = str(entry.get("body_error") or "")
                owner = entry.get("source_owner") or ""
                if (owner and not entry.get("_from_derived")
                        and owner not in derived_owners
                        and ("navigation_like" in body_error
                             or "short_prose_only" in body_error)
                        and budget.page_attempts < budget.max_page_attempts
                        and derived_added < 2):
                    for target in _derived_doc_links(entry["url"],
                                                     fetched.get("links") or []):
                        if target in known_urls or derived_added >= 2:
                            continue
                        known_urls.add(target)
                        derived_added += 1
                        derived_owners.add(owner)
                        results.append({
                            "url": target,
                            "title": f"{owner} — documentation",
                            "snippet": "",
                            "has_body": False,
                            "date": "",
                            "_from_mapping": False,
                            "_from_prior_search": False,
                            "_from_derived": True,
                            "_mapping_root": entry.get("_mapping_root"),
                            "source_owner": owner,
                            "source_kind": entry.get("source_kind"),
                        })
                # A curated root that served only a JS shell/navigation page may
                # also expose static documentation under common paths, or llms.txt.
                # Try one static fallback only when the normal derived-page route
                # found nothing for this owner and the page budget still allows it.
                if (owner and entry.get("_from_mapping")
                        and owner not in derived_owners
                        and owner not in fallback_owners
                        and budget.page_attempts < budget.max_page_attempts
                        and fallback_added < 2):
                    for target in _fallback_doc_targets(entry["url"]):
                        if target in known_urls or fallback_added >= 2:
                            continue
                        known_urls.add(target)
                        fallback_added += 1
                        fallback_owners.add(owner)
                        results.append({
                            "url": target,
                            "title": f"{owner} — static documentation fallback",
                            "snippet": "",
                            "has_body": False,
                            "date": "",
                            "_from_mapping": False,
                            "_from_prior_search": False,
                            "_from_derived": True,
                            "_from_fallback": True,
                            "_mapping_root": entry.get("_mapping_root"),
                            "source_owner": owner,
                            "source_kind": entry.get("source_kind"),
                        })
                continue
            body = fetched["body"]
            owner = entry.get("source_owner") or entry.get("title") or ""
            if not entry.get("_from_mapping"):
                # Search metadata and our generated title are discovery hints, not
                # page identity. Only the safe-fetched body may establish that the
                # page names the owner. A page derived from a hand-curated mapping
                # root may still be official when it stays on the same host/path
                # scope and its body names the product (GitHub Pages project sites
                # put the product name in the path, not the host).
                verified = source_identity_verified(
                    owner, entry["url"], str(fetched.get("title") or ""), body)
                if not verified:
                    verified = _mapping_scope_identity(
                        owner, entry["url"], str(fetched.get("title") or ""), body,
                        entry.get("_mapping_root"))
                if not verified:
                    # A safe-fetched page that does not name the declared
                    # product/constraint is not that product's evidence. Keep the
                    # attempt visible as navigation, never as a citable body.
                    entry["has_body"] = False
                    entry["snippet"] = ""
                    entry["body_identity_verified"] = False
                    entry["fetch_status"] = "navigation"
                    entry["body_url"] = fetched.get("body_url") or entry["url"]
                    entry["body_error"] = "source_identity_unverified"
                    continue
            entry["snippet"] = body
            entry["has_body"] = True
            entry["body_identity_verified"] = True
            entry["fetch_status"] = "body"
            entry["body_url"] = fetched.get("body_url") or entry["url"]
            entry["body_page_chars"] = fetched.get("page_chars", fetched.get(
                "source_chars", len(body)))
            entry["body_chars"] = entry["body_page_chars"]
            entry["body_stored_chars"] = fetched.get(
                "stored_chars", len(body))
            entry["body_page_truncated"] = bool(fetched.get("page_truncated"))
            entry["body_stored_truncated"] = bool(fetched.get(
                "stored_truncated", len(entry["snippet"]) < entry["body_stored_chars"]))
            entry["body_truncated"] = bool(
                fetched.get("truncated")
                or entry["body_page_truncated"]
                or entry["body_stored_truncated"])
            entry["body_prose_chars"] = fetched.get("prose_chars", len(entry["snippet"]))
            entry["body_admission"] = fetched.get("admission", "prose_ok")
            entry["body_content_type"] = fetched.get("content_type", "")
            # A curated root is the candidate's identity anchor, but its overview
            # often does not answer migration/rollback/security/performance. Rank
            # same-scope documentation links by the question's dimensions and spend
            # a bounded number of extra page attempts on them. They still need the
            # body identity check below; the mapping scope only replaces the URL-token
            # check for a hand-verified root.
            if (entry.get("_from_mapping") and not entry.get("_from_derived")
                    and budget.page_attempts < budget.max_page_attempts):
                constraints = list((getattr(self, "_discovery_context", {}) or {})
                                   .get("constraints") or [])
                focus = _deep_doc_focus_terms(
                    query, " ".join(str(item) for item in sub_questions or []),
                    " ".join(str(item) for item in constraints))
                for target in _deep_doc_links(
                        entry["url"], body, fetched.get("links") or [], focus,
                        entry.get("_mapping_root") or entry["url"],
                        limit=OFFICIAL_DEEP_DOC_PAGES_PER_CANDIDATE):
                    if target in known_urls:
                        continue
                    if budget.page_attempts >= budget.max_page_attempts:
                        break
                    known_urls.add(target)
                    results.append({
                        "url": target,
                        "title": f"{owner} — deep documentation",
                        "snippet": "",
                        "has_body": False,
                        "date": "",
                        "_from_mapping": False,
                        "_from_prior_search": False,
                        "_from_derived": True,
                        "_deep_doc": True,
                        "_mapping_root": entry.get("_mapping_root") or entry["url"],
                        "source_owner": owner,
                        "source_kind": entry.get("source_kind"),
                    })
            # Learn only a verified identity whose body was actually collected,
            # and only when it came from discovery rather than the curated map.
            if not entry.get("_from_mapping") and entry.get("body_identity_verified"):
                learn(owner, entry["url"],
                      f"{owner} — Official Documentation", via="body_fetch")

        self._last_fetch_stats = budget.snapshot()
        return results[:max_results]
