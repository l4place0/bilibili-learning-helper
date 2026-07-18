"""Two-stage prompt system: classify first, then route to specialized prompts."""

# ============================================================
# Stage 1: Quick classification
# ============================================================

CLASSIFY_PROMPT = {
    "zh": """请快速分析以下视频内容，返回 JSON 格式：
{{"summary": "一句话概要（30字以内）", "type": "<类型标签>"}}

类型标签可选值：
- tutorial: 教程、教学、操作指南
- tech_talk: 技术分享、演讲、会议
- demo: 产品演示、实操演示、案例展示
- review: 评测、对比、推荐
- news: 新闻、时事、行业动态
- vlog: 日常记录、生活分享
- general: 其他

只返回 JSON，不要其他内容。

[转录文本]
{transcript}""",
    "en": """Quickly analyze the following video content, return JSON format:
{{"summary": "one-line summary (under 30 words)", "type": "<type label>"}}

Type labels:
- tutorial: tutorials, teaching, how-to guides
- tech_talk: tech talks, speeches, conferences
- demo: product demos, live demos, case studies
- review: reviews, comparisons, recommendations
- news: news, current events, industry updates
- vlog: daily logs, lifestyle content
- general: other

Return JSON only, nothing else.

[Transcript]
{transcript}""",
}

CLASSIFY_PROMPT_MULTIMODAL = {
    "zh": """请根据视频画面和转录文本快速分析，返回 JSON 格式：
{{"summary": "一句话概要（30字以内）", "type": "<类型标签>"}}

类型标签可选值：
- tutorial: 教程、教学、操作指南
- tech_talk: 技术分享、演讲、会议
- demo: 产品演示、实操演示、案例展示
- review: 评测、对比、推荐
- news: 新闻、时事、行业动态
- vlog: 日常记录、生活分享
- general: 其他

只返回 JSON，不要其他内容。

[转录文本]
{transcript}""",
    "en": """Quickly analyze the video visuals and transcript, return JSON format:
{{"summary": "one-line summary (under 30 words)", "type": "<type label>"}}

Type labels:
- tutorial: tutorials, teaching, how-to guides
- tech_talk: tech talks, speeches, conferences
- demo: product demos, live demos, case studies
- review: reviews, comparisons, recommendations
- news: news, current events, industry updates
- vlog: daily logs, lifestyle content
- general: other

Return JSON only, nothing else.

[Transcript]
{transcript}""",
}

# ============================================================
# Stage 2: Specialized prompts by content type
# ============================================================

