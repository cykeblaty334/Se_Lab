# -*- coding: utf-8 -*-
"""集成测试：聚焦模块间的接口交互，验证数据在分层之间正确传递。

对应实验 10 的集成测试要求，用例覆盖：
* TC-INT-001  录入 -> 持久化 -> 聚合 -> 诊断回复 的端到端链路；
* TC-INT-002  爬虫 -> 入库 -> 检索 的跨模块交互；
* TC-INT-003  空数据 / 非法数据等边界场景下各层不崩溃；
* TC-INT-004  CLI 命令与服务层、可视化层的接口契约；
* TC-INT-005  自定义考点 -> 考点聚合 -> 弱项定位 的数据一致性；
* TC-INT-006  重复初始化（多次启动程序）的数据保持性；
* TC-INT-007  备考计划 -> 目标拆解 -> 报告导出 的链路一致性（迭代三）；
* TC-INT-008  闪卡抽测 -> 抽测日志 -> 复盘清单 的跨模块引用（迭代三）；
* TC-INT-009  错题标记 -> 考点聚合 -> 复盘清单 -> 报告 的端到端一致（迭代三）；
* TC-INT-010  CLI 导出与数据库备份还原的端到端闭环（迭代三）。
"""

import argparse
import sqlite3
from pathlib import Path

import pytest

from src import config
from src.analyzer import Analyzer
from src.database import Database
from src.knowledge import KnowledgeBase
from src.main import (
    cmd_backup,
    cmd_chart,
    cmd_export,
    cmd_init,
    cmd_kb,
    cmd_list,
    cmd_record,
    cmd_report,
    cmd_restore,
)
from src.planner import PlanService
from src.quiz import QuizService, build_question
from src.recorder import RecordService, build_feedback
from src.reviewer import ReviewService
from src.scraper import AnnouncementScraper, scrape_and_store


