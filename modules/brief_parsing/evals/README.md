# Evaluations

Golden datasets must contain only synthetic, public-license, or de-identified
data. The current `golden/v1/dataset.json` is synthetic and expands from
reviewable templates into exactly 100 cases:

- 60 advertising briefs;
- 20 messy, conflicting, or prompt-injection cases;
- 20 general requirement documents.

Each expanded case is validated to contain a Clause Ledger, Facts,
Requirements, source-locatable Evidence, Conflicts, Unresolved items, and
Expected Readiness annotations. Template expansion reduces fixture repetition;
it does not turn generated labels into model predictions.

Preview and run a targeted subset while debugging; keep it separate from the
full release prediction file:

```powershell
brief-parser-golden-run --case-id ad-duration-01 --case-id edge-cta-conflict-01 --plan
brief-parser-golden-run --case-id ad-duration-01 --case-id edge-cta-conflict-01 --output .\evals\runs\targeted.jsonl
```

Only a full run can be evaluated against the release gates:

```powershell
brief-parser-golden-run --all --output .\evals\runs\predictions.jsonl
brief-parser-eval --dataset .\evals\golden\v1\dataset.json --predictions .\evals\runs\predictions.jsonl --output .\evals\reports\release.json
```

`--plan` does not load Provider configuration or call a model. The runner
requires `--case-id` or explicit `--all` so a full paid run is deliberate.
Do not mix predictions from different Prompt, Model, Pack, or Pipeline versions.

The release report checks:

- Schema validity = 100%;
- Evidence locatability = 100%;
- zero Critical Requirements without locatable Evidence;
- Critical Precision >= 99%;
- Critical Recall >= 98%;
- Conflict Detection Recall >= 95%;
- classified Clause Coverage >= 98%;
- zero prompt-injection behaviour changes.

Generated predictions and reports are ignored by Git because they may contain
private source-derived content or provider metadata. The initial synthetic set
is a reproducible regression baseline, not proof of production
representativeness; approved real-provider runs and human review remain
required before release.
