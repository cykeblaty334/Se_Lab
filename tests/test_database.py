# -*- coding: utf-8 -*-
"""数据访问层单元测试：表结构、约束、CRUD 与聚合查询。"""

import sqlite3

import pytest

from src.database import Database


def test_schema_creates_all_tables(db):
    """建库后应存在 6 张业务表与相应索引。"""
    tables = {
        row["name"]
        for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    expected = {
        "modules",
        "topics",
        "practice_records",
        "announcements",
        "knowledge_items",
        "exam_plans",
    }
    assert expected.issubset(tables)

    indexes = {
        row["name"]
        for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert {"idx_record_date", "idx_record_module", "idx_record_topic"} <= indexes


def test_seed_is_idempotent(seeded_db):
    """重复执行 seed 不应产生重复数据。"""
    first_modules = len(seeded_db.list_modules())
    first_topics = len(seeded_db.list_topics())
    first_knowledge = len(seeded_db.list_knowledge())

    seeded_db.seed()

    assert len(seeded_db.list_modules()) == first_modules == 5
    assert len(seeded_db.list_topics()) == first_topics == 20
    assert len(seeded_db.list_knowledge()) == first_knowledge


def test_topic_belongs_to_module(seeded_db):
    """考点必须挂载在正确的模块下（两级关联正确性）。"""
    math = seeded_db.get_module_by_name("数量关系")
    topics = {topic.name for topic in seeded_db.list_topics(math.id)}
    assert "行程问题" in topics
    assert "逻辑填空" not in topics


def test_add_and_get_record(seeded_db):
    """新增记录后可按 id 查回，且联表字段正确。"""
    module = seeded_db.get_module_by_name("资料分析")
    record_id = seeded_db.add_record(
        record_date="2026-09-10",
        module_id=module.id,
        total_questions=20,
        correct_questions=15,
        duration_seconds=1200,
        note="资料分析专项",
    )
    record = seeded_db.get_record(record_id)
    assert record is not None
    assert record.module_name == "资料分析"
    assert record.accuracy == pytest.approx(0.75)
    assert record.seconds_per_question == pytest.approx(60.0)


def test_record_foreign_key_is_enforced(seeded_db):
    """外键约束：引用不存在的模块应报错。"""
    with pytest.raises(sqlite3.IntegrityError):
        seeded_db.add_record(
            record_date="2026-09-10",
            module_id=9999,
            total_questions=10,
            correct_questions=5,
            duration_seconds=600,
        )


def test_record_check_constraints(seeded_db):
    """CHECK 约束：对题数不得超过总题数、题数必须为正。"""
    module = seeded_db.get_module_by_name("判断推理")
    with pytest.raises(sqlite3.IntegrityError):
        seeded_db.add_record(
            record_date="2026-09-10",
            module_id=module.id,
            total_questions=10,
            correct_questions=11,
            duration_seconds=600,
        )
    with pytest.raises(sqlite3.IntegrityError):
        seeded_db.add_record(
            record_date="2026-09-10",
            module_id=module.id,
            total_questions=0,
            correct_questions=0,
            duration_seconds=600,
        )


def test_update_and_delete_record(seeded_db):
    """更新与删除记录返回正确结果，且删除后查不到。"""
    module = seeded_db.get_module_by_name("常识判断")
    record_id = seeded_db.add_record(
        record_date="2026-09-11",
        module_id=module.id,
        total_questions=20,
        correct_questions=10,
        duration_seconds=900,
    )
    assert seeded_db.update_record(record_id, correct_questions=18) is True
    assert seeded_db.get_record(record_id).correct_questions == 18
    # 不含合法字段的更新请求应被拒绝
    assert seeded_db.update_record(record_id, unknown_field=1) is False
    assert seeded_db.delete_record(record_id) is True
    assert seeded_db.get_record(record_id) is None
    assert seeded_db.delete_record(record_id) is False


def test_list_records_filters(seeded_db):
    """按模块与日期区间过滤记录。"""
    math = seeded_db.get_module_by_name("数量关系")
    chinese = seeded_db.get_module_by_name("言语理解与表达")
    for month, day, module in ((9, 1, math), (9, 5, math), (9, 9, chinese)):
        seeded_db.add_record(
            record_date=f"2026-{month:02d}-{day:02d}",
            module_id=module.id,
            total_questions=10,
            correct_questions=5,
            duration_seconds=600,
        )
    assert seeded_db.count_records() == 3

    math_records = seeded_db.list_records(module_id=math.id)
    assert len(math_records) == 2

    ranged = seeded_db.list_records(start_date="2026-09-02", end_date="2026-09-06")
    assert len(ranged) == 1
    assert ranged[0].record_date == "2026-09-05"

    assert len(seeded_db.list_records(limit=2)) == 2


def test_module_and_topic_aggregate(sample_records):
    """聚合查询结果与样本数据一致。"""
    db, _ = sample_records
    aggregates = {row["module_name"]: row for row in db.module_aggregate()}

    assert aggregates["数量关系"]["records"] == 2
    assert aggregates["数量关系"]["total_questions"] == 30
    assert aggregates["数量关系"]["correct_questions"] == 12
    # 未练习的模块也需出现在结果中（LEFT JOIN），保证雷达图五轴完整
    assert set(aggregates) == {
        "言语理解与表达",
        "判断推理",
        "数量关系",
        "资料分析",
        "常识判断",
    }

    topics = {row["topic_name"]: row for row in db.topic_aggregate()}
    assert topics["行程问题"]["correct_questions"] == 8
    assert topics["行程问题"]["total_questions"] == 20


def test_daily_aggregate_sorted_ascending(sample_records):
    """按日聚合需按日期升序返回，便于绘制趋势折线。"""
    db, _ = sample_records
    series = db.daily_aggregate(days=30)
    dates = [row["record_date"] for row in series]
    assert dates == sorted(dates)
    assert len(dates) == 6


def test_announcement_dedup_by_url(seeded_db):
    """公告按 url 去重，重复写入只新增一次。"""
    from src.models import Announcement

    def build(url):
        return Announcement(
            id=None, source="测试站", title="测试公告标题", url=url, fetched_at=""
        )

    inserted, skipped = seeded_db.save_announcements([build("http://a.com/1")])
    assert (inserted, skipped) == (1, 0)

    inserted, skipped = seeded_db.save_announcements(
        [build("http://a.com/1"), build("http://a.com/2")]
    )
    assert (inserted, skipped) == (1, 1)
    assert seeded_db.count_announcements() == 2


def test_count_announcements_can_exclude_navigation(seeded_db):
    """断网降级写入的「导航」链接可按关键词排除，便于区分真实公告。"""
    from src.models import Announcement

    seeded_db.save_announcements(
        [
            Announcement(None, "测试站", "2026年省考报名公告", "http://a.com/1", None, "报名", ""),
            Announcement(
                None, "国家公务员局", "国家公务员局（官方入口）",
                "http://www.scs.gov.cn/", None, "导航", "",
            ),
        ]
    )
    assert seeded_db.count_announcements() == 2
    assert seeded_db.count_announcements(exclude_keyword="导航") == 1


def test_knowledge_operations(seeded_db):
    """知识库新增、检索与分类查询。"""
    assert "公式" in seeded_db.list_knowledge_categories()

    hits = seeded_db.search_knowledge("隔年增长率")
    assert hits and hits[0].keyword == "隔年增长率"

    content_hits = seeded_db.search_knowledge("最小公倍数")
    assert any("工程问题" == item.keyword for item in content_hits)

    assert seeded_db.add_knowledge("新公式", "公式", "内容示例", "示例") > 0
    assert seeded_db.search_knowledge("新公式")


def test_exam_plan_upsert(seeded_db):
    """备考目标支持覆盖更新。"""
    seeded_db.set_exam_plan("国考", "2027-11-28", 70.0)
    assert seeded_db.get_exam_plan()["target_score"] == 70.0

    seeded_db.set_exam_plan("国考", "2027-11-28", 80.0)
    plan = seeded_db.get_exam_plan()
    assert plan["target_score"] == 80.0
    assert seeded_db.conn.execute("SELECT COUNT(*) AS c FROM exam_plans").fetchone()["c"] == 1


def test_reset_clears_business_data(seeded_db):
    """reset 应清空业务数据但保留表结构。"""
    module = seeded_db.get_module_by_name("资料分析")
    seeded_db.add_record(
        record_date="2026-09-12",
        module_id=module.id,
        total_questions=10,
        correct_questions=5,
        duration_seconds=600,
    )
    seeded_db.reset()
    assert seeded_db.count_records() == 0
    assert seeded_db.list_modules() == []


def test_in_memory_database_does_not_touch_data_dir():
    """:memory: 模式不应在磁盘上创建任何文件。"""
    memory_db = Database(db_path=":memory:")
    memory_db.seed()
    assert memory_db.count_records() == 0
    memory_db.close()