SUMMARY_PROMPTS = {
    "tutorial": {
        "zh": """请对以下教程类视频进行结构化总结，按以下格式输出：

## 核心主题
一句话说明本教程教什么。

## 前置条件
列出学习本教程需要的基础知识或环境准备。

## 操作步骤
按顺序列出关键步骤，每步简要说明操作内容和目的。

## 关键要点
提取 3-5 个最重要的知识点或技巧。

## 常见问题/注意事项
如有提到易错点或注意事项，列出。

[转录文本]
{transcript}""",
        "en": """Summarize the following tutorial video in this structured format:

## Core Topic
One sentence on what this tutorial teaches.

## Prerequisites
List any required knowledge or setup.

## Steps
List key steps in order, briefly describing each action and its purpose.

## Key Takeaways
Extract 3-5 most important points or tips.

## Pitfalls / Notes
List any common mistakes or important notes mentioned.

[Transcript]
{transcript}""",
    },
    "tech_talk": {
        "zh": """请对以下技术分享/演讲类视频进行结构化总结，按以下格式输出：

## 核心观点
提炼演讲者的中心论点或核心主张。

## 背景与动机
为什么提出这个观点？解决什么问题？

## 关键论据/架构
支撑核心观点的技术细节、架构设计或数据。

## 演示/案例
如有演示或案例，简述其内容和效果。

## 结论与展望
演讲者的总结和对未来的判断。

[转录文本]
{transcript}""",
        "en": """Summarize the following tech talk in this structured format:

## Core Argument
Distill the speaker's central thesis or main claim.

## Background & Motivation
Why was this proposed? What problem does it solve?

## Key Evidence / Architecture
Technical details, architecture, or data supporting the core argument.

## Demos / Case Studies
Briefly describe any demos or cases shown and their results.

## Conclusion & Outlook
The speaker's summary and outlook on the future.

[Transcript]
{transcript}""",
    },
    "demo": {
        "zh": """请对以下演示/实操类视频进行结构化总结，按以下格式输出：

## 演示目标
说明演示的是什么产品/工具/功能。

## 操作流程
按顺序列出演示中的关键操作。

## 输入与输出
每步的关键输入是什么，得到什么输出/效果。

## 亮点与局限
演示中展现的优势和可能的不足。

[转录文本]
{transcript}""",
        "en": """Summarize the following demo video in this structured format:

## Demo Objective
What product/tool/feature is being demonstrated.

## Workflow
List key operations in order.

## Input & Output
What are the key inputs and resulting outputs/effects for each step.

## Strengths & Limitations
Advantages shown and any potential shortcomings.

[Transcript]
{transcript}""",
    },
    "review": {
        "zh": """请对以下评测/对比类视频进行结构化总结，按以下格式输出：

## 评测对象
列出被评测的产品/方案。

## 评测维度
列出从哪些方面进行评测。

## 核心结论
各维度的对比结论，谁优谁劣。

## 推荐建议
视频作者的最终推荐和适用场景。

[转录文本]
{transcript}""",
        "en": """Summarize the following review video in this structured format:

## Review Subjects
List the products/solutions being reviewed.

## Evaluation Criteria
List the dimensions used for comparison.

## Key Findings
Comparison results for each dimension — which is better and why.

## Recommendation
The author's final recommendation and best-fit scenarios.

[Transcript]
{transcript}""",
    },
    "news": {
        "zh": """请对以下新闻/资讯类视频进行结构化总结，按以下格式输出：

## 事件概述
一句话说明发生了什么。

## 关键事实
列出时间、地点、涉及方等关键事实。

## 背景与影响
事件的背景和可能产生的影响。

## 各方观点
如有不同立场或观点，分别列出。

[转录文本]
{transcript}""",
        "en": """Summarize the following news video in this structured format:

## Event Summary
One sentence on what happened.

## Key Facts
List time, location, parties involved, and other key facts.

## Context & Impact
Background of the event and its potential impact.

## Perspectives
List different viewpoints or positions if mentioned.

[Transcript]
{transcript}""",
    },
    "vlog": {
        "zh": """请对以下 Vlog/日常类视频进行结构化总结，按以下格式输出：

## 内容概要
一段话概括视频的主要内容。

## 关键场景
按时间顺序列出视频中的主要场景或活动。

## 值得关注的点
如有有趣的信息、推荐或经验分享，列出。

[转录文本]
{transcript}""",
        "en": """Summarize the following vlog in this structured format:

## Overview
A brief paragraph summarizing the video content.

## Key Scenes
List main scenes or activities in chronological order.

## Notable Points
List any interesting info, recommendations, or shared experiences.

[Transcript]
{transcript}""",
    },
    "general": {
        "zh": """请对以下视频内容进行结构化总结，按以下格式输出：

## 核心内容
一段话概括视频的核心主题和主要内容。

## 关键要点
提取 3-5 个最重要的信息点。

## 详细分析
按主题分段展开，保留重要细节和数据。

## 结论
总结视频的核心结论或行动建议。

[转录文本]
{transcript}""",
        "en": """Summarize the following video in this structured format:

## Core Content
A brief paragraph on the main topic and key content.

## Key Points
Extract 3-5 most important pieces of information.

## Detailed Analysis
Expand by topic, preserving important details and data.

## Conclusion
Summarize the core conclusions or action items.

[Transcript]
{transcript}""",
    },
}

# Multimodal variants add visual context instructions
MULTIMODAL_SUFFIX = {
    "zh": "\n\n请在分析中结合视频画面内容，标注关键视觉信息（如白板内容、图表、代码界面等）。",
    "en": "\n\nIn your analysis, incorporate visual content from the video (e.g., whiteboard notes, charts, code interfaces).",
}

# Citation instruction — appended to all summary prompts
CITATION_INSTRUCTION = {
    "zh": """

【引用规则】
转录文本已按段落编号（如 [S0 @00:00]、[S1 @00:15]）。请在总结中为每个关键事实标注来源段落：
- 单段引用：[S12]
- 连续段引用：[S12-S15]
- 离散段引用：[S12,S15]
引用放在句末。概括性语句和结论可不标注引用。
如有视频画面信息（如代码截图、架构图、白板内容），请用 [F@MM:SS] 标注对应的画面时间点。""",
    "en": """

[Citation Rules]
The transcript is segmented with IDs (e.g., [S0 @00:00], [S1 @00:15]). Cite source segments for each factual claim:
- Single segment: [S12]
- Range: [S12-S15]
- Multiple: [S12,S15]
Place citations at end of sentence. General statements and conclusions may omit citations.
If referencing visual content (code screenshots, diagrams, whiteboard), cite the frame timestamp as [F@MM:SS].""",
}

