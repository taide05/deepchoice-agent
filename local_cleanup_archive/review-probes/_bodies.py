import io
import json
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))

want = ["Amazon Athena", "Elastic", "AWS OpenSearch Deep Dive", "SelectDB",
        "OpenSearch vs ClickStack", "ClickHouse 填平", "托管 ClickStack"]
seen = set()
for c in state.get("evidence_chains") or []:
    for s in c.get("sources", []):
        title = s.get("title", "")
        if title in seen:
            continue
        if not any(w.lower() in title.lower() for w in want):
            continue
        seen.add(title)
        print("=" * 100)
        print(f"TITLE : {title}")
        print(f"URL   : {s.get('url')}")
        print(f"SCORE : {s.get('score')}  strength={c.get('evidence_strength')}")
        print("-" * 100)
        print(s.get("snippet") or "(no body)")
        print()
