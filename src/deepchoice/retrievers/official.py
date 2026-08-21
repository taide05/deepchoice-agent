import httpx
from .base import BaseRetriever
from .learned_docs import load_learned, learn, domain_label_match, is_plausible_term
from ..utils.llm import call_model

# Mapping of known tech terms to their official documentation sites.
# Curated list — only entries with stable, well-known doc URLs.
# Self-updates at runtime: learned pairs (harvest + LLM fallback) persist
# to learned_docs.json and are consulted before this seed dict.

_LLM_FALLBACK_MAX = 3

_VS_MARKERS = (" vs ", " versus ", " 对比 ", " 比较 ")


def _is_vs_query(query: str) -> bool:
    return any(m in query.lower() for m in _VS_MARKERS)


def _normalize(s: str) -> str:
    """Lowercase, alphanumerics only — 'AWS Lambda' and 'aws-lambda' both normalize to 'awslambda'."""
    return "".join(c for c in s.lower() if c.isalnum())
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

    async def _propose_official_url(self, term: str) -> str | None:
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
            model="deepseek-v4-flash",
            response_format="json",
        )
        if isinstance(result, dict):
            return result.get("url")
        return None

    async def _verify_reachable(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(url)
            return resp.status_code == 200 and "text/html" in resp.headers.get("content-type", "")
        except Exception:
            return False

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        all_text = " ".join(adapted_queries) if adapted_queries else query
        keywords = all_text.lower().replace(" vs ", " ").replace(" versus ", " ").split()
        learned = load_learned()
        # Curated seed always wins: a learned entry must never shadow a
        # hand-verified mapping (e.g. a harvested 'python' entry once
        # overrode docs.python.org with python.langchain.com).
        lookup = {**learned, **TECH_DOCS}
        results = []

        # Pass 1: curated seed + learned cache via normalized n-gram matching.
        # Space-separated multi-word terms ('AWS Lambda') match hyphenated or
        # dotted keys ('aws-lambda', 'next.js') through alnum normalization.
        norm_lookup = {_normalize(k): k for k in lookup}
        matched_norms: set[str] = set()
        matched_ngram_components: set[str] = set()
        for n in (1, 2, 3):
            for i in range(len(keywords) - n + 1):
                phrase = " ".join(keywords[i:i + n])
                norm = _normalize(phrase)
                key = norm_lookup.get(norm)
                if key is None or norm in matched_norms:
                    continue
                matched_norms.add(norm)
                matched_ngram_components.update(_normalize(kw) for kw in keywords[i:i + n])
                doc = lookup[key]
                results.append({
                    "url": doc["url"],
                    "title": doc["title"],
                    "snippet": f"Official documentation site for {key}",
                    "date": "",
                })

        # Pass 1.5: LLM fallback for unmapped candidate terms (validated + learned)
        unmapped = []
        for kw in keywords:
            kw_clean = kw.strip().rstrip(".").rstrip(",")
            if (kw_clean not in lookup and kw_clean not in unmapped
                    and is_plausible_term(kw_clean)
                    and _normalize(kw_clean) not in matched_ngram_components):
                unmapped.append(kw_clean)
        for kw in unmapped[:_LLM_FALLBACK_MAX]:
            url = await self._propose_official_url(kw)
            if not url or not domain_label_match(kw, url):
                continue
            if not await self._verify_reachable(url):
                continue
            learn(kw, url, f"{kw} — Official Documentation", via="llm")
            lookup[kw] = {"url": url, "title": f"{kw} — Official Documentation"}
            results.append({
                "url": url,
                "title": f"{kw} — Official Documentation",
                "snippet": f"Official documentation site for {kw}",
                "date": "",
            })

        # Pass 2: PyPI search for packages. Restricted to vs-style comparison
        # queries — on open-scenario queries the tokens are ordinary English
        # words ('feature', 'team', 'wants'), and PyPI matches polluted the
        # evidence chains with junk packages (recommended "flag (PyPI)" once).
        if _is_vs_query(query):
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
