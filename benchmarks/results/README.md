# Evaluation results

`formal_200_metrics.json` — deterministic, machine-readable metrics from the fixed 200-case evaluation run
(completion, tokens, wall time, official-source coverage, evidence budget, citation gaps, health flags) plus
the calibrated content-evaluation summary and the run configuration/provenance.

Only deterministic/aggregate data is published here. It can be re-computed from the run artifacts; the content
verdicts were produced with the AI-assisted calibrated review protocol described in `EVALUATION.md` and are
**inside** the aggregate counts only (no per-case review notes are included).

Notes:
- Internal evaluation, fixed set: do not extrapolate to other domains or model versions.
- One known critical error is disclosed (C4 = 1/200), not excluded.
- Token totals are API usage, not necessarily billed cost.
