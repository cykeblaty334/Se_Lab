# -*- coding: utf-8 -*-
"""导出与备份模块单元测试：Markdown/CSV 生成、备份与还原的安全性。"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from src import config
from src.database import Database
from src.exporter import (
    ExportError,
    SQLITE_MAGIC,
    backup_database,
    build_markdown,
    export_csv,
    export_markdown,
    has_required_table,
    is_sqlite_file,
    list_backups,
    record_to_row,
    report_filename,
    restore_database,
    unique_backup_path,
)

TODAY = date(2026, 9, 21)


@pytest.fixture()
def sample_db(seeded_db):
    """带两条记录（其中一条错题）+ 一份备考计划的数据库。"""
    modules = {module.name: module for module in seeded_db.list_modules()}
    module = modules["数量关系"]
    topic = seeded_db.get_topic_by_name(module.id, "行程问题")
    seeded_db.set_exam_plan("2027 年国家公务员考试", "2027-11-28", 135.0, 65.0)
    seeded_db.add_record(
        record_date="2026-09-20",
        module_id=module.id,
        topic_id=topic.id,
        total_questions=20,
        correct_questions=8,
        duration_seconds=1800,
        note="专项突破",
        is_wrong=True,
    )
    seeded_db.add_record(
        record_date="2026-09-21",
        module_id=modules["资料分析"].id,
        total_questions=20,
        correct_questions=15,
        duration_seconds=1200,
    )
    return seeded_db


# ------------------------------------------------------------------ 文件命名
@pytest.mark.parametrize(
    "exam_name,expected",
    [
        ("2027 年国家公务员考试", "2026-国考备考诊断报告.md"),
        ("2027 年广东省考", "2026-省考备考诊断报告.md"),
        ("某事业单位招考", "2026-公考备考诊断报告.md"),
        ("", "2026-公考备考诊断报告.md"),
    ],
)
def test_report_filename(exam_name, expected):
    assert report_filename(exam_name, TODAY) == expected


def test_report_filename_uses_current_year():
    assert report_filename("国考").startswith(str(date.today().year))


# ------------------------------------------------------------------ Markdown
def test_build_markdown_contains_all_sections(sample_db):
    text = build_markdown(sample_db, TODAY)
    for section in [
        "# 2026 年公考备考诊断报告",
        "## 一、备考倒计时与目标",
        "## 二、整体统计",
        "## 三、模块诊断明细",
        "## 四、薄弱环节定位",
        "## 五、今日优先复盘清单",
        "## 六、最近 14 天正确率趋势",
        "## 七、错题备忘",
        "## 八、闪卡抽测统计",
    ]:
        assert section in text


def test_build_markdown_renders_plan_and_targets(sample_db):
    text = build_markdown(sample_db, TODAY)
    assert "2027 年国家公务员考试" in text
    assert "目标总分：135 分" in text
    assert "行测目标 70 分" in text
    assert "| 资料 | 85% | 85% | 17 | 75.0% | 差 10.0 个百分点 |" in text


def test_build_markdown_renders_wrong_records(sample_db):
    text = build_markdown(sample_db, TODAY)
    assert "错题标记：1 条" in text
    assert "专项突破" in text


def test_build_markdown_without_plan(seeded_db):
    """没有备考计划时给出引导文案而不是崩溃。"""
    text = build_markdown(seeded_db, TODAY)
    assert "尚未设置备考计划" in text
    assert "暂无练习记录" in text


def test_build_markdown_without_wrong_records(seeded_db):
    seeded_db.add_record(
        record_date="2026-09-21",
        module_id=seeded_db.list_modules()[0].id,
        total_questions=10,
        correct_questions=8,
        duration_seconds=400,
    )
    text = build_markdown(seeded_db, TODAY)
    assert "暂无错题标记" in text
    assert "--wrong" in text


def test_export_markdown_default_directory(sample_db, tmp_path, monkeypatch):
    """不指定路径时，按 "年份-国考备考诊断报告.md" 规则落到导出目录。"""
    monkeypatch.setattr(config, "EXPORT_DIR", tmp_path / "exports")
    path = export_markdown(sample_db, today=TODAY)
    assert path.name == "2026-国考备考诊断报告.md"
    assert path.exists()
    assert "CEATS" in path.read_text(encoding="utf-8")


def test_export_markdown_explicit_path(sample_db, tmp_path):
    target = tmp_path / "nested" / "报告.md"
    path = export_markdown(sample_db, target, TODAY)
    assert path == target
    assert target.read_text(encoding="utf-8").startswith("# 2026")


# ------------------------------------------------------------------ CSV
def test_export_csv_writes_bom_and_rows(sample_db, tmp_path):
    path = export_csv(sample_db, tmp_path / "records.csv")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # utf-8-sig，Excel 打开不乱码

    lines = path.read_text(encoding="utf-8-sig").strip().splitlines()
    assert lines[0].split(",")[:4] == ["ID", "日期", "模块", "考点"]
    assert len(lines) == 3  # 表头 + 2 条记录
    assert "是" in lines[1] or "是" in lines[2]


def test_export_csv_default_directory(sample_db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXPORT_DIR", tmp_path / "exports")
    path = export_csv(sample_db)
    assert path.name == f"ceats-练习记录-{date.today().isoformat()}.csv"
    assert path.exists()


def test_record_to_row_layout(sample_db):
    record = sample_db.list_wrong_records()[0]
    row = record_to_row(record)
    assert len(row) == 11
    assert row[2] == "数量关系"
    assert row[3] == "行程问题"
    assert row[6] == 40.0  # 正确率 8/20
    assert row[8] == 90.0  # 单题耗时 1800/20
    assert row[9] == "是"


# ------------------------------------------------------------------ 备份
def test_backup_creates_timestamped_snapshot(sample_db, tmp_path):
    path = backup_database(sample_db.db_path, tmp_path / "backups",
                           datetime(2026, 9, 21, 15, 30, 0))
    assert path.name == "ceats_20260921_153000.db"
    assert is_sqlite_file(path)
    assert has_required_table(path)


def test_backup_snapshot_contains_data(sample_db, tmp_path):
    path = backup_database(sample_db.db_path, tmp_path / "backups")
    conn = sqlite3.connect(str(path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM practice_records").fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_backup_rejects_missing_database(tmp_path):
    with pytest.raises(ExportError, match="数据库文件不存在"):
        backup_database(tmp_path / "nope.db", tmp_path / "backups")


def test_backup_uses_config_dir_by_default(sample_db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    path = backup_database(sample_db.db_path)
    assert path.parent == tmp_path / "backups"


def test_backup_creates_missing_directory(sample_db, tmp_path):
    nested = tmp_path / "a" / "b"
    path = backup_database(sample_db.db_path, nested)
    assert nested.is_dir() and path.parent == nested


# ------------------------------------------------------------------ 备份枚举与校验
def test_list_backups_sorted_latest_first(sample_db, tmp_path):
    for stamp in [datetime(2026, 9, 20, 10, 0, 0), datetime(2026, 9, 21, 10, 0, 0)]:
        backup_database(sample_db.db_path, tmp_path / "backups", stamp)
    names = [path.name for path in list_backups(tmp_path / "backups")]
    assert names == ["ceats_20260921_100000.db", "ceats_20260920_100000.db"]


def test_list_backups_empty_when_directory_missing(tmp_path):
    assert list_backups(tmp_path / "absent") == []


def test_is_sqlite_file_detects_format(tmp_path):
    fake = tmp_path / "fake.db"
    fake.write_text("这不是数据库", encoding="utf-8")
    assert is_sqlite_file(fake) is False
    assert is_sqlite_file(tmp_path / "missing.db") is False

    real = tmp_path / "real.db"
    Database(db_path=real).close()
    assert is_sqlite_file(real) is True
    assert real.read_bytes().startswith(SQLITE_MAGIC)


def test_has_required_table(tmp_path):
    with_table = tmp_path / "with.db"
    Database(db_path=with_table).close()
    assert has_required_table(with_table) is True

    other = tmp_path / "other.db"
    conn = sqlite3.connect(str(other))
    conn.execute("CREATE TABLE demo (id INTEGER)")
    conn.commit()
    conn.close()
    assert has_required_table(other) is False
    assert has_required_table(tmp_path / "missing.db") is False


# ------------------------------------------------------------------ 还原
def test_restore_brings_back_old_snapshot(sample_db, tmp_path):
    db_file = Path(sample_db.db_path)
    backup_dir = tmp_path / "backups"
    snapshot = backup_database(db_file, backup_dir, datetime(2026, 9, 21, 9, 0, 0))
    sample_db.close()

    # 备份后再新增一条记录，模拟 "误删/误操作" 前的状态差异
    db = Database(db_path=db_file)
    db.add_record(
        record_date="2026-09-21",
        module_id=db.list_modules()[0].id,
        total_questions=10,
        correct_questions=5,
        duration_seconds=500,
    )
    assert db.count_records() == 3
    db.close()

    result = restore_database(
        snapshot, db_file, backup_dir, datetime(2026, 9, 21, 16, 0, 0)
    )
    assert result["restored_from"] == snapshot
    assert result["safety_backup"] is not None
    assert result["safety_backup"].name == "ceats_20260921_160000.db"

    restored = Database(db_path=db_file)
    assert restored.count_records() == 2  # 回到备份时刻的状态
    restored.close()

    # 还原前的数据被完整保留在安全备份里，可再次回退
    safety = sqlite3.connect(str(result["safety_backup"]))
    try:
        assert safety.execute("SELECT COUNT(*) FROM practice_records").fetchone()[0] == 3
    finally:
        safety.close()


def test_restore_without_existing_target_skips_safety_backup(tmp_path):
    source = tmp_path / "src.db"
    db = Database(db_path=source)
    db.seed()
    db.add_record(
        record_date="2026-09-21",
        module_id=db.list_modules()[0].id,
        total_questions=10,
        correct_questions=6,
        duration_seconds=400,
    )
    db.close()

    result = restore_database(source, tmp_path / "target.db", tmp_path / "backups")
    assert result["safety_backup"] is None
    assert Database(db_path=tmp_path / "target.db").count_records() == 1


def test_restore_rejects_missing_backup(tmp_path):
    with pytest.raises(ExportError, match="备份文件不存在"):
        restore_database(tmp_path / "nope.db", tmp_path / "target.db")


def test_restore_rejects_non_sqlite_file(tmp_path):
    fake = tmp_path / "fake.db"
    fake.write_text("我是一个文本文件", encoding="utf-8")
    with pytest.raises(ExportError, match="不是合法的 SQLite"):
        restore_database(fake, tmp_path / "target.db")


def test_restore_rejects_unrelated_database(tmp_path):
    """防止把别的项目的数据库覆盖进来。"""
    other = tmp_path / "other.db"
    conn = sqlite3.connect(str(other))
    conn.execute("CREATE TABLE todo (id INTEGER)")
    conn.commit()
    conn.close()
    with pytest.raises(ExportError, match="缺少核心表"):
        restore_database(other, tmp_path / "target.db")


def test_restore_does_not_touch_target_on_failure(tmp_path):
    """校验失败时目标数据库必须原封不动。"""
    target = tmp_path / "ceats.db"
    db = Database(db_path=target)
    db.seed()
    db.add_record(
        record_date="2026-09-21",
        module_id=db.list_modules()[0].id,
        total_questions=10,
        correct_questions=6,
        duration_seconds=400,
    )
    db.close()

    other = tmp_path / "other.db"
    conn = sqlite3.connect(str(other))
    conn.execute("CREATE TABLE todo (id INTEGER)")
    conn.commit()
    conn.close()

    with pytest.raises(ExportError):
        restore_database(other, target)
    assert Database(db_path=target).count_records() == 1


# ------------------------------------------------------- 备份重名（回归 ISSUE-002）
def test_unique_backup_path_avoids_collision(tmp_path):
    """同一秒内多次备份不得互相覆盖。"""
    assert unique_backup_path(tmp_path, "ceats_20260921_090000").name == "ceats_20260921_090000.db"
    (tmp_path / "ceats_20260921_090000.db").write_text("x", encoding="utf-8")
    assert unique_backup_path(tmp_path, "ceats_20260921_090000").name == "ceats_20260921_090000_1.db"
    (tmp_path / "ceats_20260921_090000_1.db").write_text("x", encoding="utf-8")
    assert unique_backup_path(tmp_path, "ceats_20260921_090000").name == "ceats_20260921_090000_2.db"


def test_backup_twice_in_same_second_keeps_both(tmp_path):
    """连续两次 backup（同一秒）应产生两份备份，而不是悄悄覆盖。"""
    db_file = tmp_path / "ceats.db"
    db = Database(db_path=db_file)
    db.seed()
    db.add_record(
        record_date="2026-09-21",
        module_id=db.list_modules()[0].id,
        total_questions=10,
        correct_questions=6,
        duration_seconds=400,
    )
    db.close()

    backup_dir = tmp_path / "backups"
    moment = datetime(2026, 9, 21, 9, 0, 0)
    first = backup_database(db_file, backup_dir, moment)
    second = backup_database(db_file, backup_dir, moment)

    assert first != second
    assert len(list_backups(backup_dir)) == 2
    assert first.name == "ceats_20260921_090000.db"
    assert second.name == "ceats_20260921_090000_1.db"


def test_restore_keeps_source_backup_in_same_second(sample_db, tmp_path):
    """回归 ISSUE-002：还原前的安全备份不得覆盖待还原的备份。

    旧实现把两份备份写成同一文件名，导致待还原的备份被当前数据覆盖，
    还原动作随之失效（数据仍是"被误改"后的状态），且可回退快照被销毁。
    """
    db_file = Path(sample_db.db_path)
    backup_dir = tmp_path / "backups"
    snapshot = backup_database(db_file, backup_dir, datetime(2026, 9, 21, 9, 0, 0))
    snapshot_bytes = snapshot.read_bytes()
    sample_db.close()

    db = Database(db_path=db_file)
    db.add_record(
        record_date="2026-09-21",
        module_id=db.list_modules()[0].id,
        total_questions=10,
        correct_questions=5,
        duration_seconds=500,
    )
    assert db.count_records() == 3
    db.close()

    # 同一秒内还原：安全备份与待还原备份的时间戳完全相同
    result = restore_database(snapshot, db_file, backup_dir, datetime(2026, 9, 21, 9, 0, 0))
    assert result["safety_backup"] != snapshot
    assert snapshot.read_bytes() == snapshot_bytes  # 原备份内容未被改写
    assert len(list_backups(backup_dir)) == 2

    restored = Database(db_path=db_file)
    assert restored.count_records() == 2  # 还原真正生效
    restored.close()

    safety = sqlite3.connect(str(result["safety_backup"]))
    try:
        assert safety.execute("SELECT COUNT(*) FROM practice_records").fetchone()[0] == 3
    finally:
        safety.close()
