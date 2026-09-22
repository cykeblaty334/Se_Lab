# -*- coding: utf-8 -*-
"""pytest 全局夹具。

约定：
* ``db``           —— 每个用例独立的临时数据库（避免污染真实 data/ceats.db）；
* ``seeded_db``    —— 已写入模块/考点/知识库字典的数据库；
* ``sample_records`` —— 覆盖五大模块的确定性样本数据，供分析类用例使用。
"""

import sys
from pathlib import Path

import pytest

# 允许在仓库根目录直接执行 pytest（把项目根加入 sys.path）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import Database  # noqa: E402
from src.models import Module  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    """返回一个空的临时数据库。"""
    database = Database(db_path=tmp_path / "test_ceats.db")
    yield database
    database.close()


@pytest.fixture()
def seeded_db(db):
    """返回已载入字典数据的数据库。"""
    db.seed()
    return db


@pytest.fixture()
def sample_records(seeded_db):
    """写入覆盖五大模块的固定样本数据，并返回 (数据库, 模块字典)。"""
    modules = {module.name: module for module in seeded_db.list_modules()}
    dataset = [
        ("2026-09-01", "言语理解与表达", "逻辑填空", 20, 15, 800),
        ("2026-09-02", "判断推理", "图形推理", 20, 14, 1000),
        ("2026-09-03", "数量关系", "行程问题", 20, 8, 1700),
        ("2026-09-04", "资料分析", "增长率", 20, 12, 1400),
        ("2026-09-05", "常识判断", "法律常识", 20, 11, 600),
        ("2026-09-06", "数量关系", "工程问题", 10, 4, 900),
    ]
    for record_date, module_name, topic_name, total, correct, duration in dataset:
        module: Module = modules[module_name]
        topic = seeded_db.get_topic_by_name(module.id, topic_name)
        seeded_db.add_record(
            record_date=record_date,
            module_id=module.id,
            topic_id=topic.id if topic else None,
            total_questions=total,
            correct_questions=correct,
            duration_seconds=duration,
            note="测试样本",
        )
    return seeded_db, modules
