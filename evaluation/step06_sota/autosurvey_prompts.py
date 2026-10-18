"""Evaluation prompts and rubrics copied verbatim from AutoSurvey (NeurIPS 2024).

Source: https://github.com/AutoSurveys/AutoSurvey (MIT License)
    CRITERIA                       src/agents/judge.py
    CRITERIA_BASED_JUDGING_PROMPT  src/prompt.py
    NLI_PROMPT                     src/prompt.py

Only the dict keys of CRITERIA are normalized ("score 1" → "score1"); every string, typos
included, is unchanged so scores stay comparable in form to the paper's. Trailing spaces in
NLI_PROMPT are written as \x20 so editors do not strip them (byte equality with the AutoSurvey
source checked on 2026-10-07).

NAIVE_SURVEY_PROMPT is ours: the AutoSurvey repo does not ship its naive RAG baseline prompt.
"""

CRITERIA = {
    'Coverage': {
        'description': 'Coverage: Coverage assesses the extent to which the survey encapsulates all relevant aspects of the topic, ensuring comprehensive discussion on both central and peripheral topics.',
        'score1': 'The survey has very limited coverage, only touching on a small portion of the topic and lacking discussion on key areas.',
        'score2': 'The survey covers some parts of the topic but has noticeable omissions, with significant areas either underrepresented or missing.',
        'score3': 'The survey is generally comprehensive in coverage but still misses a few key points that are not fully discussed.',
        'score4': 'The survey covers most key areas of the topic comprehensively, with only very minor topics left out.',
        'score5': 'The survey comprehensively covers all key and peripheral topics, providing detailed discussions and extensive information.',
    },
    'Structure': {
        'description': 'Structure: Structure evaluates the logical organization and coherence of sections and subsections, ensuring that they are logically connected.',
        'score1': 'The survey lacks logic, with no clear connections between sections, making it difficult to understand the overall framework.',
        'score2': 'The survey has weak logical flow with some content arranged in a disordered or unreasonable manner.',
        'score3': 'The survey has a generally reasonable logical structure, with most content arranged orderly, though some links and transitions could be improved such as repeated subsections.',
        'score4': 'The survey has good logical consistency, with content well arranged and natural transitions, only slightly rigid in a few parts.',
        'score5': 'The survey is tightly structured and logically clear, with all sections and content arranged most reasonably, and transitions between adajecent sections smooth without redundancy.',
    },
    'Relevance': {
        'description': 'Relevance: Relevance measures how well the content of the survey aligns with the research topic and maintain a clear focus.',
        'score1': 'The  content is outdated or unrelated to the field it purports to review, offering no alignment with the topic',
        'score2': 'The survey is somewhat on topic but with several digressions; the core subject is evident but not consistently adhered to.',
        'score3': 'The survey is generally on topic, despite a few unrelated details.',
        'score4': 'The survey is mostly on topic and focused; the narrative has a consistent relevance to the core subject with infrequent digressions.',
        'score5': 'The survey is exceptionally focused and entirely on topic; the article is tightly centered on the subject, with every piece of information contributing\
                                    to a comprehensive understanding of the topic.',
    },
}

CRITERIA_BASED_JUDGING_PROMPT = '''
Here is an academic survey about the topic "[TOPIC]":
---
[SURVEY]
---

<instruction>
Please evaluate this survey about the topic "[TOPIC]" based on the criterion above provided below, and give a score from 1 to 5 according to the score description:
---
Criterion Description: [Criterion Description]
---
Score 1 Description: [Score 1 Description]
Score 2 Description: [Score 2 Description]
Score 3 Description: [Score 3 Description]
Score 4 Description: [Score 4 Description]
Score 5 Description: [Score 5 Description]
---
Return the score without any other information:
'''

NLI_PROMPT = '''
---
Claim:
[CLAIM]
---
Source: 
[SOURCE]
---
Claim:
[CLAIM]
---
Is the Claim faithful to the Source? 
A Claim is faithful to the Source if the core part in the Claim can be supported by the Source.\n
Only reply with 'Yes' or 'No':
'''

NAIVE_SURVEY_PROMPT = '''You are writing an academic literature survey on the topic "[TOPIC]".

Below are [N] papers. Each has a citation key, title, year and abstract.
---
[PAPERS]
---

Write a comprehensive survey of this topic in Markdown, in English, using only the papers above:
- a title, an introduction, sections and subsections organised by theme, and a conclusion;
- support every factual statement with citations written as (CitationKey), e.g. (SmithEtAl2024) or (SmithEtAl2024; LeeKim2023);
- cite only keys from the list above;
- aim for about [WORDS] words.

Return only the survey.
'''


def fill(template: str, values: dict[str, str]) -> str:
    """AutoSurvey's Judge.__generate_prompt: replace every [KEY] placeholder."""
    for key, value in values.items():
        template = template.replace(f'[{key}]', value)
    return template