@pytest.fixture()
def cli_isolated(tmp_path, monkeypatch):
    """把数据库、图表、导出与备份目录全部隔离到临时目录。

    迭代三的集成用例会走到 CLI 层，而 cmd_export / cmd_backup 读取的是
    ``config.DB_PATH``（不是测试自己开的那个连接），因此必须把配置里的
    路径一并重定向，否则用例会误读到仓库里的真实数据库。
    """
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "ceats.db")
    monkeypatch.setattr(config, "CHART_DIR", tmp_path / "charts")
    monkeypatch.setattr(config, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    return tmp_path


# ---------------------------------------------------------------- TC-INT-001
def test_tc_int_001_record_to_diagnosis_pipeline(seeded_db):
    """录入 5 条数据后，诊断报告能正确反映最新写入的内容。"""
    service = RecordService(seeded_db)
    assert seeded_db.count_records() == 0
    assert "暂无练习记录" in Analyzer(seeded_db).text_report()

    dataset = [
        ("资料分析", "20", "18", "10:00"),
        ("资料分析", "20", "17", "11:00"),
        ("数量关系", "20", "6", "30:00"),
        ("数量关系", "10", "3", "16:00"),
        ("言语理解与表达", "20", "16", "12:00"),
    ]
    for module_raw, total, correct, duration in dataset:
        record = service.submit(module_raw, total, correct, duration)
        assert "已保存" in build_feedback(record)
    assert seeded_db.count_records() == 5

    analyzer = Analyzer(seeded_db)
    diagnoses = {item.module_name: item for item in analyzer.diagnose_modules()}
    # 数量关系正确率与耗时均最差，必须被判为弱项并排在首位
    assert diagnoses["数量关系"].is_weak is True
    assert analyzer.diagnose_modules()[0].module_name == "数量关系"
    assert diagnoses["资料分析"].is_weak is False

    report = analyzer.text_report()
    assert "数量关系" in report
    assert "薄弱环节定位" in report
    assert analyzer.ready_for_radar() is True


# ---------------------------------------------------------------- TC-INT-002
def test_tc_int_002_scraper_to_knowledge_interaction(seeded_db):
    """爬虫模块与数据层的接口交互：抓取结果入库存量、可检索且可去重。"""
    scraper = AnnouncementScraper(retries=0)
    scraper.session.get = lambda url, timeout=None: type(
        "R",
        (),
        {
            "text": '<a href="/a.html">关于2026年度考试录用公务员报名公告</a>',
            "status_code": 200,
            "encoding": "utf-8",
            "apparent_encoding": "utf-8",
            "raise_for_status": lambda self=None: None,
        },
    )()

    result = scrape_and_store(seeded_db, keywords=["报名"], scraper=scraper)
    assert result.announcements
    assert seeded_db.count_announcements() > 0
    assert all(item.matched_keyword == "报名" for item in result.announcements)

    kb = KnowledgeBase(seeded_db)
    assert kb.search("隔年增长率")


# ---------------------------------------------------------------- TC-INT-003
def test_tc_int_003_boundary_scenarios_do_not_crash(tmp_path, monkeypatch):
    """边界场景：空数据库、非法输入、不足 5 条记录时链路仍可运行。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "boundary.db")
    monkeypatch.setattr(config, "CHART_DIR", tmp_path / "charts")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    assert cmd_init(argparse.Namespace()) == 0

    db = Database()
    analyzer = Analyzer(db)
    assert "暂无练习记录" in analyzer.text_report()
    assert len(analyzer.diagnose_modules()) == 5  # 雷达图五轴完整
    assert analyzer.trend(days=30) == []

    # 非法输入由服务层拦截，不写入脏数据
    from src.recorder import RecordError

    with pytest.raises(RecordError):
        RecordService(db).submit("数量关系", "abc", "5", "10:00")
    assert db.count_records() == 0

    # 数据不足时图表仍可生成，且给出提示
    assert cmd_chart(argparse.Namespace(days=30)) == 0
    assert (tmp_path / "charts" / "radar.png").exists()
    db.close()


# ---------------------------------------------------------------- TC-INT-004
def test_tc_int_004_cli_commands_contract(tmp_path, monkeypatch, capsys):
    """CLI 层与服务层的接口契约：命令返回码与输出格式。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cli.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CHART_DIR", tmp_path / "charts")

    assert cmd_init(argparse.Namespace()) == 0
    assert cmd_record(
        argparse.Namespace(
            module="判断推理",
            total="20",
            correct="15",
            duration="15:00",
            topic="逻辑判断",
            date="2026-09-10",
            note="",
        )
    ) == 0
    assert "正确率 75.0%" in capsys.readouterr().out

    # 非法录入应返回错误码 1（而不是抛异常退出）
    assert cmd_record(
        argparse.Namespace(
            module="判断推理",
            total="20",
            correct="25",
            duration="15:00",
            topic="",
            date="",
            note="",
        )
    ) == 1

    assert cmd_list(argparse.Namespace(limit=5)) == 0
    assert "判断推理" in capsys.readouterr().out

    assert cmd_report(argparse.Namespace(days=0, start=None, end=None)) == 0
    assert "弱项诊断报告" in capsys.readouterr().out

    assert cmd_kb(argparse.Namespace(keyword="申论", category=None)) == 0
    assert "申论模板" in capsys.readouterr().out

    # 空关键词查询返回错误码，且不崩溃
    assert cmd_kb(argparse.Namespace(keyword="", category="公式")) == 0
    assert cmd_kb(argparse.Namespace(keyword="不存在的关键词", category=None)) == 0


# ---------------------------------------------------------------- TC-INT-005
def test_tc_int_005_custom_topic_flows_into_diagnosis(seeded_db):
    """自定义考点经由服务层入库后，能被考点聚合与弱项定位正确识别。"""
    service = RecordService(seeded_db)
    for _ in range(3):
        service.submit(
            module_raw="判断推理",
            total_raw="10",
            correct_raw="2",
            duration_raw="12:00",
            topic_raw="朴素逻辑专项",
        )
    assert seeded_db.get_topic_by_name(
        seeded_db.get_module_by_name("判断推理").id, "朴素逻辑专项"
    ) is not None

    topics = {
        row["topic_name"]: row
        for row in seeded_db.topic_aggregate()
    }
    assert topics["朴素逻辑专项"]["total_questions"] == 30
    assert topics["朴素逻辑专项"]["correct_questions"] == 6

    diagnoses = {item.module_name: item for item in Analyzer(seeded_db).diagnose_modules()}
    assert any("朴素逻辑专项" in topic for topic in diagnoses["判断推理"].weak_topics)


# ---------------------------------------------------------------- 稳定性
def test_repeated_initialization_keeps_data(tmp_path, monkeypatch):
    """多次启动程序（重复 init）不应清空历史数据。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "persist.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    cmd_init(argparse.Namespace())
    cmd_record(
        argparse.Namespace(
            module="资料分析",
            total="20",
            correct="18",
            duration="18:00",
            topic="",
            date="",
            note="",
        )
    )
    cmd_init(argparse.Namespace())

    db = Database()
    assert db.count_records() == 1
    db.close()


# ---------------------------------------------------------------- TC-INT-007
def test_tc_int_007_plan_flows_into_target_table_and_report(cli_isolated):
    """备考计划经数据层落到目标拆解表，并随导出的 Markdown 报告一起输出。"""
    assert cmd_init(argparse.Namespace()) == 0
    db = Database()
    planner = PlanService(db)
    assert planner.current() is None

    plan = planner.set_plan("2027 年国家公务员考试", "2027-11-28", "135", "65")
    assert plan["xingce_target"] == 70.0

    # 录入资料分析练习：34/40 = 85%，正好达到该模块的建议目标正确率
    module = db.get_module_by_name("资料分析")
    topic = db.get_topic_by_name(module.id, "增长率")
    for correct, duration in ((16, 800), (18, 700)):
        db.add_record(
            record_date="2026-09-10",
            module_id=module.id,
            topic_id=topic.id,
            total_questions=20,
            correct_questions=correct,
            duration_seconds=duration,
        )

    rows = {row["module_name"]: row for row in planner.target_table(135)}
    assert rows["资料分析"]["current"] == 85.0
    assert rows["资料分析"]["gap"] == "已达标（+0.0%）"
    assert "倒计时" in planner.banner()  # 启动横幅读取同一份计划
    db.close()

    assert cmd_export(argparse.Namespace(format="md", out=None)) == 0
    report = (cli_isolated / "exports" / "2026-国考备考诊断报告.md").read_text(encoding="utf-8")
    assert "考试名称：2027 年国家公务员考试" in report
    assert "资料分析" in report and "85" in report


# ---------------------------------------------------------------- TC-INT-008
def test_tc_int_008_quiz_log_feeds_review_list(seeded_db):
    """闪卡抽测结果写入抽测日志后，统计与复盘清单都能引用同一批数据。"""
    quiz = QuizService(seeded_db)
    card = [item for item in quiz.pool() if item.keyword == "工程问题"][0]

    perfect = quiz.submit(build_question(card), card.content)
    assert perfect.score == 100.0
    failed = quiz.submit(build_question(card), "不知道")
    assert failed.score == 0.0

    stats = quiz.stats()
    assert stats["attempts"] == 2
    assert stats["passed"] == 1
    assert stats["avg_score"] == 50.0

    # 复盘清单读取同一张 quiz_log，提示最弱知识点
    module = seeded_db.get_module_by_name("数量关系")
    topic = seeded_db.get_topic_by_name(module.id, "工程问题")
    seeded_db.add_record(
        record_date="2026-09-15",
        module_id=module.id,
        topic_id=topic.id,
        total_questions=10,
        correct_questions=3,
        duration_seconds=1200,
        is_wrong=True,
    )
    text = ReviewService(seeded_db).format_list()
    assert "闪卡抽测薄弱点" in text
    assert "工程问题" in text


# ---------------------------------------------------------------- TC-INT-009
def test_tc_int_009_wrong_flag_flows_into_review_and_report(cli_isolated):
    """错题标记 -> 考点聚合 -> 复盘清单 -> 导出报告 全链路一致。"""
    assert cmd_init(argparse.Namespace()) == 0
    db = Database()
    module = db.get_module_by_name("数量关系")
    topic = db.get_topic_by_name(module.id, "行程问题")
    for index in range(3):
        db.add_record(
            record_date=f"2026-09-1{index}",
            module_id=module.id,
            topic_id=topic.id,
            total_questions=10,
            correct_questions=3,
            duration_seconds=1200,
            is_wrong=True,
        )

    assert db.count_wrong_records() == 3
    items = ReviewService(db).review_items(days=30, top_n=3)
    assert items[0].topic_name == "行程问题"
    assert items[0].wrong_records == 3
    assert "错题 3 条" in items[0].reason
    total = db.count_records()
    db.close()

    assert cmd_export(argparse.Namespace(format="all", out=None)) == 0
    exports = sorted((cli_isolated / "exports").iterdir())
    markdown = [p for p in exports if p.suffix == ".md"][0].read_text(encoding="utf-8")
    csv_text = [p for p in exports if p.suffix == ".csv"][0].read_text(encoding="utf-8-sig")
    assert "行程问题" in markdown and "错题" in markdown
    assert "是" in csv_text  # 错题标记列
    assert csv_text.count("\n") == total + 1


# ---------------------------------------------------------------- TC-INT-010
def test_tc_int_010_export_backup_restore_roundtrip(cli_isolated, capsys):
    """CLI 导出 → 备份 → 误改数据 → 还原 的端到端闭环，数据精确回到备份时刻。"""
    cmd_init(argparse.Namespace())
    cmd_record(
        argparse.Namespace(
            module="资料分析", total="20", correct="18", duration="18:00",
            topic="增长率", date="", note="", wrong=True,
        )
    )
    baseline = Database().count_records()
    capsys.readouterr()

    assert cmd_export(argparse.Namespace(format="md", out=None)) == 0
    assert cmd_backup(argparse.Namespace(list=False)) == 0
    assert "数据库已备份" in capsys.readouterr().out

    # 模拟备份之后继续练习（此时若误还原，应回到 1 条）
    for _ in range(3):
        cmd_record(
            argparse.Namespace(
                module="数量关系", total="10", correct="4", duration="10:00",
                topic="", date="", note="", wrong=False,
            )
        )
    assert Database().count_records() == baseline + 3

    assert cmd_restore(argparse.Namespace(file="")) == 0
    output = capsys.readouterr().out
    assert "已从备份还原" in output and "自动另存为" in output
    assert Database().count_records() == baseline

    # 还原出的库是完整可用的 SQLite（表结构与错题标记都在）
    db_file = Path(config.DB_PATH)
    with db_file.open("rb") as handle:
        assert handle.read(16) == b"SQLite format 3\x00"
    conn = sqlite3.connect(str(db_file))
    try:
        assert conn.execute("SELECT COUNT(*) FROM practice_records WHERE is_wrong = 1").fetchone()[0] == 1
    finally:
        conn.close()
