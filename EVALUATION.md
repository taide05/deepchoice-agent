# Evaluation

> **Scope.** These are **internal** results on a fixed 200-case set with a fixed review protocol.
> They are not a third-party audit and are not a human-signed acceptance record. Do not extrapolate
> them beyond this fixed set.

## Fixed evaluation set

| Item | Value |
|---|---|
| Cases | 200 (`benchmarks/cases_formal_200.json`) |
| Domains | Frontend, backend, database, infrastructure, AI/ML |
| Languages | Chinese and English inputs |
| Case schema | `query`, `scene_context`, `candidate_techs`, `constraints`, `report_format`, `language` |
| SHA-256 (at evaluation time) | `46728f209aa12760afa39e0467b1c6c8fae1b0dac130b20e76ff1810031e3807` |

Each case is a realistic technology-selection question with a usage scene, constraints and two or more
candidates. The task is to produce a condition-aware recommendation grounded in cited evidence.

## Metrics

A report is judged on content (not structure or citation count):

| Metric | Definition |
|---|---|
| **Usable** | The report answers the question (C1) and contains no critical (decision-misleading) error (C4 = 0). |
| **Decision-grade** | Usable **and** key claims are evidence-comparable (C2) **and** conditions/limitations are stated (C3). |
| **C4 (critical error)** | A defect that could mislead the decision: fabricated constraint/threshold, wrong attribution row, retrieval gap asserted as a product fact, contradictory decision branches, unstated current-stack premise driving the ranking, etc. |

Report-level checks:

- **C1 — answer**: does the report actually help choose (tendency, reasons, conditions that would change it)?
- **C2 — evidence calibration**: are decisive claims backed by applicable evidence on both sides (or an
  explicitly disclosed gap turned into a conditional branch)? Are attributes, prices and permissions
  attributed per row/product? Are secondary/community sources kept from becoming hard gates?
- **C3 — conditions & gaps**: are the conditions, uncertainties and limitations stated?
- **C4 — critical errors**: would any claim mislead the decision? (0 = none)

## Results (fixed 200-case set)

| Metric | Result |
|---|---:|
| Completed | **200 / 200** |
| Usable | **199 / 200 (99.5%)** |
| Decision-grade | **179 / 200 (89.5%)** |
| Critical errors (C4) | **1 / 200** |

Observation statistics from the same evaluation run:

| Observation | Value |
|---|---:|
| Official documentation pages collected | 903 (mean 4.51 per case, 0 cases with zero official pages) |
| Server-side extraction fallback pages | 211 |
| LLM tokens per case (mean / p50) | 79,970 / 76,674 |
| Wall time per case (p50 / p95) | 262.8 s / 453.8 s |

## Review protocol

- **Three layers**: (1) internal full-set content review, (2) independent full-set re-review with the same
  rubric (blind to the first layer), (3) independent spot-check of repaired cases plus a fresh random sample.
- **Calibration**: when the two full-set layers disagreed on a case, a third-pass adjudication applied the
  written rubric; the adjudication rule and per-case outcomes are recorded in the internal review records.
- **Repairs**: cases judged to contain critical errors were regenerated from the same fixed question (same
  case ID, no replacement) and re-reviewed under the same rubric.
- The review is **AI-assisted**; it is not a human signature and not a blind third-party benchmark.

## Reproducing a run

1. Install the project and provide credentials (see README).
2. Use the fixed set in `benchmarks/cases_formal_200.json`.
3. Run the research pipeline for each case with a fixed configuration (evidence budget, concurrency and
   timeouts), then compute the completion and token statistics.
4. Content verdicts require the review rubric described above; a single-run reproduction without review only
   reproduces *completion and observability* metrics, not the quality verdicts.

A full 200-case run makes real LLM/search API calls and costs real money; budget accordingly.

## Known limitations of these results

- Fixed-set internal evaluation; results should not be extrapolated to other domains or to future model
  versions.
- Content review is AI-assisted and calibrated; it is not a human acceptance record.
- One case in the set contains a known critical error (C4 = 1) and is disclosed in internal records rather
  than silently excluded; the rest of the set passed the calibrated review.
