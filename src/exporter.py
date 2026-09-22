# -*- coding: utf-8 -*-
"""业务层：报告导出与数据备份模块。

对应需求 FR-EXP-01 / FR-EXP-02 / FR-EXP-03：

1. **Markdown 报告**：把倒计时、目标拆解、模块诊断、复盘清单、趋势数据
   汇总为一份可直接打印的 ``YYYY-国考备考诊断报告.md``；
2. **CSV 明细**：导出练习记录明细，使用 ``utf-8-sig`` 编码，Excel 可直接打开；
3. **一键备份 / 还原**：把本地 ``.db`` 复制为带时间戳的备份文件，还原前
   会先自动备份当前数据库，避免误操作导致成绩数据丢失。

备份实现使用 SQLite 官方的 ``Connection.backup`` 接口而非直接复制文件，
这样即使数据库正处于写入状态，也能得到一致的快照。
"""

import csv
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import config
from .analyzer import Analyzer
from .database import Database
from .models import PracticeRecord
from .planner import PlanService
from .quiz import QuizService
from .reviewer import ReviewService

#: SQLite 文件头，用于校验备份文件是否为合法数据库
SQLITE_MAGIC = b"SQLite format 3\x00"
#: CEATS 备份必须包含的表，防止还原到无关的数据库文件
REQUIRED_TABLE = "practice_records"


class ExportError(ValueError):
    """导出或备份过程中的业务异常。"""


# ------------------------------------------------------------------ 命名
def report_filename(exam_name: str = "", today: Optional[date] = None) -> str:
    """生成 Markdown 报告文件名，如 ``2026-国考备考诊断报告.md``。"""
    base = today or date.today()
    name = exam_name or ""
    tag = "国考" if "国家" in name else ("省考" if "省" in name else "公考")
    return f"{base.year}-{tag}备考诊断报告.md"


