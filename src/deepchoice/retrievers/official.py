import asyncio
import os

from ..utils.candidate_identity import (
    constraint_discovery_terms,
    source_identity_verified,
    source_text_identity_match,
    source_url_identity_match,
)
from ..utils.llm import call_model, summarize_usage
from .base import BaseRetriever
from .learned_docs import (
    learn,
    load_learned,
)
from .official_fetch import (
    OfficialFetchBudget,
    budget_for_research,
    fetch_official_page,
)

# A discovered official link is not a body. These are cumulative bounds for one
# research run: page attempts and actual HTTP requests are counted separately.
# Redirects consume the HTTP-request count; a proxy/forward route is rejected
# rather than being allowed to bypass IP pinning. Route selection is
# configuration-only and makes no network probe.
OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN = int(
    os.environ.get("OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", "2"))
OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN = int(
    os.environ.get("OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", "6"))
OFFICIAL_FETCH_TOTAL_DEADLINE_S = float(
    os.environ.get("OFFICIAL_FETCH_TOTAL_DEADLINE_S", "15"))
OFFICIAL_FETCH_MAX_BYTES = int(os.environ.get("OFFICIAL_FETCH_MAX_BYTES", "200000"))
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
    "langgraph": {"url": "https://langchain-ai.github.io/langgraph/", "title": "LangGraph — Official Documentation"},
    "llamaindex": {"url": "https://docs.llamaindex.ai", "title": "LlamaIndex — Official Documentation"},
    "crewai": {"url": "https://docs.crewai.com", "title": "CrewAI — Official Documentation"},
    "autogen": {"url": "https://microsoft.github.io/autogen", "title": "AutoGen — Official Documentation"},
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

    async def _fetch_official_body(self, url: str) -> dict:
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
            key = max(named, key=lambda k: len(_normalize(k)))
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
                    if not source_text_identity_match(owner, title, snippet):
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

        # Candidate pages are always attempted before platform-constraint pages:
        # a page budget must not let a general platform document crowd out the
        # declared products being compared.
        results.sort(key=lambda entry: 0 if entry.get("source_kind") == "candidate" else 1)

        # Fetch bounded bodies only after candidates/URLs are de-duplicated, so a
        # failed or seeded link cannot trigger duplicate network work. Page
        # attempts and dispatched HTTP requests are separate cumulative bounds;
        # redirects consume the HTTP count. Every attempt remains visible on the
        # saved source row; an exhausted budget is navigation.
        budget = self._fetch_budget
        for entry in results:
            if not budget.begin_page():
                entry["body_error"] = "page_attempt_budget_exhausted"
                entry["fetch_status"] = "navigation"
                continue
            fetched = await self._fetch_official_body(entry["url"])
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
                continue
            body = fetched["body"]
            owner = entry.get("source_owner") or entry.get("title") or ""
            if not entry.get("_from_mapping"):
                # The fallback entry's title is generated by us, so only the
                # fetched body may establish identity. A prior-search title is
                # real search metadata and may be used alongside the body.
                identity_title = (entry.get("title", "")
                                  if entry.get("_from_prior_search") else "")
                if not source_identity_verified(owner, entry["url"],
                                                identity_title, body):
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
            # Learn only a verified identity whose body was actually collected,
            # and only when it came from discovery rather than the curated map.
            if not entry.get("_from_mapping") and entry.get("body_identity_verified"):
                learn(owner, entry["url"],
                      f"{owner} — Official Documentation", via="body_fetch")

        self._last_fetch_stats = budget.snapshot()
        return results[:max_results]
