"""Build the draft 120-group final-evaluation dataset (offline preparation only).

This draft creates independent requirement groups across the six protocol layers
by pairing technologies from the existing historical pool and curated fallback
names. It does NOT reuse a historical case as an evaluation case: every group is
a draft combination and a new requirement template; some pairs may coincide with
historical combinations and no independent dedupe was performed. Reference bases,
acceptable outcomes and scoring were not independently authored/verified, so the
dataset is explicitly `draft_pending_reference_authoring` and cannot be dispatched.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POOL = ROOT / "cases_eval_300.json"
OUTPUT = ROOT / "final-batch-v1.json"

LAYERS = {
    "A": {"name": "core_comparison", "quota": 30, "domain": "Backend Frameworks & API"},
    "B": {"name": "hard_constraints", "quota": 24, "domain": "Deployment & Operations"},
    "C": {"name": "evidence_insufficient", "quota": 18, "domain": "Models & Data"},
    "D": {"name": "version_applicability", "quota": 16, "domain": "AI/Agent Frameworks"},
    "E": {"name": "missing_requirements", "quota": 16, "domain": "Infrastructure"},
    "F": {"name": "security_cost_maintenance", "quota": 16, "domain": "Open Scenario"},
}
DOMAIN_POOL_FALLBACK = {
    "Backend Frameworks & API": ["FastAPI", "Flask", "Django", "Django Ninja", "Litestar", "Pyramid", "Tornado", "Falcon", "Sanic", "Starlette", "Express", "NestJS", "Fastify", "Koa", "Hono", "Gin", "Echo", "Fiber", "Chi", "Actix Web"],
    "Deployment & Operations": ["Kubernetes", "Nomad", "Docker Swarm", "OpenShift", "Rancher", "Argo CD", "Flux", "Terraform", "Pulumi", "Ansible", "Chef", "Puppet", "Helm", "Kustomize", "Crossplane", "Argo Rollouts", "Spinnaker", "Jenkins", "GitLab CI", "GitHub Actions"],
    "Models & Data": ["PostgreSQL", "MySQL", "MariaDB", "SQLite", "SQL Server", "Oracle Database", "MongoDB", "FerretDB", "CockroachDB", "YugabyteDB", "Kafka", "RabbitMQ", "Redis", "Valkey", "Qdrant", "Milvus", "Weaviate", "pgvector", "Elasticsearch", "OpenSearch"],
    "AI/Agent Frameworks": ["LangGraph", "CrewAI", "AutoGen", "Semantic Kernel", "LlamaIndex", "LangChain", "Haystack", "DSPy", "PydanticAI", "OpenAI Agents SDK", "Vercel AI SDK", "Mastra", "Agno", "Temporal", "Camunda", "Prefect", "Airflow", "Dagster", "Inngest", "Restate"],
    "Infrastructure": ["NATS", "RabbitMQ", "Kafka", "Redpanda", "Redis", "Memcached", "etcd", "Consul", "MinIO", "Ceph", "Traefik", "Envoy", "NGINX", "HAProxy", "Caddy", "Vault", "Keycloak", "Zitadel", "Prometheus", "Grafana"],
    "Open Scenario": ["Temporal", "Camunda", "LangGraph", "CrewAI", "FastAPI", "Django", "Kubernetes", "Nomad", "PostgreSQL", "MongoDB", "Kafka", "RabbitMQ", "Redis", "RabbitMQ", "Terraform", "Pulumi", "Argo CD", "Flux", "Qdrant", "Milvus"],
}
TEMPLATES = {
    "A": ("Compare {a} and {b} for a {scene} {domain} decision. Explain the main trade-off, "
          "the decisive evidence for each, and the conditions under which the recommendation reverses."),
    "B": ("Compare {a} and {b} for a {scene} {domain} deployment with a hard network, data-residency, "
          "budget, and on-call constraint. State which constraint eliminates or preserves each option and "
          "what remains unknown."),
    "C": ("Compare {a} and {b} for a {scene} {domain} choice where public authoritative evidence may be "
          "missing. Do not force a winner: identify the evidence gap, the impact on the choice, and what "
          "specific evidence would change the conclusion."),
    "D": ("Compare {a} and {b} for a {scene} {domain} migration where version, release channel, and "
          "end-of-support status affect the decision. State the applicable version conditions, date limits, "
          "and what must be verified before adoption."),
    "E": ("A {scene} {domain} request names {a} and {b} but omits workload, failure tolerance, and ownership. "
          "Give a conditional comparison, make the missing requirements explicit, and do not invent the missing data."),
    "F": ("Compare {a} and {b} for a {scene} {domain} choice focused on security boundaries, long-term "
          "operating cost, maintainability, and reversibility. Distinguish measured facts from estimates and "
          "state the stop or rollback conditions."),
}
MUST_ANSWER = {
    "A": ["compare both declared candidates, not only feature lists",
          "state the decisive evidence and applicability conditions",
          "give the conditions that reverse or stop the choice"],
    "B": ["apply the hard constraints to each candidate",
          "separate eliminated options from unknown evidence",
          "state the operational stop condition"],
    "C": ["identify the decisive evidence gap and its decision impact",
          "avoid an unsupported unique winner",
          "state what evidence would change the conclusion"],
    "D": ["bind the decisive claim to a version/date condition",
          "name what must be re-verified before adoption",
          "state the reversal or EOL condition"],
    "E": ["make missing requirements explicit",
          "give conditional advice without inventing measurements",
          "state the question that would unlock the decision"],
    "F": ["separate security facts from estimates",
          "cover cost/maintenance/reversibility honestly",
          "state stop and rollback conditions"],
}
CRITICAL_ERRORS = [
    "hard_constraint_violation", "fabricated_capability_or_source",
    "reversed_causality_or_applicability", "unsupported_exclusion_or_guarantee",
    "unsafe_operation",
]


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _domain_names(pool: list[dict]) -> dict[str, list[str]]:
    names: dict[str, set[str]] = {}
    for item in pool:
        category = str(item.get("category") or "")
        if category not in DOMAIN_POOL_FALLBACK:
            continue
        for key in ("tech_a", "tech_b"):
            value = str(item.get(key) or "").strip()
            if value:
                names.setdefault(category, set()).add(value)
    # Keep the curated fallback names as well, so the draft remains buildable
    # even when the historical catalog changes; all names are only source
    # material for new pairs, not reused historical cases.
    for category, fallback in DOMAIN_POOL_FALLBACK.items():
        names.setdefault(category, set()).update(fallback)
    return {key: sorted(value) for key, value in names.items()}


def _pairs(names: list[str], needed: int, used: set[str]) -> list[tuple[str, str]]:
    unique_names = sorted({name.strip() for name in names if name.strip()})
    found: list[tuple[str, str]] = []
    for first, second in itertools.combinations(unique_names, 2):
        key = "|".join(sorted((first.casefold(), second.casefold())))
        if key in used:
            continue
        found.append((first, second))
        used.add(key)
        if len(found) == needed:
            return found
    raise SystemExit(f"not enough names for {needed} unique pairs")


def _case(layer: str, pair: tuple[str, str], index: int, split: str) -> dict:
    first, second = pair
    scene = "solo developer" if index % 3 == 0 else (
        "3-person platform team" if index % 3 == 1 else "enterprise team")
    query = TEMPLATES[layer].format(a=first, b=second, scene=scene,
                                    domain=LAYERS[layer]["domain"])
    return {
        "id": f"FB-{layer}-{split[:1].upper()}-{index:02d}",
        "group_id": f"RG-{layer}-{split[0].upper()}-{index:02d}",
        "layer": layer,
        "layer_name": LAYERS[layer]["name"],
        "domain": LAYERS[layer]["domain"],
        "split": split,
        "scene": scene,
        "difficulty": "medium",
        "request": {
            "schema_version": 1,
            "query": query,
            "scene_context": scene,
            "constraints": [
                "Use only the original request's declared candidates.",
                "Bind decisive claims to an authoritative source with a date/version where available.",
                "If evidence is insufficient, state the missing evidence and its decision impact.",
            ],
            "candidate_techs": [first, second],
            "report_format": "what_why_how",
            "language": "en",
            "sub_questions": [
                "What roles and trade-offs do the two candidates have under the declared constraints?",
                "Which decisive claims need authoritative versioned evidence, and what remains unknown?",
                "When should the answer be conditional or a hold?",
            ],
        },
        "rubric": {
            "rule_id": "semantic-five-check-v1",
            "status": "draft_pending_freeze",
            "must_answer": MUST_ANSWER[layer],
            "acceptable_outcomes": ["recommended", "conditional", "insufficient_evidence"],
            "critical_error_types": CRITICAL_ERRORS,
        },
        "reference_basis": {
            "status": "pending_authoring_verification",
            "expected_winner": None,
            "required_evidence": [
                "official/primary source for each decisive capability",
                "date/version/applicability condition",
                "explicit unknown where public authoritative evidence is absent",
            ],
            "review_only": True,
            "must_not_enter_research_input": True,
        },
        "scoring": {
            "rule_id": "semantic-five-check-v1",
            "review_status": "pending",
            "reviewer": None,
            "independent_second_review": False,
        },
        "hitl": {"action": "limited_report", "repeat_action": "limited_report"},
        "eval_ready": False,
        "exposure_status": "generated_draft_unverified",
        "generation_method": "deterministic pair + layer template from historical technology catalog; independent authoring/reference verification not performed",
    }


def build() -> dict:
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    domains = _domain_names(pool)
    used: set[str] = set()
    final_cases: list[dict] = []
    calibration_cases: list[dict] = []
    for layer, spec in LAYERS.items():
        pairs = _pairs(domains[spec["domain"]], spec["quota"] + 2, used)
        for index, pair in enumerate(pairs[:spec["quota"]], start=1):
            final_cases.append(_case(layer, pair, index, "final"))
        for index, pair in enumerate(pairs[spec["quota"]:], start=1):
            calibration_cases.append(_case(layer, pair, index, "calibration"))
    dataset = {
        "dataset_id": "final-batch-v1",
        "version": "0.1.0-draft",
        "status": "draft_pending_reference_authoring",
        "freeze_date": None,
        "eval_ready": False,
        "description": (
            "Protocol-shaped draft of 120 independent requirement groups across six layers, "
            "plus an isolated 12-case calibration set. Cases are deterministic draft combinations, "
            "not historical evaluation cases or independently deduped final cases; references, expected outcomes and scoring are not "
            "independently authored/verified, so this is not an admitted evaluation dataset."
        ),
        "protocol": {
            "planned_N": 120,
            "layer_quotas": {layer: spec["quota"] for layer, spec in LAYERS.items()},
            "calibration_per_layer": 2,
            "split_policy": "calibration is disjoint and never enters final denominator",
        },
        "batch_budget": {
            "status": "not_authorized",
            "max_cases": 120,
            "candidate_runs_per_case": 1,
            "baseline_runs_per_case": 1,
            "repeat_subset_policy": "to freeze at 10-15% of final cases; repeats are separate runs",
            "unknown_cost": "unknown",
        },
        "admission_blockers": [
            "reference_basis_pending_independent_authoring_verification",
            "expected_outcomes_and_scoring_pending_freeze",
            "generated_draft_not_independently_prepared_or_exposed_cleared",
            "paired_baseline_runner_not_yet_integrated",
            "batch_budget_not_authorized",
        ],
        "cases": final_cases,
        "calibration": {
            "status": "draft_pending_reference_authoring",
            "isolated": True,
            "never_in_final_denominator": True,
            "cases": calibration_cases,
        },
    }
    dataset["content_sha256"] = hashlib.sha256(_canonical(dataset)).hexdigest()
    return dataset


def main() -> None:
    dataset = build()
    OUTPUT.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "final_cases": len(dataset["cases"]),
        "calibration_cases": len(dataset["calibration"]["cases"]),
        "layers": dict(Counter(c["layer"] for c in dataset["cases"])),
        "sha256": dataset["content_sha256"],
        "eval_ready": dataset["eval_ready"],
        "admission_blockers": dataset["admission_blockers"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
