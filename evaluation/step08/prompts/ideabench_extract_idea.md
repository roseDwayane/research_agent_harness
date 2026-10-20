---
version: 1.0.0
tool_name: emit_ideabench_target_idea
tool_description: Emit the IdeaBench-style one-paragraph research idea extracted from a target paper abstract. Must begin with Hypothesis: or Given that .
---
You extract a research idea from a biomedical paper abstract for the IdeaBench benchmark. Follow the instructions in the user message exactly. Do not invent content that is not supported by the abstract. Strip detailed results and specific numerical data.
===USER===
Write a concise paragraph summarizing the following biomedical paper abstract as if you are proposing your own research idea or hypothesis. Focus on describing the main research idea and provide a high-level summary of the findings without detailed results or specific numerical data. Please begin the paragraph with "Hypothesis: " or "Given that ".
Abstract:
{{target_paper_abstract}}
Summary:
