# -*- coding: utf-8 -*-
"""备考计划模块单元测试：倒计时解析、黄金比例换算与目标拆解表。"""

from datetime import date, timedelta

import pytest

from src import config
from src.planner import (
    PlanError,
    PlanService,
    countdown_phrase,
    days_remaining,
    decompose_target,
    judge_gap,
    parse_exam_date,
    parse_score,
    target_ratio,
)

TODAY = date(2026, 9, 21)


# ------------------------------------------------------------------ 日期解析
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2027-11-28", "2027-11-28"),
        ("2027/11/28", "2027-11-28"),
        ("2027.11.28", "2027-11-28"),
        ("2027-1-8", "2027-01-08"),
    ],
)
def test_parse_exam_date_accepts_common_formats(raw, expected):
    assert parse_exam_date(raw, TODAY) == expected


def test_parse_exam_date_accepts_today():
    assert parse_exam_date("2026-09-21", TODAY) == "2026-09-21"


@pytest.mark.parametrize("raw", ["", "   ", "2027年11月", "11-28", "abc"])
def test_parse_exam_date_rejects_bad_format(raw):
    with pytest.raises(PlanError, match="不能为空|格式非法"):
        parse_exam_date(raw, TODAY)


def test_parse_exam_date_rejects_nonexistent_day():
    with pytest.raises(PlanError, match="日期不存在"):
        parse_exam_date("2027-02-30", TODAY)


def test_parse_exam_date_rejects_past_date():
    """考试日期必须是未来，避免倒计时出现无意义的负数。"""
    with pytest.raises(PlanError, match="不能早于今天"):
        parse_exam_date("2025-11-30", TODAY)


# ------------------------------------------------------------------ 分数解析
def test_parse_score_accepts_int_and_float():
    assert parse_score("135", "目标总分") == 135.0
    assert parse_score(" 135.5 ", "目标总分") == 135.5


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
def test_parse_score_rejects_invalid(raw):
    with pytest.raises(PlanError, match="必须是数字|必须大于 0"):
        parse_score(raw, "目标总分")


def test_parse_score_rejects_over_upper_bound():
    with pytest.raises(PlanError, match="不应超过"):
        parse_score("260", "目标总分")


@pytest.mark.parametrize("raw", ["120", "101"])
def test_parse_score_respects_custom_upper_bound(raw):
    with pytest.raises(PlanError, match="不应超过 100"):
        parse_score(raw, "申论预期分", upper=100.0)


# ------------------------------------------------------------------ 倒计时
def test_days_remaining_counts_forward():
    assert days_remaining("2027-11-28", TODAY) == (date(2027, 11, 28) - TODAY).days


def test_days_remaining_is_zero_on_exam_day():
    assert days_remaining("2026-09-21", TODAY) == 0


def test_days_remaining_is_negative_after_exam():
    assert days_remaining("2026-09-01", TODAY) == -20


def test_days_remaining_rejects_bad_date():
    with pytest.raises(PlanError, match="非法"):
        days_remaining("not-a-date", TODAY)


@pytest.mark.parametrize(
    "days,expected",
    [(0, "就是今天，全力冲刺"), (1, "还有 1 天"), (100, "还有 100 天"), (-3, "已过去 3 天")],
)
def test_countdown_phrase(days, expected):
    assert countdown_phrase(days) == expected


# ------------------------------------------------------------------ 黄金比例
def test_target_ratio_matches_golden_ratio_at_base_total():
    """目标总分 = 基准 135 时，结果应等于黄金比例原值。"""
    ratios = {row["module_name"]: row["ratio"] for row in decompose_target(135)}
    assert ratios["言语理解与表达"] == 75.0
    assert ratios["判断推理"] == 75.0
    assert ratios["资料分析"] == 85.0
    assert ratios["数量关系"] == 60.0
    assert ratios["常识判断"] == 55.0


def test_target_ratio_scales_with_target_total():
    assert target_ratio("资料分析", 150) == pytest.approx(94.4, abs=0.05)
    assert target_ratio("数量关系", 120) == pytest.approx(53.3, abs=0.05)


def test_target_ratio_is_clamped():
    """极端目标分不应产生 100% 或 10% 这类不切实际的建议正确率。"""
    assert target_ratio("言语理解与表达", 400) == config.TARGET_RATIO_MAX
    assert target_ratio("常识判断", 5) == config.TARGET_RATIO_MIN


def test_target_ratio_returns_zero_for_unknown_module():
    assert target_ratio("不存在的模块", 135) == 0.0


def test_decompose_target_contains_all_fields():
    rows = decompose_target(135)
    assert len(rows) == len(config.GOLDEN_RATIO)
    first = rows[0]
    assert set(first) == {"module_name", "short", "golden", "ratio", "full_score", "target_score"}
    assert first["short"] == "言语"
    # 建议得分 = 参考满分 × 建议正确率
    assert first["target_score"] == round(first["full_score"] * first["ratio"] / 100, 1)


def test_decompose_target_scores_sum_to_about_full_mark():
    rows = decompose_target(135)
    assert sum(row["full_score"] for row in rows) == pytest.approx(100.0)


def test_decompose_target_accepts_custom_modules():
    rows = decompose_target(135, ["资料分析"])
    assert len(rows) == 1
    assert rows[0]["short"] == "资料"


@pytest.mark.parametrize(
    "current,target,keyword",
    [(None, 75, "暂无数据"), (80, 75, "已达标"), (70, 75, "差 5.0")],
)
def test_judge_gap(current, target, keyword):
    assert keyword in judge_gap(current, target)


