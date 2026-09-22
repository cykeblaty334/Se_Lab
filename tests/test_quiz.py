# -*- coding: utf-8 -*-
"""闪卡抽测模块单元测试：文本归一化、片段判分、抽题与记账。"""

import random

import pytest

from src import config
from src.models import KnowledgeItem, QuizResult
from src.quiz import (
    QuizService,
    build_question,
    compact,
    extract_fragments,
    format_result,
    fragment_weight,
    grade_answer,
    loosen,
    normalize,
)

#: 判分基准答案（取自知识库种子中的「隔年增长率」）
EXPECTED = "隔年增长率 R = r1 + r2 + r1*r2，其中 r1、r2 为相邻两年的同比增长率。"


# ------------------------------------------------------------------ 文本归一化
def test_loosen_converts_fullwidth_and_symbols():
    assert loosen("ａｂｃ　１２３") == "abc 123"
    assert loosen("1×2") == "1*2"
    assert loosen("1Ｘ2") == "1*2"
    assert loosen("6÷2") == "6/2"
    assert loosen("A") == "a"


def test_normalize_removes_whitespace():
    assert normalize("隔年增长率  R =  r1") == "隔年增长率r=r1"


def test_compact_keeps_only_cjk_and_alnum():
    assert compact("隔年增长率 R = r1 + r2, 其中") == "隔年增长率rr1r2其中"


def test_extract_fragments_splits_on_separators():
    """空格与标点都要成为切分点，避免片段互相粘连。"""
    assert extract_fragments("隔年增长率 R = r1 + r2") == ["隔年增长率", "r", "r1", "r2"]


def test_extract_fragments_drops_short_cjk_pieces():
    """单个汉字（如「的」）信息量过低，不作为评分片段。"""
    assert "的" not in extract_fragments("甲的效率是乙的 2 倍")


def test_extract_fragments_deduplicates_keep_order():
    """重复出现的 r1 只计一次，否则答案篇幅越长越容易刷分。"""
    fragments = extract_fragments(EXPECTED)
    assert fragments == ["隔年增长率", "r", "r1", "r2", "其中", "为相邻两年的同比增长率"]
    assert len(fragments) == len(set(fragments))


def test_extract_fragments_on_empty_text():
    assert extract_fragments("") == []
    assert extract_fragments("   ") == []


def test_fragment_weight_prefers_formula_tokens():
    assert fragment_weight("r1") == config.QUIZ_WEIGHT_ALNUM
    assert fragment_weight("134") == config.QUIZ_WEIGHT_ALNUM
    assert fragment_weight("隔年增长率") == config.QUIZ_WEIGHT_CJK


# ------------------------------------------------------------------ 自动判分
def test_grade_full_answer_scores_100():
    result = grade_answer(EXPECTED, EXPECTED)
    assert result["score"] == 100.0
    assert result["level"] == "完全正确"
    assert result["passed"] is True
    assert result["missed"] == []


def test_grade_accepts_extra_text_around_answer():
    """答案中包含标准答案全文时同样判满分（允许补充说明）。"""
    result = grade_answer(f"我的回答：{EXPECTED} 补充：注意区分同比与环比。", EXPECTED)
    assert result["score"] == 100.0


def test_grade_formula_only_gets_partial_credit():
    """只写公式骨架、漏掉变量含义：应通过但不满分，并提示遗漏要点。"""
    result = grade_answer("R = r1 + r2 + r1×r2", EXPECTED)
    assert result["passed"] is True
    assert result["level"] == "基本正确"
    assert 0 < result["score"] < 100
    assert "r1" in result["hit"]
    assert "为相邻两年的同比增长率" in result["missed"]


def test_grade_ignores_fullwidth_and_symbol_variance():
    """全角符号与 ×/*/x 写法差异不应影响成绩。"""
    half = grade_answer("R = r1 + r2 + r1*r2", EXPECTED)["score"]
    full = grade_answer("Ｒ ＝ ｒ１ ＋ ｒ２ ＋ ｒ１ｘｒ２", EXPECTED)["score"]
    assert half == full


def test_grade_wrong_answer_scores_zero():
    result = grade_answer("我不知道", EXPECTED)
    assert result["score"] == 0.0
    assert result["level"] == "需加强"
    assert result["passed"] is False
    assert result["hit"] == []