# Review cards suffix — appended to all summary prompts
REVIEW_CARDS_SUFFIX = {
    "zh": """

## 复习卡片

根据以上总结内容，生成 5-10 组知识卡片用于复习自测。每组包含一个问题和答案，覆盖视频中最重要的知识点。按以下格式输出：

**Q1:** （问题）
**A1:** （简明扼要的答案）

**Q2:** （问题）
**A2:** （答案）

以此类推。""",
    "en": """

## Review Cards

Based on the summary above, generate 5-10 flashcards for self-testing. Each card should cover an important knowledge point from the video. Use this format:

**Q1:** (question)
**A1:** (concise answer)

**Q2:** (question)
**A2:** (answer)

And so on.""",
}


def get_classify_prompt(lang: str = "zh", multimodal: bool = False) -> str:
    # Check custom store first
    from core.llm.prompt_store import get_prompt_store
    custom = get_prompt_store().get_classify(lang, multimodal)
    if custom:
        return custom
    prompts = CLASSIFY_PROMPT_MULTIMODAL if multimodal else CLASSIFY_PROMPT
    return prompts.get(lang, prompts["zh"])


DETAIL_INSTRUCTIONS = {
    "brief": {
        "zh": "\n\n【要求】请用 2-3 句话简洁概括核心内容，不要展开细节。",
        "en": "\n\n[Instruction] Summarize in 2-3 sentences. Be concise, no details.",
    },
    "normal": {
        "zh": "",
        "en": "",
    },
    "detailed": {
        "zh": "\n\n【要求】请提供详尽分析，包含具体例子、关键数据引用、重要时间点。每个要点尽量展开说明。",
        "en": "\n\n[Instruction] Provide thorough analysis with specific examples, data references, and key timestamps. Elaborate on each point.",
    },
}


def _get_review_cards_suffix(lang: str = "zh") -> str:
    """Get review cards suffix — custom from store or built-in default."""
    from core.llm.prompt_store import get_prompt_store
    custom = get_prompt_store().get_review_cards_suffix(lang)
    return custom or REVIEW_CARDS_SUFFIX.get(lang, REVIEW_CARDS_SUFFIX["zh"])


def get_summary_prompt(content_type: str, lang: str = "zh", multimodal: bool = False, detail: str = "normal", has_segments: bool = False) -> str:
    # Check custom store first
    from core.llm.prompt_store import get_prompt_store
    custom = get_prompt_store().get_summary(content_type, lang)
    if custom:
        if multimodal:
            suffix = MULTIMODAL_SUFFIX.get(lang, MULTIMODAL_SUFFIX["zh"])
            custom += suffix
        if has_segments:
            custom += CITATION_INSTRUCTION.get(lang, CITATION_INSTRUCTION["zh"])
        custom += _get_review_cards_suffix(lang)
        return custom
    type_prompts = SUMMARY_PROMPTS.get(content_type, SUMMARY_PROMPTS["general"])
    prompt = type_prompts.get(lang, type_prompts["zh"])
    if multimodal:
        suffix = MULTIMODAL_SUFFIX.get(lang, MULTIMODAL_SUFFIX["zh"])
        prompt += suffix
    # Append detail instructions
    detail_instr = DETAIL_INSTRUCTIONS.get(detail, DETAIL_INSTRUCTIONS["normal"])
    prompt += detail_instr.get(lang, detail_instr["zh"])
    # Append citation instruction if segments are available
    if has_segments:
        prompt += CITATION_INSTRUCTION.get(lang, CITATION_INSTRUCTION["zh"])
    # Append review cards suffix
    prompt += _get_review_cards_suffix(lang)
    return prompt


DETAIL_MAX_TOKENS = {
    "brief": 2048,
    "normal": 8192,
    "detailed": 20480,
}


# All known content types for validation
CONTENT_TYPES = {"tutorial", "tech_talk", "demo", "review", "news", "vlog", "general"}

# ============================================================
# Three-stage learning prompt (preview + index + summary)
# ============================================================

