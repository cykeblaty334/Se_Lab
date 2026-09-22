# -*- coding: utf-8 -*-
"""弱项诊断模块单元测试：算法边界、权重合成与报告输出。"""

import pytest

from src import config
from src.analyzer import Analyzer, accuracy_score, compute_score, efficiency_score, stability_score


def test_accuracy_score():
    assert accuracy_score(0, 0) == 0.0
    assert accuracy_score(15, 20) == pytest.approx(0.75)


def test_efficiency_score_boundary():
    # 单题 45 秒为满分基准
    assert efficiency_score(45.0) == pytest.approx(1.0)
    assert efficiency_score(22.5) == pytest.approx(1.0)  # 上限截断为 1
    assert efficiency_score(90.0) == pytest.approx(0.5)
    assert efficiency_score(0) == 1.0  # 避免除零


def test_stability_score():
    # 成绩完全稳定 -> 稳定性满分
    assert stability_score([0.8, 0.8, 0.8]) == (1.0, 0.0)
    # 样本不足时不做波动惩罚
    assert stability_score([0.5]) == (1.0, 0.0)
    # 波动越大，稳定性越低
    low_var, _ = stability_score([0.8, 0.79, 0.81])
    high_var, std = stability_score([0.9, 0.3, 0.9])
    assert low_var > high_var
    assert std > 0


def test_compute_score_weights_sum_to_one():
    weight_sum = (
        config.WEIGHT_ACCURACY
        + config.WEIGHT_EFFICIENCY
        + config.WEIGHT_STABILITY
    )
    assert weight_sum == pytest.approx(1.0)
    assert compute_score(1.0, 1.0, 1.0) == 100.0
    assert compute_score(0.0, 0.0, 0.0) == 0.0
    assert compute_score(0.5, 0.5, 0.5) == 50.0


def test_diagnose_empty_database_returns_all_modules(db):
    """无任何练习数据时，仍应返回五大模块（雷达图五轴完整）。"""
    db.seed()
    diagnoses = Analyzer(db).diagnose_modules()
    assert len(diagnoses) == 5
    assert all(item.records == 0 for item in diagnoses)
    assert all(item.is_weak is False for item in diagnoses)


def test_diagnose_sorted_by_score_ascending(sample_records):
    """诊断结果按综合得分升序，弱项排在最前。"""
    db, _ = sample_records
    diagnoses = Analyzer(db).diagnose_modules()
    scores = [item.final_score for item in diagnoses]
    assert scores == sorted(scores)


def test_diagnose_marks_weak_module(sample_records):
    """数量关系正确率 40% 且单题耗时高，应被判为弱项。"""
    db, _ = sample_records
    diagnoses = {item.module_name: item for item in Analyzer(db).diagnose_modules()}
    math = diagnoses["数量关系"]
    assert math.is_weak is True
    assert math.accuracy == pytest.approx(12 / 30, rel=1e-3)
    assert math.seconds_per_question == pytest.approx(2600 / 30, rel=1e-3)
    assert "行程问题（40.0%）" in math.weak_topics
    assert "工程问题（40.0%）" in math.weak_topics

    chinese = diagnoses["言语理解与表达"]
    assert chinese.is_weak is False
    assert chinese.final_score > math.final_score


def test_unstudied_modules_rank_last(seeded_db):
    """回归用例：从未练习的模块不得因 "0 正确率 + 满分效率" 被排到弱项之前。

    缺陷现象：未练习模块综合得分为 40 分，排名高于真实弱项模块。
    修复后：未练习模块记 0 分、不参与评分，并统一排在结果末尾。
    """
    module = seeded_db.get_module_by_name("数量关系")
    seeded_db.add_record(
        record_date="2026-09-19",
        module_id=module.id,
        total_questions=20,
        correct_questions=4,  # 正确率 20%，真实弱项
        duration_seconds=1800,
    )
    diagnoses = Analyzer(seeded_db).diagnose_modules()
    assert diagnoses[0].module_name == "数量关系"
    assert diagnoses[0].is_weak is True

    unstudied = [item for item in diagnoses if item.records == 0]
    assert len(unstudied) == 4
    assert all(item.final_score == 0.0 for item in unstudied)
    assert all(item.is_weak is False for item in unstudied)
    # 未练习模块全部排在已练习模块之后
    assert diagnoses[-1].records == 0

    report = Analyzer(seeded_db).text_report()
    assert "尚未开始练习" in report


def test_diagnose_respects_date_range(sample_records):
    """日期区间过滤应生效。"""
    db, _ = sample_records
    analyzer = Analyzer(db)
    scoped = {item.module_name: item for item in analyzer.diagnose_modules(start_date="2026-09-03")}
    assert scoped["言语理解与表达"].records == 0
    assert scoped["数量关系"].records == 2


def test_overall_statistics(sample_records):
    """整体统计与样本数据一致。"""
    db, _ = sample_records
    overall = Analyzer(db).overall()
    assert overall["records"] == 6
    assert overall["total_questions"] == 110
    assert overall["correct_questions"] == 64
    assert overall["accuracy"] == pytest.approx(58.18, rel=1e-2)
    assert overall["covered_modules"] == 5
    assert overall["total_modules"] == 5


def test_trend_series(sample_records):
    """趋势数据按日期升序、字段完整。"""
    db, _ = sample_records
    trend = Analyzer(db).trend(days=30)
    dates = [item[0] for item in trend]
    assert dates == sorted(dates)
    assert len(trend) == 6
    date_str, accuracy, per_question = trend[0]
    assert date_str == "2026-09-01"
    assert accuracy == pytest.approx(75.0)
    assert per_question == pytest.approx(40.0)


def test_slow_modules_detection(sample_records):
    """单题耗时超过阈值的模块应被列入效率预警。"""
    db, _ = sample_records
    slow = {item.module_name for item in Analyzer(db).slow_modules()}
    assert "数量关系" in slow  # 2600s / 30 题 ≈ 86.7s
    assert "常识判断" not in slow  # 600s / 20 题 = 30s


def test_ready_for_radar_threshold(seeded_db):
    """记录数不足 5 条时提示数据不足以生成雷达图。"""
    analyzer = Analyzer(seeded_db)
    assert analyzer.ready_for_radar() is False
    module = seeded_db.get_module_by_name("资料分析")
    for day in range(1, 6):
        seeded_db.add_record(
            record_date=f"2026-09-0{day}",
            module_id=module.id,
            total_questions=10,
            correct_questions=6,
            duration_seconds=600,
        )
    assert analyzer.ready_for_radar() is True


def test_text_report_without_data(db):
    db.seed()
    assert "暂无练习记录" in Analyzer(db).text_report()


def test_text_report_contains_weak_section(sample_records):
    db, _ = sample_records
    report = Analyzer(db).text_report()
    assert "CEATS 弱项诊断报告" in report
    assert "薄弱环节定位" in report
    assert "数量关系" in report
    assert "效率预警" in report


def test_text_report_no_weak_module(seeded_db):
    """全部模块成绩优秀时，报告应给出正向反馈。"""
    modules = seeded_db.list_modules()
    for module in modules:
        seeded_db.add_record(
            record_date="2026-09-20",
            module_id=module.id,
            total_questions=20,
            correct_questions=19,
            duration_seconds=400,
        )
    report = Analyzer(seeded_db).text_report()
    assert "暂未发现明显弱项" in report
