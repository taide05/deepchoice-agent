import asyncio
import ipaddress
import os
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .. import outbound as _outbound
from ..utils.llm import call_model
from .base import BaseRetriever
from .learned_docs import (
    _looks_official,
    domain_label_match,
    is_plausible_term,
    learn,
    load_learned,
)

# A discovered official link is not a body. These bounds make the source layer
# collect a bounded, traceable excerpt through the same routed outbound client
# used for the rest of the retriever. They are deliberately small constants, not
# a crawler: at most a few pages per run, one page per candidate, no link
# following beyond safe HTTP redirects.
OFFICIAL_FETCH_MAX_PER_RUN = int(os.environ.get("OFFICIAL_FETCH_MAX_PER_RUN", "2"))
OFFICIAL_FETCH_MAX_BYTES = int(os.environ.get("OFFICIAL_FETCH_MAX_BYTES", "200000"))
OFFICIAL_FETCH_TIMEOUT_S = float(os.environ.get("OFFICIAL_FETCH_TIMEOUT_S", "10"))
OFFICIAL_FETCH_MAX_REDIRECTS = 3
OFFICIAL_BODY_STORE_CHARS = int(os.environ.get("OFFICIAL_BODY_STORE_CHARS", "8000"))
_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

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


def _url_shape_ok(url: str) -> tuple[bool, str]:
    """Cheap URL shape check before DNS/network work."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "invalid_url"
    if parsed.scheme not in ("http", "https"):
        return False, "scheme_not_http"
    if not parsed.hostname or parsed.username or parsed.password:
        return False, "host_or_userinfo"
    try:
        port = parsed.port
    except ValueError:
        return False, "invalid_port"
    if port not in (None, 80, 443):
        return False, "port_not_allowed"
    return True, ""


def _public_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    # is_global rejects loopback, private, link-local, reserved, multicast,
    # unspecified and RFC 6598 carrier-grade NAT (100.64.0.0/10), which the
    # individual flags would otherwise miss.
    return address.is_global


def _resolve_host_ips(host: str, port: int) -> list[str]:
    """Resolve a host for the safety check. Tests replace this seam."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


async def _url_is_safe(url: str) -> tuple[bool, str]:
    shape_ok, reason = _url_shape_ok(url)
    if not shape_ok:
        return False, reason
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        ips = await asyncio.wait_for(
            asyncio.to_thread(_resolve_host_ips, parsed.hostname, port), timeout=5)
    except Exception:
        return False, "dns_unavailable"
    if not ips or not all(_public_ip(ip) for ip in ips):
        return False, "non_public_ip"
    return True, ""