THREE_STAGE_PROMPT = {
    "zh": """你是一个视频学习助手。根据以下视频转录文本，生成三份结构化学习材料。

请严格返回以下 JSON 格式，不要包含其他内容：

```json
{{
  "preview": {{
    "overview": "2-3 句话概述视频主题和范围，不要剧透核心解答",
    "questions": ["核心问题1：观众带着这个问题去看视频", "核心问题2", "核心问题3"],
    "pre_quiz": [
      {{"question": "前置知识测验题", "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"], "answer": "A", "explanation": "简短解释"}}
    ]
  }},
  "index": [
    {{"time_seconds": 225, "time_display": "03:45", "label": "知识点标题", "detail": "一句话说明这个知识点"}}
  ],
  "summary": {{
    "text": "完整的 Markdown 格式总结（包含核心主题、关键要点、详细分析、结论等章节）",
    "cards": [
      {{"question": "复习问题", "answer": "简明答案", "difficulty": 3, "bloom_level": "understand"}}
    ],
    "post_quiz": [
      {{"question": "视频内容回忆题", "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"], "answer": "B", "explanation": "简短解释"}}
    ],
    "weak_points": ["值得深入学习的知识点1", "知识点2"]
  }}
}}
```

要求：
- preview.overview：只给框架，不给核心解答
- preview.questions：3-5 个引导性问题，让观众带着问题去看
- preview.pre_quiz：3-5 道前置知识选择题，不考视频内容
- index：5-20 个关键知识点，按时间顺序排列，time_seconds 是秒数
- summary.text：完整的结构化总结，用 Markdown 格式
- summary.cards：5-8 组复习卡片，覆盖视频核心知识
- summary.post_quiz：3-5 道选择题，考察对视频内容的理解
- summary.weak_points：1-3 个值得深入学习的点

{detail_instruction}
{citation_instruction}

[转录文本]
{transcript}""",
    "en": """You are a video learning assistant. Based on the following video transcript, generate three structured learning materials.

Return strictly the following JSON format, no other content:

```json
{{
  "preview": {{
    "overview": "2-3 sentence overview of the video topic and scope, do not reveal core answers",
    "questions": ["Core question 1: viewer watches with this question in mind", "Core question 2", "Core question 3"],
    "pre_quiz": [
      {{"question": "Prerequisite knowledge question", "options": ["A. Option 1", "B. Option 2", "C. Option 3", "D. Option 4"], "answer": "A", "explanation": "Brief explanation"}}
    ]
  }},
  "index": [
    {{"time_seconds": 225, "time_display": "03:45", "label": "Knowledge point title", "detail": "One-sentence description"}}
  ],
  "summary": {{
    "text": "Full Markdown-formatted summary (with sections for core topic, key points, detailed analysis, conclusion, etc.)",
    "cards": [
      {{"question": "Review question", "answer": "Concise answer", "difficulty": 3, "bloom_level": "understand"}}
    ],
    "post_quiz": [
      {{"question": "Video content recall question", "options": ["A. Option 1", "B. Option 2", "C. Option 3", "D. Option 4"], "answer": "B", "explanation": "Brief explanation"}}
    ],
    "weak_points": ["Knowledge point worth deeper study 1", "Point 2"]
  }}
}}
```

Requirements:
- preview.overview: give framework only, no core answers
- preview.questions: 3-5 guiding questions for the viewer
- preview.pre_quiz: 3-5 prerequisite multiple-choice questions, not about video content
- index: 5-20 key knowledge points in chronological order, time_seconds in seconds
- summary.text: full structured summary in Markdown format
- summary.cards: 5-8 review cards covering core video knowledge
- summary.post_quiz: 3-5 multiple-choice questions testing video comprehension
- summary.weak_points: 1-3 points worth deeper study

{detail_instruction}
{citation_instruction}

[Transcript]
{transcript}""",
}


def get_three_stage_prompt(lang: str = "zh", detail: str = "normal", has_segments: bool = False) -> str:
    """Get the three-stage learning prompt (preview + index + summary)."""
    prompt = THREE_STAGE_PROMPT.get(lang, THREE_STAGE_PROMPT["zh"])
    # Detail instruction
    detail_map = {
        "brief": {"zh": "summary.text 控制在 500 字以内，index 不超过 10 条。", "en": "summary.text under 500 words, index no more than 10 entries."},
        "normal": {"zh": "", "en": ""},
        "detailed": {"zh": "summary.text 请详尽展开，包含具体例子和数据引用。", "en": "summary.text should be thorough with specific examples and data references."},
    }
    detail_instr = detail_map.get(detail, detail_map["normal"]).get(lang, "")
    # Citation instruction
    citation = CITATION_INSTRUCTION.get(lang, CITATION_INSTRUCTION["zh"]) if has_segments else ""
    return prompt.format(transcript="{transcript}", detail_instruction=detail_instr, citation_instruction=citation)