@pytest.mark.parametrize("raw", ["", "   ", "\n"])
def test_grade_blank_answer_is_marked(raw):
    result = grade_answer(raw, EXPECTED)
    assert result["score"] == 0.0
    assert result["level"] == "未作答"
    assert result["missed"] == extract_fragments(EXPECTED)


#: 用于覆盖四档评级的合成答案：6 个中文片段 + 1 个公式片段，总权重 8
_LEVEL_EXPECTED = "甲甲 乙乙 丙丙 丁丁 戊戊 己己 r1"


@pytest.mark.parametrize(
    "answer,expected_level",
    [
        ("甲甲 乙乙 丙丙 丁丁 戊戊 己己 r1", "完全正确"),  # 命中全部 -> 100
        ("甲甲 乙乙 丙丙 丁丁 戊戊 r1", "完全正确"),  # 7/8 = 87.5
        ("甲甲 乙乙 丙丙 丁丁 戊戊", "基本正确"),  # 5/8 = 62.5
        ("甲甲 乙乙 r1", "部分正确"),  # 4/8 = 50.0
        ("r1", "需加强"),  # 2/8 = 25.0
    ],
)
def test_grade_level_bands(answer, expected_level):
    assert grade_answer(answer, _LEVEL_EXPECTED)["level"] == expected_level


def test_grade_uses_configurable_pass_score():
    answer = "R = r1 + r2 + r1*r2"
    assert grade_answer(answer, EXPECTED, pass_score=50)["passed"] is True
    assert grade_answer(answer, EXPECTED, pass_score=90)["passed"] is False


# ------------------------------------------------------------------ 题目构造
def test_build_question_uses_category_template():
    item = KnowledgeItem(None, "隔年增长率", "公式", EXPECTED, "r1=5% -> 13.4%")
    question = build_question(item)
    assert question.keyword == "隔年增长率"
    assert "计算公式" in question.question
    assert question.expected == EXPECTED
    assert question.example == "r1=5% -> 13.4%"


@pytest.mark.parametrize(
    "category,keyword",
    [("解题技巧", "思路"), ("申论模板", "作答结构"), ("未知分类", "核心要点")],
)
def test_build_question_templates(category, keyword):
    item = KnowledgeItem(None, "某考点", category, "内容内容", "")
    assert keyword in build_question(item).question


def test_format_result_shows_missed_points():
    item = KnowledgeItem(None, "隔年增长率", "公式", EXPECTED, "示例文本")
    result = QuizResult(
        question=build_question(item),
        answer="R = r1",
        score=22.2,
        passed=False,
        level="需加强",
        hit_fragments=["r1"],
        missed_fragments=["隔年增长率", "为相邻两年的同比增长率"],
    )
    text = format_result(result)
    assert "需加强" in text
    assert "标准答案" in text
    assert "遗漏要点：隔年增长率" in text
    assert "示例：示例文本" in text


def test_format_result_can_hide_expected():
    item = KnowledgeItem(None, "隔年增长率", "公式", EXPECTED, "")
    result = QuizResult(build_question(item), EXPECTED, 100.0, True, "完全正确", [], [])
    assert "标准答案" not in format_result(result, show_expected=False)


# ------------------------------------------------------------------ 抽题
def test_draw_returns_requested_count_without_duplicates(seeded_db):
    questions = QuizService(seeded_db).draw(count=4, rng=random.Random(7))
    assert len(questions) == 4
    assert len({item.keyword for item in questions}) == 4


def test_draw_caps_count_at_pool_size(seeded_db):
    """题量超过知识库条目数时按库存量返回，不报错。"""
    total = len(seeded_db.list_knowledge())
    questions = QuizService(seeded_db).draw(count=total + 50, rng=random.Random(1))
    assert len(questions) == total


def test_draw_filters_by_category(seeded_db):
    questions = QuizService(seeded_db).draw(count=3, category="申论模板", rng=random.Random(2))
    assert all(item.category == "申论模板" for item in questions)


def test_draw_raises_on_empty_pool(db):
    with pytest.raises(ValueError, match="知识库为空"):
        QuizService(db).draw(count=3)


def test_draw_is_reproducible_with_seed(seeded_db):
    first = [item.keyword for item in QuizService(seeded_db).draw(count=3, rng=random.Random(9))]
    second = [item.keyword for item in QuizService(seeded_db).draw(count=3, rng=random.Random(9))]
    assert first == second


def test_pool_skips_items_without_content(seeded_db):
    seeded_db.add_knowledge("空条目", "公式", "")
    keywords = {item.keyword for item in QuizService(seeded_db).pool()}
    assert "空条目" not in keywords


