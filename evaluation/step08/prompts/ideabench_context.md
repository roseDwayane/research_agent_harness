---
version: 1.0.0
tool_name: emit_ideabench_context
tool_description: Infer a broad research topic and PICO from reference abstracts only.
---
Describe the shared biomedical research context using only the provided references. Keep the topic broad; do not guess the contents of a future paper. State uncertainty and avoid inventing a specific population or intervention when references span several settings.
===USER===
References:
{{references}}
Return topic and PICO (population, intervention, comparison, outcome, setting, timeframe).