# ============================================================
# Stage 3: Question generation
# ============================================================

QUESTION_GENERATION_PROMPT = {
    "zh": """你是一个学习评估专家。根据以下视频总结和转录文本，生成 15-20 道不同类型的复习题。

要求题型分布：
__QUESTION_TYPES__

每道题必须包含以下字段：
- id: 唯一标识（简短字符串）
- type: 题型（__TYPE_LIST__）
- difficulty: 难度 1-5
- bloom_level: 认知层次（remember/understand/apply/analyze/evaluate/create）
- source_refs: 来源转录段落 ID 列表（如 ["S3", "S5-S8"]）

各题型扩展字段：
- qa: {"question": "...", "answer": "..."}
- true_false: {"statement": "...", "correct": true/false, "explanation": "..."}
- choice: {"question": "...", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "..."}
- fill_blank: {"template": "___是___的关键", "blanks": [{"position": 0, "answer": "关键词"}]}
- sequencing: {"items": ["步骤1", "步骤2", "步骤3"], "correct_order": [0, 1, 2]}
- matching: {"pairs": [{"left": "概念A", "right": "定义A"}, {"left": "概念B", "right": "定义B"}]}
- code: {"context": "def func():\\n    ...", "missing_code": "关键代码", "answer": "答案代码", "language": "python"}
- scenario: {"scenario": "场景描述", "question": "问题", "sample_answer": "参考答案", "key_points": ["要点1", "要点2"]}
- explain: {"concept": "概念名", "prompt": "请用自己的话解释...", "evaluation_criteria": ["标准1", "标准2"]}
- comparison: {"subjects": ["概念A", "概念B"], "question": "比较异同", "answer": "对比分析"}

只返回 JSON 数组，不要其他内容。

[视频总结]
__SUMMARY__

[转录文本片段]
__TRANSCRIPT__""",
    "en": """You are a learning assessment expert. Based on the following video summary and transcript, generate 15-20 review questions of various types.

Question type distribution:
__QUESTION_TYPES__

Each question must include:
- id: unique identifier (short string)
- type: question type (__TYPE_LIST__)
- difficulty: 1-5
- bloom_level: cognitive level (remember/understand/apply/analyze/evaluate/create)
- source_refs: source transcript segment IDs (e.g., ["S3", "S5-S8"])

Type-specific fields:
- qa: {"question": "...", "answer": "..."}
- true_false: {"statement": "...", "correct": true/false, "explanation": "..."}
- choice: {"question": "...", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "..."}
- fill_blank: {"template": "___is the key to___", "blanks": [{"position": 0, "answer": "keyword"}]}
- sequencing: {"items": ["Step 1", "Step 2", "Step 3"], "correct_order": [0, 1, 2]}
- matching: {"pairs": [{"left": "Concept A", "right": "Definition A"}, {"left": "Concept B", "right": "Definition B"}]}
- code: {"context": "def func():\\n    ...", "missing_code": "key code", "answer": "answer code", "language": "python"}
- scenario: {"scenario": "description", "question": "question", "sample_answer": "reference answer", "key_points": ["point1", "point2"]}
- explain: {"concept": "concept name", "prompt": "Explain in your own words...", "evaluation_criteria": ["criterion1", "criterion2"]}
- comparison: {"subjects": ["Concept A", "Concept B"], "question": "Compare and contrast", "answer": "analysis"}

Return JSON array only, no other content.

[Video Summary]
__SUMMARY__

[Transcript Excerpt]
__TRANSCRIPT__""",
}

