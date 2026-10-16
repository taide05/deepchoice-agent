import io
import msgpack
import pathlib
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

db = pathlib.Path(r"D:\deepchoice-precodex\outputs\checkpoints.db")
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
try:
    rows = conn.execute(
        "SELECT rowid, thread_id, CAST(checkpoint AS BLOB) FROM checkpoints "
        "WHERE thread_id = ? ORDER BY rowid", ("8049500c-bd39-44e4-81bb-a1fbbebac780",)
    ).fetchall()
finally:
    conn.close()

print(f"checkpoints for this task: {len(rows)}")
for rowid, _tid, blob in rows:
    d = msgpack.unpackb(blob, raw=False)
    v = d.get("channel_values", {})
    branches = [k for k in v if k.startswith("branch:")]
    phase = v.get("current_phase")
    usage = v.get("token_usage") or []
    agents = [u.get("agent") for u in usage if isinstance(u, dict)]
    qs = [q.get("agent") for q in (v.get("quality_signals") or [])]
    rec = v.get("final_recommendation") or {}
    print(f"  #{rowid} ts={d.get('ts','')[:19]} phase={phase!r} {branches}")
    print(f"        usage agents={agents}")
    print(f"        quality_signals={qs}")
    print(f"        winner={rec.get('winner')!r} confidence={rec.get('confidence')!r}")