class _BodyTextExtractor(HTMLParser):
    """Small bounded HTML-to-text extractor for official documentation pages."""

    _SKIP = {"script", "style", "noscript", "template", "svg", "canvas"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        else:
            self.parts.append(text)


def _extract_official_text(raw: str) -> tuple[str, str]:
    parser = _BodyTextExtractor()
    try:
        parser.feed(raw)
    except Exception:
        # HTMLParser can accept partial documents, but never turn a parser error
        # into an unbounded exception path.
        return "", ""
    title = " ".join(" ".join(parser.title_parts).split())
    text = " ".join(" ".join(parser.parts).split())
    return title, text


async def _fetch_official_page(url: str) -> dict:
    """Fetch one official page with bounded size, timeout, redirects and safety.

    Returns a plain result record; never raises for remote failures. The caller
    must keep a failed fetch as a navigation link (has_body=False), not as
    evidence, and must not synthesize body text. ``url`` remains the registered
    identity even if a safe redirect supplied the body.
    """
    current = url
    visited: set[str] = set()
    for redirect_count in range(OFFICIAL_FETCH_MAX_REDIRECTS + 1):
        if current in visited:
            return {"ok": False, "url": current, "error": "redirect_loop"}
        visited.add(current)
        safe, reason = await _url_is_safe(current)
        if not safe:
            return {"ok": False, "url": current, "error": f"unsafe_url:{reason}"}
        try:
            async with await _outbound.make_client("official") as client:
                async with client.stream(
                        "GET", current, timeout=OFFICIAL_FETCH_TIMEOUT_S,
                        follow_redirects=False) as response:
                    status = response.status_code
                    if status in (301, 302, 303, 307, 308):
                        location = response.headers.get("location", "")
                        if not location or redirect_count >= OFFICIAL_FETCH_MAX_REDIRECTS:
                            return {"ok": False, "url": current,
                                    "error": "redirect_limit"}
                        current = urljoin(current, location)
                        continue
                    if status != 200:
                        return {"ok": False, "url": current, "error": f"http:{status}"}
                    content_type = (response.headers.get("content-type", "")
                                    .split(";")[0].strip().lower())
                    if content_type and content_type not in _HTML_CONTENT_TYPES:
                        return {"ok": False, "url": current,
                                "error": f"content_type:{content_type}"}
                    declared = response.headers.get("content-length")
                    if declared:
                        try:
                            too_big = int(declared) > OFFICIAL_FETCH_MAX_BYTES
                        except ValueError:
                            too_big = False
                        if too_big:
                            return {"ok": False, "url": current,
                                    "error": "content_too_large"}
                    chunks: list[bytes] = []
                    total = 0
                    truncated = False
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        remaining = OFFICIAL_FETCH_MAX_BYTES - total
                        if len(chunk) > remaining:
                            chunks.append(chunk[:remaining])
                            total += remaining
                            truncated = True
                            break
                        chunks.append(chunk)
                        total += len(chunk)
                    raw = b"".join(chunks).decode("utf-8", "replace")
                    title, text = _extract_official_text(raw)
                    if not text:
                        return {"ok": False, "url": current,
                                "error": "empty_body"}
                    stored = text[:OFFICIAL_BODY_STORE_CHARS].rstrip()
                    return {
                        "ok": True,
                        "url": url,
                        "body_url": current,
                        "title": title,
                        "body": stored,
                        "source_chars": len(text),
                        "stored_chars": len(stored),
                        "truncated": (truncated or len(text) > len(stored)),
                        "bytes": total,
                        "content_type": content_type,
                    }
        except Exception as exc:
            return {"ok": False, "url": current,
                    "error": f"{type(exc).__name__}"}
    return {"ok": False, "url": current, "error": "redirect_limit"}


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
            model="deepseek-flash", tag="official_fallback",
            response_format="json",
        )
        if isinstance(result, dict):
            return result.get("url")
        return None

    async def _fetch_official_body(self, url: str) -> dict:
        return await _fetch_official_page(url)

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None,
                         candidate_techs: list[str] | None = None) -> list[dict]:
        # Only declared candidates may introduce an official source. The adapted
        # queries are search aids: an ordinary word in them is not a research
        # target, and a learned-cache hit is not proof of candidacy either.
        from ..utils.candidate_identity import (
            candidate_names_key,
            mapping_key_for,
            normalize_term,
        )

        candidates = [c for c in (candidate_techs or []) if str(c).strip()]
        learned = load_learned()
        # Curated seed always wins: a learned entry must never shadow a
        # hand-verified mapping (e.g. a harvested 'python' entry once
        # overrode docs.python.org with python.langchain.com).
        lookup = {**learned, **TECH_DOCS}
        results = []

        if not candidates:
            # No declared identity, so nothing may be promoted to "official".
            # Better an explicit gap than an unowned official-looking source.
            return []

        # Mapping entries that a declared candidate actually names. This is the
        # whole bound: an unmapped candidate yields no official source rather
        # than matching on a shared ordinary word.
        named_keys = set(mapping_key_for(candidates, lookup))

        # Match whole declared candidate names against the mapping, so
        # 'PostgreSQL' inside 'pgvector on Amazon RDS for PostgreSQL' resolves to
        # the PostgreSQL docs, while 'vector' inside 'pgvector' cannot resolve to
        # an unrelated product that merely shares that word.
        for candidate in candidates:
            named = [k for k in named_keys if candidate_names_key(candidate, k)]
            if not named:
                continue
            # Longest match wins, so a candidate naming both 'postgresql' and a
            # more specific key resolves to the more specific one.
            key = max(named, key=lambda k: len(_normalize(k)))
            if key not in lookup:
                continue
            doc = lookup[key]
            entry = {
                "url": doc["url"],
                "title": doc["title"],
                # A mapping entry is a discovered link until the bounded page
                # fetch below succeeds; if it fails it stays navigation.
                "snippet": "",
                "has_body": False,
                "date": "",
                "_from_mapping": True,
            }
            if entry["url"] not in {r["url"] for r in results}:
                results.append(entry)

        # LLM fallback stays available, but only for a declared candidate that the
        # mapping does not name — never for an ordinary word from the query.
        unmapped_candidates = [
            c for c in candidates
            if not any(normalize_term(k) in normalize_term(c) for k in named_keys)
        ]

        async def _resolve_fallback(candidate):
            url = await self._propose_official_url(candidate)
            if not url or not domain_label_match(candidate, url):
                return None
            if not _looks_official(url):
                return None
            return candidate, url

        pending = unmapped_candidates[:_LLM_FALLBACK_MAX]
        resolved = await asyncio.gather(*[_resolve_fallback(c) for c in pending])
        for item in resolved:
            if item is None:
                continue
            candidate, url = item
            entry = {
                "url": url,
                "title": f"{candidate} — Official Documentation",
                "snippet": "",
                "has_body": False,
                "date": "",
                "_from_mapping": False,
            }
            if entry["url"] not in {r["url"] for r in results}:
                results.append(entry)

        # Fetch bounded bodies only after candidates/URLs are de-duplicated, so a
        # failed or seeded link cannot trigger duplicate network work. The budget
        # is per official-source search, and every attempt is visible on the saved
        # source row as body_error/fetch_status; an exhausted budget is navigation,
        # not evidence.
        remaining = max(0, OFFICIAL_FETCH_MAX_PER_RUN)
        for entry in results:
            if remaining <= 0:
                entry["body_error"] = "fetch_budget_exhausted"
                continue
            remaining -= 1
            fetched = await self._fetch_official_body(entry["url"])
            if not fetched.get("ok"):
                entry["has_body"] = False
                entry["snippet"] = ""
                entry["body_error"] = str(fetched.get("error") or "fetch_failed")
                entry["fetch_status"] = "failed"
                continue
            entry["snippet"] = fetched["body"]
            entry["has_body"] = True
            entry["fetch_status"] = "body"
            entry["body_url"] = fetched.get("body_url") or entry["url"]
            entry["body_chars"] = fetched.get("source_chars", len(fetched["body"]))
            entry["body_stored_chars"] = fetched.get(
                "stored_chars", len(fetched["body"]))
            entry["body_truncated"] = bool(fetched.get("truncated"))
            entry["body_content_type"] = fetched.get("content_type", "")
            if fetched.get("title") and entry["title"].endswith("Official Documentation"):
                entry["title"] = fetched["title"] or entry["title"]
            # Learn only a URL whose body was actually collected, and only when
            # the URL came from the LLM fallback. Re-learning a curated mapping on
            # every run would rewrite the user's learned_docs cache for no gain.
            if not entry.get("_from_mapping"):
                for candidate in candidates:
                    if entry["url"].startswith(("http://", "https://")) and \
                            domain_label_match(candidate, entry["url"]):
                        learn(candidate, entry["url"],
                              f"{candidate} — Official Documentation", via="body_fetch")
                        break

        return results[:max_results]