QUESTION_TYPE_DISTRIBUTION = {
    "tutorial": {
        "zh": "填空题 4-5 道、代码补全 2-3 道、排序题 2-3 道、场景题 2-3 道、Q&A 3-4 道",
        "en": "4-5 fill_blank, 2-3 code, 2-3 sequencing, 2-3 scenario, 3-4 qa",
    },
    "tech_talk": {
        "zh": "选择题 4-5 道、对比题 2-3 道、解释题 3-4 道、判断题 2-3 道、Q&A 2-3 道",
        "en": "4-5 choice, 2-3 comparison, 3-4 explain, 2-3 true_false, 2-3 qa",
    },
    "demo": {
        "zh": "排序题 3-4 道、场景题 3-4 道、填空题 3-4 道、Q&A 3-4 道",
        "en": "3-4 sequencing, 3-4 scenario, 3-4 fill_blank, 3-4 qa",
    },
    "review": {
        "zh": "对比题 4-5 道、选择题 3-4 道、场景题 2-3 道、Q&A 3-4 道",
        "en": "4-5 comparison, 3-4 choice, 2-3 scenario, 3-4 qa",
    },
    "news": {
        "zh": "判断题 4-5 道、选择题 3-4 道、解释题 2-3 道、Q&A 3-4 道",
        "en": "4-5 true_false, 3-4 choice, 2-3 explain, 3-4 qa",
    },
    "vlog": {
        "zh": "Q&A 5-6 道、判断题 3-4 道、解释题 3-4 道",
        "en": "5-6 qa, 3-4 true_false, 3-4 explain",
    },
    "general": {
        "zh": "选择题 4-5 道、填空题 3-4 道、解释题 3-4 道、Q&A 3-4 道",
        "en": "4-5 choice, 3-4 fill_blank, 3-4 explain, 3-4 qa",
    },
}


def get_question_generation_prompt(content_type: str, lang: str = "zh") -> str:
    """Get the prompt for generating questions from a summary."""
    prompt = QUESTION_GENERATION_PROMPT.get(lang, QUESTION_GENERATION_PROMPT["zh"])
    distribution = QUESTION_TYPE_DISTRIBUTION.get(content_type, QUESTION_TYPE_DISTRIBUTION["general"])
    dist_text = distribution.get(lang, distribution["zh"])
    type_list = "qa, true_false, choice, fill_blank, sequencing, matching, code, scenario, explain, comparison"
    return (prompt
            .replace("__QUESTION_TYPES__", dist_text)
            .replace("__TYPE_LIST__", type_list)
            .replace("__SUMMARY__", "{summary}")
            .replace("__TRANSCRIPT__", "{transcript}"))


# ============================================================
# Stage 4: Multi-source synthesis
# ============================================================

SYNTHESIS_PROMPT = {
    "zh": """你是一个学习整合专家。请根据以下 {n} 个视频的总结和转录片段，生成一份综合学习分析文档。

按以下格式输出：

## 统一理解
整合所有视频的核心知识，形成对这个主题的完整理解。标注各来源 [视频1] [视频2] [视频3]。

## 各视角独特贡献
列出每个视频独特覆盖的内容：
- 视频1 特有: ...
- 视频2 特有: ...
- 视频3 特有: ...

## 共识与分歧
- 三方一致: ...
- 观点分歧: ...（附各自论据）
- 互补之处: ...

## 最佳实践提炼
从所有来源中提炼的最优方法或建议。

## 综合复习卡片
生成 5-8 组跨视频的复习卡片，覆盖需要综合多个来源才能理解的知识点。

**Q1:** （跨视频综合问题）
**A1:** （综合答案）

[各视频总结]
{summaries}

[转录文本片段]
{transcripts}""",
    "en": """You are a learning integration expert. Based on the following {n} video summaries and transcript excerpts, generate a comprehensive learning analysis document.

Output format:

## Unified Understanding
Integrate core knowledge from all videos into a complete understanding of this topic. Cite sources [Video1] [Video2] [Video3].

## Unique Contributions
List what each video uniquely covers:
- Video 1 unique: ...
- Video 2 unique: ...
- Video 3 unique: ...

## Consensus & Disagreement
- All agree: ...
- Disagreements: ... (with evidence from each)
- Complementary: ...

## Best Practices
Optimal approaches or recommendations distilled from all sources.

## Synthesis Review Cards
Generate 5-8 cross-source review cards covering knowledge that requires synthesizing multiple sources.

**Q1:** (cross-source synthesis question)
**A1:** (synthesized answer)

[Video Summaries]
{summaries}

[Transcript Excerpts]
{transcripts}""",
}


def get_synthesis_prompt(lang: str = "zh") -> str:
    return SYNTHESIS_PROMPT.get(lang, SYNTHESIS_PROMPT["zh"])