# ------------------------------------------------------------------ Markdown
def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> List[str]:
    """把二维数据渲染为 Markdown 表格。"""
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def build_markdown(db: Database, today: Optional[date] = None) -> str:
    """生成完整的 Markdown 诊断报告文本。"""
    base = today or date.today()
    analyzer = Analyzer(db)
    planner = PlanService(db)
    reviewer = ReviewService(db)
    quiz = QuizService(db)

    plan = planner.current(base)
    overall = analyzer.overall()
    filename = report_filename(str((plan or {}).get("exam_name", "")), base)

    lines = [
        f"# {base.year} 年公考备考诊断报告",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　|　"
        f"数据来源：CEATS 本地数据库（SQLite）",
        "",
        "## 一、备考倒计时与目标",
        "",
    ]
    if plan:
        lines += [
            f"- 考试名称：{plan['exam_name']}",
            f"- 考试日期：{plan['exam_date']}（剩余 {plan['days_remaining']} 天）",
            f"- 目标总分：{plan['target_score']:g} 分"
            f"（行测目标 {plan['xingce_target']:g} 分 + 申论预期 {plan['essay_score']:g} 分）",
            "",
        ]
        lines += _table(
            ["模块", "黄金比例", "建议正确率", "建议得分", "当前正确率", "差距"],
            [
                [
                    row["short"],
                    f"{row['golden']:g}%",
                    f"{row['ratio']:g}%",
                    f"{row['target_score']:g}",
                    f"{row['current']}%" if row["current"] is not None else "—",
                    row["gap"],
                ]
                for row in planner.target_table(float(plan["target_score"]))
            ],
        )
        lines += [
            "",
            f"按上述目标正确率估算，行测可得约 "
            f"{planner.estimated_xingce_score(float(plan['target_score'])):g} / 100 分。",
        ]
    else:
        lines.append("尚未设置备考计划，请执行 `python -m src.main plan set` 补充。")

    lines += [
        "",
        "## 二、整体统计",
        "",
        f"- 练习记录：{overall['records']} 条"
        f"（覆盖 {overall['covered_modules']}/{overall['total_modules']} 个模块）",
        f"- 累计题量：{overall['total_questions']} 题，答对 {overall['correct_questions']} 题",
        f"- 整体正确率：{overall['accuracy']}%",
        f"- 平均单题耗时：{overall['seconds_per_question']} 秒",
        f"- 错题标记：{db.count_wrong_records()} 条",
        "",
        "## 三、模块诊断明细",
        "",
    ]
    diagnoses = analyzer.diagnose_modules()
    practiced = [item for item in diagnoses if item.records > 0]
    if practiced:
        lines += _table(
            ["模块", "记录数", "正确率", "单题耗时", "综合得分", "判定"],
            [
                [
                    item.module_name,
                    item.records,
                    f"{round(item.accuracy * 100, 1)}%",
                    f"{item.seconds_per_question}s",
                    item.final_score,
                    "弱项" if item.is_weak else "正常",
                ]
                for item in practiced
            ],
        )
    else:
        lines.append("暂无练习记录。")

    weak = [item for item in practiced if item.is_weak]
    lines += ["", "## 四、薄弱环节定位", ""]
    if weak:
        for item in weak:
            detail = "、".join(item.weak_topics) if item.weak_topics else "暂无细分考点数据"
            lines.append(f"- **{item.module_name}**：{detail}")
    else:
        lines.append("暂未发现明显弱项。")

    lines += ["", "## 五、今日优先复盘清单", ""]
    review_rows = reviewer.as_dicts(today=base)
    if review_rows:
        lines += _table(
            ["优先级", "模块", "考点", "正确率", "单题耗时", "错题数", "入选原因"],
            [
                [
                    row["priority"],
                    row["module_name"],
                    row["topic_name"],
                    f"{row['accuracy']}%",
                    f"{row['seconds_per_question']}s",
                    row["wrong_records"],
                    row["reason"],
                ]
                for row in review_rows
            ],
        )
    else:
        lines.append("暂无带考点的练习记录。")

    lines += ["", "## 六、最近 14 天正确率趋势", ""]
    trend = analyzer.trend(days=14)
    if trend:
        lines += _table(
            ["日期", "正确率", "单题耗时"],
            [[day, f"{acc}%", f"{spq}s"] for day, acc, spq in trend],
        )
    else:
        lines.append("暂无趋势数据。")

    lines += ["", "## 七、错题备忘", ""]
    wrong_records = db.list_wrong_records(limit=10)
    if wrong_records:
        lines += _table(
            ["日期", "模块", "考点", "对/总", "备注"],
            [
                [
                    item.record_date,
                    item.module_name,
                    item.topic_name or "—",
                    f"{item.correct_questions}/{item.total_questions}",
                    item.note or "—",
                ]
                for item in wrong_records
            ],
        )
    else:
        lines.append("暂无错题标记，可在录入时加 `--wrong` 参数标记。")

    lines += ["", "## 八、闪卡抽测统计", ""]
    lines.append("- " + quiz.stats_text().replace("\n", "\n- "))
    lines += [
        "",
        "---",
        "",
        f"本报告由 CEATS 自动生成（文件名：`{filename}`），"
        "数据全部来自本地练习记录，可用 `python -m src.main export` 重新导出。",
        "",
    ]
    return "\n".join(lines)


def export_markdown(
    db: Database, out_path: Optional[Path] = None, today: Optional[date] = None
) -> Path:
    """把诊断报告导出为 Markdown 文件，返回文件路径。"""
    base = today or date.today()
    plan = PlanService(db).current(base)
    if out_path is None:
        filename = report_filename(str((plan or {}).get("exam_name", "")), base)
        out_path = Path(config.EXPORT_DIR) / filename
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_markdown(db, base), encoding="utf-8")
    return target


def record_to_row(record: PracticeRecord) -> List[object]:
    """把一条练习记录转换为 CSV 行。"""
    return [
        record.id,
        record.record_date,
        record.module_name,
        record.topic_name,
        record.total_questions,
        record.correct_questions,
        round(record.accuracy * 100, 1),
        record.duration_seconds,
        round(record.seconds_per_question, 1),
        "是" if record.is_wrong else "否",
        record.note,
    ]


