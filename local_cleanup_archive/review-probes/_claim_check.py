import io
import json
import pathlib
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
report = (RUN / "report.md").read_text(encoding="utf-8")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))

# Map title -> longest available body text.
bodies = {}
for c in state.get("evidence_chains") or []:
    for s in c.get("sources", []):
        t = s.get("title", "")
        if t:
            bodies.setdefault(t, s.get("snippet") or "")

def cited_bodies(sentence):
    out = []
    for name in re.findall(r"\[Source:\s*([^\]]+)\]", sentence):
        for part in name.split(", Source:"):
            part = part.strip()
            if part in bodies:
                out.append((part, bodies[part]))
    return out

# The two claims whose candidate had no attributed material.
targets = {
    "Serverless 免集群管理": "免集群管理",
    "Serverless 零调优": "零调优",
    "UltraWarm 计价": "$0.024",
    "Athena 计费方式": "按扫描量计费",
}
for label, needle in targets.items():
    hits = [ln for ln in report.splitlines() if needle in ln]
    print(f"\n=== {label} ===")
    if not hits:
        print("  claim text not found verbatim")
        continue
    sentence = hits[0]
    print("  claim:", sentence[:200])
    for name, body in cited_bodies(sentence)[:2]:
        print(f"  cited source: {name}")
        # Does the source body actually mention the decisive term?
        term = needle.strip("$").split("/")[0]
        present = term.lower() in body.lower()
        print(f"    body mentions '{term}': {present}")
        print(f"    body: {body[:220]}")

print("\n=== all distinct cited sources, with whether they carry a body ===")
cited = set()
for name in re.findall(r"\[Source:\s*([^\]]+)\]", report):
    for part in name.split(", Source:"):
        cited.add(part.strip())
for name in sorted(cited):
    body = bodies.get(name)
    if body is None:
        print(f"  [NO SUCH SOURCE] {name}")
    else:
        print(f"  [{'body' if body.strip() else 'BODY-LESS'}] {len(body):5}  {name[:70]}")
