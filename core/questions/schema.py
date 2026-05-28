"""Question type schema for active learning system.

Unified schema with base fields and type-specific extensions.
"""

# Question type constants
TYPE_QA = "qa"                    # Q&A flashcard (existing)
TYPE_TRUE_FALSE = "true_false"   # 判断题
TYPE_MULTIPLE_CHOICE = "choice"  # 选择题
TYPE_FILL_BLANK = "fill_blank"   # 填空题
TYPE_SEQUENCING = "sequencing"   # 排序题
TYPE_MATCHING = "matching"       # 配对题
TYPE_CODE_COMPLETION = "code"    # 代码补全
TYPE_SCENARIO = "scenario"       # 场景题
TYPE_EXPLAIN = "explain"         # 用自己的话解释
TYPE_COMPARISON = "comparison"   # 对比题

ALL_TYPES = {
    TYPE_QA, TYPE_TRUE_FALSE, TYPE_MULTIPLE_CHOICE, TYPE_FILL_BLANK,
    TYPE_SEQUENCING, TYPE_MATCHING, TYPE_CODE_COMPLETION, TYPE_SCENARIO,
    TYPE_EXPLAIN, TYPE_COMPARISON,
}

# Bloom's taxonomy levels
BLOOM_LEVELS = {
    "remember": 1,    # 识别、回忆
    "understand": 2,  # 理解、解释
    "apply": 3,       # 应用、执行
    "analyze": 4,     # 分析、区分
    "evaluate": 5,    # 评价、判断
    "create": 6,      # 创造、设计
}

# Content type → preferred question type mapping
CONTENT_TYPE_QUESTION_MAP = {
    "tutorial": [TYPE_FILL_BLANK, TYPE_CODE_COMPLETION, TYPE_SEQUENCING, TYPE_SCENARIO, TYPE_QA],
    "tech_talk": [TYPE_MULTIPLE_CHOICE, TYPE_COMPARISON, TYPE_EXPLAIN, TYPE_TRUE_FALSE, TYPE_QA],
    "demo": [TYPE_SEQUENCING, TYPE_SCENARIO, TYPE_FILL_BLANK, TYPE_QA],
    "review": [TYPE_COMPARISON, TYPE_MULTIPLE_CHOICE, TYPE_SCENARIO, TYPE_QA],
    "news": [TYPE_TRUE_FALSE, TYPE_MULTIPLE_CHOICE, TYPE_EXPLAIN, TYPE_QA],
    "vlog": [TYPE_QA, TYPE_TRUE_FALSE, TYPE_EXPLAIN],
    "general": [TYPE_MULTIPLE_CHOICE, TYPE_FILL_BLANK, TYPE_EXPLAIN, TYPE_QA],
}


def validate_question(q: dict) -> bool:
    """Validate a question object has required base fields."""
    required = {"id", "type", "difficulty", "bloom_level", "source_refs"}
    return required.issubset(q.keys()) and q["type"] in ALL_TYPES
