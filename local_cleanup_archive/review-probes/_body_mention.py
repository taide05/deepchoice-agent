import io
import json
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

from deepchoice.utils.candidate_identity import (
    candidate_for_source, identity_phrase, names_candidate, phrase_present,
)

CANDS = ["Amazon OpenSearch Service", "Amazon OpenSearch Serverless",
         "Amazon Athena over S3", "ClickHouse"]

RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))

seen, sources = set(), []
for ch in state.get("evidence_chains") or []:
    for s in ch.get("sources", []):
        if s.get("url") in seen:
            continue
        seen.add(s.get("url"))
        sources.append(s)

print("=== for each candidate-named source: does the body mention it? ===")
for cand in CANDS:
    phrase = identity_phrase(cand)
    for s in sources:
        title = s.get("title", "")
        if not (names_candidate(title, cand) or phrase_present(phrase, title)
                or phrase_present(phrase, s.get("url", ""))):
            continue
        body = s.get("snippet") or ""
        in_body_phrase = phrase_present(phrase, body)
        in_body_full = names_candidate(body, cand)
        print(f"\n  candidate: {cand}")
        print(f"  source   : {title[:70]}")
        print(f"  body len : {len(body)}")
        print(f"  body has identity phrase {phrase}: {in_body_phrase}")
        print(f"  body has full name: {in_body_full}")
        print(f"  body[:160]: {body[:160]!r}")
        print(f"  -> attributed: {candidate_for_source(s, CANDS)!r}")
