"""Programmatic test case generator from taxonomy."""
import json
from pathlib import Path

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"

TEMPLATES = {
    "simple": "{tech_a} vs {tech_b} for a {scene_desc} project",
    "medium": "Comparing {tech_a} and {tech_b}: which is better for {scene_desc} with {variant} requirements?",
    "hard": "Full-stack technology selection for a {scene_desc} system: {tech_a} vs {tech_b} ecosystem comparison considering {variant}",
}

SCENE_DESC = {
    "solo": "solo developer",
    "team": "mid-size team",
    "enterprise": "enterprise-grade",
}

TECH_PAIRS = {
    "agent_orchestration": [("LangGraph", "CrewAI"), ("AutoGen", "Semantic Kernel")],
    "mcp_ecosystem": [("FastMCP", "MCP Python SDK"), ("mcp-server-fetch", "custom MCP")],
    "tool_calling": [("OpenAI function calling", "Anthropic tool use"), ("LangChain tools", "native function calling")],
    "llm_invocation": [("OpenAI SDK", "LangChain"), ("Anthropic SDK", "LiteLLM")],
    "multi_agent_collaboration": [("CrewAI", "AutoGen"), ("LangGraph", "CrewAI")],
    "rag_frameworks": [("LangChain RAG", "LlamaIndex"), ("Haystack", "LangChain")],
    "memory_systems": [("Mem0", "Zep"), ("LangChain Memory", "custom Redis")],
    "web_frameworks": [("FastAPI", "Flask"), ("Django", "FastAPI"), ("Express", "NestJS"), ("Go-Gin", "FastAPI")],
    "api_paradigms": [("REST", "GraphQL"), ("gRPC", "REST"), ("WebSocket", "SSE")],
    "auth_authorization": [("JWT", "OAuth2"), ("API Key", "JWT"), ("OAuth2", "SAML")],
    "relational_db": [("PostgreSQL", "MySQL"), ("PostgreSQL", "SQLite"), ("MySQL", "MariaDB")],
    "nosql": [("MongoDB", "PostgreSQL JSON"), ("Redis", "MongoDB"), ("Cassandra", "MongoDB")],
    "caching": [("Redis", "Memcached"), ("Redis", "Dragonfly"), ("in-memory", "Redis")],
    "message_queues": [("RabbitMQ", "Kafka"), ("Redis", "RabbitMQ"), ("NATS", "Kafka")],
    "vector_databases": [("Chroma", "Pinecone"), ("Weaviate", "Qdrant"), ("Milvus", "Chroma")],
    "llm_selection": [("GPT-4o", "Claude Sonnet 4.5"), ("DeepSeek V4", "GPT-4o"), ("Claude Haiku", "Gemini Flash")],
    "embedding_models": [("OpenAI text-embedding-3", "bge-m3"), ("bge-m3", "E5"), ("Cohere Embed", "bge-m3")],
    "container_orchestration": [("Kubernetes", "Docker Swarm"), ("Kubernetes", "Nomad"), ("K8s", "Docker Compose")],
    "cicd": [("GitHub Actions", "GitLab CI"), ("Jenkins", "GitHub Actions"), ("ArgoCD", "GitHub Actions")],
    "monitoring": [("Prometheus", "Datadog"), ("Grafana", "Datadog"), ("Sentry", "self-hosted")],
    "logging": [("ELK", "Loki"), ("Datadog", "ELK"), ("CloudWatch", "ELK")],
    "async_solutions": [("asyncio", "gevent"), ("FastAPI", "aiohttp"), ("Celery", "RQ")],
    "task_queues": [("Celery", "RQ"), ("Celery", "Dramatiq"), ("BullMQ", "Celery")],
    "api_gateways": [("Kong", "Traefik"), ("Nginx", "Kong"), ("Caddy", "Nginx")],
}


def generate_cases(count: int = 1000) -> list[dict]:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    cases = []
    case_id = 0

    for cat_key, cat_data in taxonomy["categories"].items():
        for subdomain in cat_data["subdomains"]:
            pairs = TECH_PAIRS.get(subdomain, [("OptionA", "OptionB")])
            for tech_a, tech_b in pairs:
                for scene in taxonomy["scenes"]:
                    for difficulty in taxonomy["difficulties"]:
                        for variant in taxonomy["variant_factors"][:2]:
                            template = TEMPLATES[difficulty]
                            query = template.format(
                                tech_a=tech_a,
                                tech_b=tech_b,
                                scene_desc=SCENE_DESC[scene],
                                variant=variant,
                            )
                            cases.append({
                                "id": f"TC-{case_id:04d}",
                                "query": query,
                                "category": cat_data["label"],
                                "subdomain": subdomain,
                                "scene": scene,
                                "difficulty": difficulty,
                                "variant": variant,
                                "tech_a": tech_a,
                                "tech_b": tech_b,
                                "expected_winner": None,
                                "ground_truth_notes": "",
                            })
                            case_id += 1
                            if case_id >= count:
                                return cases
    return cases


if __name__ == "__main__":
    cases = generate_cases()
    output_path = Path(__file__).parent / "generated_cases.json"
    output_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(cases)} test cases -> {output_path}")