# ------------------------------------------------------------------ 判分记账
def test_submit_writes_quiz_log(seeded_db):
    service = QuizService(seeded_db)
    question = service.draw(count=1, rng=random.Random(3))[0]
    result = service.submit(question, question.expected)
    assert result.passed is True
    stats = seeded_db.quiz_stats()
    assert stats["attempts"] == 1
    assert stats["passed"] == 1
    assert stats["avg_score"] == 100.0
    assert stats["pass_rate"] == 100.0


def test_submit_logs_failure(seeded_db):
    service = QuizService(seeded_db)
    question = service.draw(count=1, rng=random.Random(3))[0]
    service.submit(question, "完全不会")
    stats = seeded_db.quiz_stats()
    assert stats["attempts"] == 1
    assert stats["passed"] == 0
    assert stats["avg_score"] == 0.0


def test_quiz_stats_without_records(seeded_db):
    stats = seeded_db.quiz_stats()
    assert stats == {"attempts": 0, "passed": 0, "avg_score": 0.0, "pass_rate": 0.0}


def test_quiz_weak_keywords_ranks_lowest_first(seeded_db):
    db = seeded_db
    db.add_quiz_log("隔年增长率", "公式", "bad", 10.0, False)
    db.add_quiz_log("工程问题", "公式", "good", 90.0, True)
    weak = db.quiz_weak_keywords(limit=2)
    assert weak[0]["keyword"] == "隔年增长率"


def test_run_session_with_scripted_answers(seeded_db):
    """用脚本化输入走完一次抽测，验证输出与落库。"""
    service = QuizService(seeded_db)
    printed = []
    questions = service.draw(count=2, rng=random.Random(5))
    answers = iter([item.expected for item in questions])
    results = service.run_session(
        count=2,
        input_func=lambda prompt="": next(answers),
        output_func=printed.append,
        rng=random.Random(5),
    )
    assert len(results) == 2
    assert all(item.passed for item in results)
    assert any("本次抽测结果" in line for line in printed)
    assert seeded_db.quiz_stats()["attempts"] == 2


def test_run_session_aborts_on_quit(seeded_db):
    service = QuizService(seeded_db)
    printed = []
    results = service.run_session(
        count=3,
        input_func=lambda prompt="": "q",
        output_func=printed.append,
        rng=random.Random(6),
    )
    assert results == []
    assert any("已结束本次抽测" in line for line in printed)
    assert seeded_db.quiz_stats()["attempts"] == 0


def test_run_session_handles_keyboard_interrupt(seeded_db):
    """用户在答题时按 Ctrl+C 只结束抽测，不抛出异常。"""

    def _raise(prompt=""):
        raise KeyboardInterrupt

    printed = []
    results = QuizService(seeded_db).run_session(
        count=2, input_func=_raise, output_func=printed.append, rng=random.Random(8)
    )
    assert results == []
    assert any("提前结束" in line for line in printed)


def test_summary_text_lists_weak_keywords():
    item = KnowledgeItem(None, "行程问题", "公式", "相遇：路程和 = 速度和 × 时间", "示例")
    question = build_question(item)
    results = [
        QuizResult(question, "不会", 0.0, False, "需加强", [], ["路程和"]),
        QuizResult(question, question.expected, 100.0, True, "完全正确", ["路程和"], []),
    ]
    text = QuizService.summary_text(results)
    assert "作答题数：2" in text
    assert "需要巩固：行程问题" in text
    assert "平均得分：50.0" in text


def test_summary_text_without_results():
    assert "没有有效作答记录" in QuizService.summary_text([])


def test_summary_text_all_passed():
    item = KnowledgeItem(None, "行程问题", "公式", "相遇：路程和 = 速度和 × 时间", "")
    question = build_question(item)
    results = [QuizResult(question, question.expected, 100.0, True, "完全正确", [], [])]
    assert "全部通过" in QuizService.summary_text(results)


def test_stats_text_hint_when_empty(seeded_db):
    assert "暂无闪卡抽测记录" in QuizService(seeded_db).stats_text()


def test_stats_text_reports_history(seeded_db):
    seeded_db.add_quiz_log("隔年增长率", "公式", "答案", 80.0, True)
    text = QuizService(seeded_db).stats_text()
    assert "通过率 100.0%" in text
    assert "隔年增长率" in text
