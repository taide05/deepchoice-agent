"""Confirm every state path the old revision uses resolves inside its worktree."""
import importlib
import os
import pathlib
import sys

ROOT = r"D:\deepchoice-precodex"
sys.path.insert(0, os.path.join(ROOT, "src"))

import deepchoice.retrievers.learned_docs as ld
import deepchoice.retrievers.tavily_keypool as kp
import deepchoice.agents.orchestrator as orch

print("cwd                          :", os.getcwd())
print("deepchoice imported from     :", os.path.dirname(importlib.import_module("deepchoice").__file__))
print()
print("OUTPUT_DIR (orchestrator)    :", orch.OUTPUT_DIR.resolve())
print("checkpoint db                :", (orch.OUTPUT_DIR / "checkpoints.db").resolve())
print("LEARNED_DOCS_PATH            :", ld.LEARNED_DOCS_PATH.resolve())
print("tavily key state             :", os.path.abspath(kp._state_path()))
chroma = os.environ.get("CHROMA_PATH", "./chroma_kb/chroma_db")
print("CHROMA_PATH (default used)   :", os.path.abspath(chroma))
print()

rows = [
    ("outputs", orch.OUTPUT_DIR.resolve()),
    ("checkpoints.db", (orch.OUTPUT_DIR / "checkpoints.db").resolve()),
    ("learned_docs.json", ld.LEARNED_DOCS_PATH.resolve()),
    ("tavily_key_state.json", pathlib.Path(os.path.abspath(kp._state_path()))),
    ("chroma_db", pathlib.Path(os.path.abspath(chroma))),
]
inside = [r for r in rows if str(r[1]).lower().startswith(ROOT.lower())]
outside = [r for r in rows if not str(r[1]).lower().startswith(ROOT.lower())]
print("INSIDE the isolated worktree:")
for label, path in inside:
    print("   OK  ", label, "->", path)
print("OUTSIDE the isolated worktree:")
for label, path in outside:
    print("   !!  ", label, "->", path)
if not outside:
    print("   (none)")
