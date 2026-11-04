# Provenance note — mixed batch (protocol v1.2 §3)

Primary run: batch inal-200-newcode-20261104 (200/200 complete, 15,932,513 tokens).
Three cases were first-attempt invalid per batch health (report-contract issues):

  F200-105  report_contract:malformed_unresolved_question
  F200-123  report_contract:ranked_option_no_rationale + decision_validation_recovered
  F200-173  report_contract:ranked_option_no_rationale + decision_validation_recovered

Per protocol v1.2 §3 (invalid must be re-run or explicitly counted), the same three
fixed-set cases were re-run in fill batch inal-200-newcode-fill-20261104
(258,604 tokens, 2026-11-04 05:54–06:03). All three returned health warn (no invalid).
Their fill artifacts (eport.md, snapshot.json, esearch_snapshot.json,
status.json) replaced the main-run copies so downstream metrics/reviews read one
consistent artifact per case. Provenance for the three cases:

  case      main attempt (invalid)      final attempt (used)
  F200-105  05:5x batch-...             final-200-newcode-fill-20261104
  F200-123  ...                         final-200-newcode-fill-20261104
  F200-173  ...                         final-200-newcode-fill-20261104

No replacement cases: all 200 case IDs are the fixed formal set; denominator 200.
Total formal-200 spend including fill: 16,191,117 tokens.
