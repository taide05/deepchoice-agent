"""Online entry for the single bounded page-level probe.

Run only after code/tests are frozen. This is separate from pytest, which keeps
external network blocked. It uses the actual safe-fetch/extraction path and the
frozen eight URLs in `deepchoice.evaluation.page_probe`; no LLM, Tavily, judge,
or paid benchmark is called.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
SRC = WORKTREE / "src"
for path in (str(SRC), str(WORKTREE)):
    if path not in sys.path:
        sys.path.insert(0, path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default=str(
        Path(r"D:\deepchoice-dsh\v11_page_probe")))
    args = parser.parse_args(argv)
    os.chdir(WORKTREE)
    # The probe uses the direct safe-fetch path only; it must not select a
    # forward/proxy route or perform any health probe.
    os.environ["OUTBOUND_CHANNELS"] = "direct"
    from deepchoice.evaluation.page_probe import run_probe
    result = asyncio.run(run_probe(outdir=args.outdir))
    print(json.dumps({
        "outdir": args.outdir,
        "freeze_sha256": result["freeze_sha256"],
        "elapsed_s": result["elapsed_s"],
        "budget": result["budget"],
        "wall_ok": result["total_wall_ok"],
        "pages_ok": result["page_attempts_ok"],
        "http_ok": result["http_requests_ok"],
        "records": [{"url": r["url"], "ok": r["ok"],
                     "page_role": r.get("page_role"),
                     "failure": r.get("failure"),
                     "identity_verified": r.get("identity_verified")}
                    for r in result["records"]],
    }, ensure_ascii=False, indent=2))
    return 0 if (result["total_wall_ok"] and result["page_attempts_ok"]
                 and result["http_requests_ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