def export_csv(db: Database, out_path: Optional[Path] = None) -> Path:
    """把练习记录明细导出为 CSV（utf-8-sig，Excel 可直接打开）。"""
    if out_path is None:
        out_path = Path(config.EXPORT_DIR) / f"ceats-练习记录-{date.today().isoformat()}.csv"
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "ID", "日期", "模块", "考点", "总题数", "对题数",
        "正确率(%)", "用时(秒)", "单题耗时(秒)", "错题标记", "备注",
    ]
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for record in db.list_records():
            writer.writerow(record_to_row(record))
    return target


# ------------------------------------------------------------------ 备份还原
def unique_backup_path(directory: Path, stem: str, suffix: str = ".db") -> Path:
    """返回一个尚未被占用的备份路径（重名时追加 ``_1``、``_2`` …）。

    备份文件名只精确到秒，两次备份落在同一秒时直接写入会覆盖先前的快照。
    最危险的场景是 "还原前的安全备份" 恰好与待还原的备份同秒：
    覆盖后不仅丢失可回退的快照，还会让还原动作读到被改写的数据而失效，
    因此这里统一做一次去重。
    """
    candidate = directory / f"{stem}{suffix}"
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{index}{suffix}"
        index += 1
    return candidate


def backup_database(
    db_path=None, backup_dir=None, moment: Optional[datetime] = None
) -> Path:
    """备份数据库为带时间戳的文件，返回备份路径。

    :raises ExportError: 数据库文件不存在。
    """
    source = Path(db_path or config.DB_PATH)
    if not source.exists():
        raise ExportError(f"数据库文件不存在：{source}，请先执行 python -m src.main init")
    directory = Path(backup_dir or config.BACKUP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = (moment or datetime.now()).strftime("%Y%m%d_%H%M%S")
    target = unique_backup_path(directory, f"{config.BACKUP_PREFIX}_{stamp}")

    src_conn = sqlite3.connect(str(source))
    dst_conn = sqlite3.connect(str(target))
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()
    return target


def is_sqlite_file(path) -> bool:
    """判断文件是否为合法 SQLite 数据库。"""
    target = Path(path)
    if not target.is_file():
        return False
    with target.open("rb") as handle:
        return handle.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC


def has_required_table(path, table: str = REQUIRED_TABLE) -> bool:
    """判断备份文件是否包含 CEATS 核心表。"""
    if not is_sqlite_file(path):
        return False
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def list_backups(backup_dir=None) -> List[Path]:
    """列出全部备份文件（按时间倒序，最新的在前）。"""
    directory = Path(backup_dir or config.BACKUP_DIR)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.db"), key=lambda item: item.name, reverse=True)


def restore_database(
    backup_file, db_path=None, backup_dir=None, moment: Optional[datetime] = None
) -> Dict[str, Optional[Path]]:
    """从备份文件还原数据库。

    还原前会自动把当前数据库另存一份，便于误操作后回退。

    :raises ExportError: 备份文件缺失、非法或不含核心表。
    :return: ``{"restored_from": 备份文件, "safety_backup": 还原前的备份或 None}``
    """
    source = Path(backup_file)
    if not source.is_file():
        raise ExportError(f"备份文件不存在：{source}")
    if not is_sqlite_file(source):
        raise ExportError(f"备份文件不是合法的 SQLite 数据库：{source}")
    if not has_required_table(source):
        raise ExportError(f"备份文件缺少核心表 {REQUIRED_TABLE}，拒绝还原：{source}")

    target = Path(db_path or config.DB_PATH)
    safety: Optional[Path] = None
    if target.exists():
        safety = backup_database(target, backup_dir, moment)

    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(source))
    dst_conn = sqlite3.connect(str(target))
    try:
        with dst_conn:
            conn.backup(dst_conn)
    finally:
        conn.close()
        dst_conn.close()
    return {"restored_from": source, "safety_backup": safety}
