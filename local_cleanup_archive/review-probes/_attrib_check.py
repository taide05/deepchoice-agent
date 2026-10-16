import io
import json
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

from deepchoice.utils.candidate_identity import (
    candidate_for_source,
    identity_phrase,
    index_sources_by_candidate,
    UNASSIGNED,
)

CANDS = ["Amazon OpenSearch Service", "Amazon OpenSearch Serverless",
         "Amazon Athena over S3", "ClickHouse"]

print("=== identity phrases ===")
for c in CANDS:
    print(f"  {c:32} -> {identity_phrase(c)}")

print("\n=== the Athena case (should attribute) ===")
cases = [
    ("Amazon Athena - Serverless Interactive Query Service - Amazon Web Services",
     "https://aws.amazon.com/athena/"),
    ("PostgreSQL 17 release notes", "https://www.postgresql.org/docs/release-17"),
    ("What is serverless computing?", "https://ex.com/serverless"),
    ("Amazon OpenSearch Serverless pricing", "https://aws.amazon.com/opensearch-serverless"),
]
for title, url in cases:
    print(f"  {title[:60]:62} -> {candidate_for_source({'title': title, 'url': url}, CANDS)}")

print("\n=== replay the real run's 29 sources with the new rule ===")
RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))
seen, sources = set(), []
for ch in state.get("evidence_chains") or []:
    for s in ch.get("sources", []):
        key = s.get("url")
        if key in seen:
            continue
        seen.add(key)
        sources.append(s)
index = index_sources_by_candidate(sources, CANDS)
for cand in CANDS:
    rows = index.get(cand) or []
    print(f"  {cand[:34]:36} {len(rows)} source(s)")
    for s in rows[:3]:
        print(f"      {s.get('title','')[:66]}")
print(f"  {'UNASSIGNED':36} {len(index.get(UNASSIGNED) or [])}")
