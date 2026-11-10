# Step 8 / IdeaBench

`python -m evaluation.step08.cli` is the organized Step 8 entry point. It delegates to the existing
`ideabench_eval` package so existing commands and saved experiment outputs remain compatible. That package contains
the official-dataset adapter, P1/P2 generation, independent novelty/feasibility ranking, schemas, and model client.