# ------------------------------------------------------------------ 服务类
def test_set_plan_persists_and_computes_xingce_target(seeded_db):
    plan = PlanService(seeded_db).set_plan("2027 国考", "2027-11-28", "135", "65")
    assert plan["exam_name"] == "2027 国考"
    assert plan["target_score"] == 135.0
    assert plan["essay_score"] == 65.0
    assert plan["xingce_target"] == 70.0  # 行测必须补上 135 - 65
    assert plan["days_remaining"] == (date(2027, 11, 28) - date.today()).days


def test_set_plan_uses_default_essay_score(seeded_db):
    plan = PlanService(seeded_db).set_plan("2027 国考", "2027-11-28", "135")
    assert plan["essay_score"] == config.DEFAULT_ESSAY_SCORE


def test_set_plan_uses_default_name_when_blank(seeded_db):
    plan = PlanService(seeded_db).set_plan("   ", "2027-11-28", "135")
    assert plan["exam_name"] == config.DEFAULT_EXAM_NAME


def test_set_plan_overwrites_same_exam_name(seeded_db):
    planner = PlanService(seeded_db)
    planner.set_plan("2027 国考", "2027-11-28", "130")
    plan = planner.set_plan("2027 国考", "2027-11-29", "140")
    assert plan["exam_date"] == "2027-11-29"
    assert plan["target_score"] == 140.0
    # 同一考试名称只保留一行（UNIQUE 约束 + ON CONFLICT 更新）
    assert seeded_db.get_exam_plan()["target_score"] == 140.0
    rows = seeded_db.conn.execute("SELECT COUNT(*) AS c FROM exam_plans").fetchone()
    assert rows["c"] == 1


def test_set_plan_rejects_essay_not_lower_than_total(seeded_db):
    """申论预期分高于目标总分说明输入有误，必须拦下。"""
    # 目标 60 分、申论 80 分：80 未触及 100 分上限校验，可命中「应小于目标总分」分支
    with pytest.raises(PlanError, match="应小于目标总分"):
        PlanService(seeded_db).set_plan("2027 国考", "2027-11-28", "60", "80")


def test_current_returns_none_without_plan(seeded_db):
    assert PlanService(seeded_db).current() is None


def test_banner_is_empty_without_plan(seeded_db):
    assert PlanService(seeded_db).banner() == ""


def test_banner_contains_exam_and_days(seeded_db):
    planner = PlanService(seeded_db)
    planner.set_plan("2027 年国家公务员考试", "2027-11-28", "135", "65")
    banner = planner.banner()
    assert "倒计时" in banner
    assert "2027 年国家公务员考试" in banner
    assert "目标 135 分" in banner
    assert "行测需 70 分" in banner


def test_target_table_marks_missing_data(seeded_db):
    PlanService(seeded_db).set_plan("2027 国考", "2027-11-28", "135")
    rows = PlanService(seeded_db).target_table()
    assert all(row["current"] is None for row in rows)
    assert all(row["gap"] == "暂无数据" for row in rows)


def test_target_table_compares_with_actual_accuracy(sample_records):
    """已练习模块应算出真实正确率，并给出与目标正确率的差距。"""
    db, _ = sample_records
    planner = PlanService(db)
    planner.set_plan("2027 国考", "2027-11-28", "135")
    rows = {row["module_name"]: row for row in planner.target_table()}
    assert rows["言语理解与表达"]["current"] == 75.0  # 15/20
    assert rows["言语理解与表达"]["gap"] == "已达标（+0.0%）"
    assert rows["数量关系"]["current"] == 40.0  # 12/30
    assert "差" in rows["数量关系"]["gap"]


def test_target_table_accepts_explicit_total(sample_records):
    db, _ = sample_records
    rows = PlanService(db).target_table(150)
    assert rows[0]["ratio"] == pytest.approx(83.3, abs=0.05)


def test_estimated_xingce_score(sample_records):
    db, _ = sample_records
    planner = PlanService(db)
    planner.set_plan("2027 国考", "2027-11-28", "135")
    score = planner.estimated_xingce_score()
    assert 60 <= score <= 100


def test_summary_lines_without_plan_gives_guidance(seeded_db):
    text = "\n".join(PlanService(seeded_db).summary_lines())
    assert "尚未设置备考计划" in text
    assert "plan set" in text


def test_summary_lines_renders_table(sample_records):
    db, _ = sample_records
    planner = PlanService(db)
    planner.set_plan("2027 年国家公务员考试", "2027-11-28", "135", "65")
    text = "\n".join(planner.summary_lines())
    assert "CEATS 备考计划" in text
    assert "黄金比例" in text
    assert "资料" in text and "85.0%" in text
    assert "行测可得约" in text
    assert "GOLDEN_RATIO" in text


def test_summary_lines_sprint_hint_near_exam(seeded_db):
    """考试临近时应给出冲刺期提示。"""
    planner = PlanService(seeded_db)
    soon = (date.today() + timedelta(days=10)).isoformat()
    planner.set_plan("省考", soon, "135")
    assert "冲刺期" in "\n".join(planner.summary_lines())


def test_summary_lines_without_table(seeded_db):
    planner = PlanService(seeded_db)
    planner.set_plan("2027 国考", "2027-11-28", "135")
    text = "\n".join(planner.summary_lines(with_table=False))
    assert "黄金比例" not in text
    assert "剩余时间" in text
