# -*- coding: utf-8 -*-
"""展示层：命令行交互入口。

统一入口支持两种使用方式：

1. 交互模式（默认）：``python -m src.main`` 进入菜单，适合日常备考录入；
2. 命令模式：``python -m src.main report --days 30`` 适合脚本化/演示。

命令清单：
    init     初始化数据库（建表 + 写入模块/考点/知识库字典）
    record   录入一条练习记录（--wrong 可标记为错题）
    list     查看最近练习记录
    report   生成文本诊断报告
    chart    生成雷达图 / 趋势图 / 得分排名图
    scrape   抓取招考公告（失败自动降级为链接导航；--list 只看已入库）
    kb       知识库检索 / 浏览
    plan     备考倒计时与目标分拆解（set / show）
    quiz     弱项考点极速抽测闪卡（终端互动判分）
    review   今日优先复盘清单（错题 + 难题推荐）
    note     补打 / 取消错题标记
    export   导出 Markdown 诊断报告或 CSV 明细
    backup   一键备份数据库
    restore  从备份还原数据库
    demo     写入一批演示数据，便于演示与出图
    menu     进入交互式菜单
"""

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from . import config
from . import __version__ as VERSION
from .analyzer import Analyzer
from .database import Database
from .exporter import (
    ExportError,
    backup_database,
    export_csv,
    export_markdown,
    list_backups,
    restore_database,
)
from .knowledge import KnowledgeBase, KnowledgeBaseError
from .models import Announcement
from .planner import PlanError, PlanService
from .quiz import QuizService
from .recorder import RecordError, RecordService, build_feedback
from .reviewer import ReviewService
from .scraper import scrape_and_store
from .visualizer import display_charts, plot_all

#: 交互菜单文本
MENU_TEXT = f"""
============================================================
 CEATS 公考量化分析系统  v{VERSION}
============================================================
 1. 成绩录入        2. 查看历史记录     3. 弱项诊断报告
 4. 生成可视化图表  5. 招考公告抓取     6. 知识库查询
 7. 备考计划/倒计时 8. 闪卡抽测刷题     9. 今日优先复盘
 10. 导出报告      11. 数据备份/还原   12. 标记错题
 13. 删除记录      0. 退出
============================================================="""


def _print(text: str = "") -> None:
    """统一输出封装，便于后续替换为日志。"""
    print(text)


#: 断网降级时写入的官方入口链接使用的关键词标记
NAV_KEYWORD = "导航"


def _print_announcements(items: List[Announcement], limit: int = 0) -> None:
    """打印公告列表（带关键词标记；截断时提示如何查看全部）。"""
    shown = items[:limit] if limit else items
    for index, item in enumerate(shown, start=1):
        tag = f"[{item.matched_keyword}]" if item.matched_keyword else ""
        _print(f"{index:>2}. {tag}{item.title}\n    {item.url}")
    if limit and len(items) > limit:
        _print(f"（共 {len(items)} 条，仅显示前 {limit} 条；加 --limit {len(items)} 可看全部）")


def _announcement_count_text(db: Database) -> str:
    """公告入库情况说明（区分真实公告与断网降级写入的导航链接）。"""
    total = db.count_announcements()
    real = db.count_announcements(exclude_keyword=NAV_KEYWORD)
    if total > real:
        return f"数据库中累计公告：{total} 条（真实公告 {real} 条 + 降级导航链接 {total - real} 条）"
    return f"数据库中累计公告：{total} 条"


# ------------------------------------------------------------------ 命令实现
def cmd_init(args) -> int:
    """初始化数据库：建表 + 写入字典数据。"""
    db = Database()
    db.init_schema()
    db.seed()
    modules = db.list_modules()
    _print(f"数据库初始化完成：{config.DB_PATH}")
    _print(f"已载入 {len(modules)} 个模块、{db.count_records()} 条练习记录、"
           f"{len(db.list_knowledge())} 条知识库条目")
    db.close()
    return 0


def cmd_record(args) -> int:
    """录入一条练习记录（非交互式，参数一次给全）。"""
    db = Database()
    db.seed()
    service = RecordService(db)
    try:
        record = service.submit(
            module_raw=args.module,
            total_raw=args.total,
            correct_raw=args.correct,
            duration_raw=args.duration,
            topic_raw=args.topic or "",
            date_raw=args.date or "",
            note=args.note or "",
            is_wrong=getattr(args, "wrong", False),
        )
    except RecordError as exc:
        _print(f"录入失败：{exc}")
        db.close()
        return 1
    _print(build_feedback(record))
    db.close()
    return 0


def cmd_list(args) -> int:
    """查看最近的练习记录（--wrong 只看错题）。"""
    db = Database()
    if getattr(args, "wrong", False):
        records = db.list_wrong_records(limit=args.limit)
    else:
        records = db.list_records(limit=args.limit)
    if not records:
        _print("暂无错题记录。" if getattr(args, "wrong", False) else "暂无练习记录。")
        db.close()
        return 0
    _print(f"{'ID':<5}{'日期':<12}{'模块':<16}{'考点':<12}{'对/总':<9}"
           f"{'正确率':<9}{'单题':<7}{'错题':<5}")
    _print("-" * 80)
    for record in records:
        topic = record.topic_name or "-"
        ratio = f"{record.correct_questions}/{record.total_questions}"
        _print(
            f"{record.id:<5}{record.record_date:<12}{record.module_name:<16}"
            f"{topic:<12}{ratio:<9}{record.accuracy * 100:>6.1f}%"
            f"{record.seconds_per_question:>6.1f}s"
            f"{('是' if record.is_wrong else '-'):<5}"
        )
    db.close()
    return 0


def cmd_report(args) -> int:
    """生成文本诊断报告。"""
    db = Database()
    analyzer = Analyzer(db)
    start = args.start
    end = args.end
    if args.days:
        start = (date.today() - timedelta(days=args.days)).isoformat()
    _print(analyzer.text_report(start, end))
    db.close()
    return 0


def cmd_chart(args) -> int:
    """生成可视化图表。"""
    db = Database()
    analyzer = Analyzer(db)
    diagnoses = analyzer.diagnose_modules()
    series = analyzer.trend(days=args.days)
    if not analyzer.ready_for_radar():
        _print(
            f"提示：当前记录不足 {config.MIN_RECORDS_FOR_RADAR} 条，"
            "图表仅供参考，建议继续积累练习数据。"
        )
    paths = plot_all(diagnoses, series)
    _print("图表已生成：")
    for path in paths:
        _print(f"  - {path}")

    if getattr(args, "show", False):
        if display_charts(paths):
            _print("已在图形窗口中打开图表（关闭窗口后返回）。")
        else:
            _print("当前环境不支持弹窗，请直接打开上述图片文件查看。")
    db.close()
    return 0


def cmd_scrape(args) -> int:
    """抓取招考公告并入库；带 --list 时只查看已入库公告（不联网）。"""
    db = Database()
    if getattr(args, "list", False):
        items = db.list_announcements(keyword=args.keywords or None, limit=args.limit)
        if not items:
            _print("库中暂无公告，可先执行 python -m src.main scrape 抓取。")
        else:
            _print_announcements(items, args.limit)
        _print(_announcement_count_text(db))
        db.close()
        return 0
    keywords = args.keywords.split(",") if args.keywords else None
    result = scrape_and_store(db, keywords=keywords)
    _print(result.summary())
    _print("-" * 60)
    _print_announcements(result.announcements, args.limit)
    _print(_announcement_count_text(db))
    db.close()
    return 0


def cmd_kb(args) -> int:
    """知识库检索 / 浏览。"""
    db = Database()
    kb = KnowledgeBase(db)
    if args.keyword:
        try:
            items = kb.search(args.keyword)
        except KnowledgeBaseError as exc:
            _print(f"查询失败：{exc}")
            db.close()
            return 1
    else:
        items = kb.browse(args.category)
    _print(KnowledgeBase.format_items(items))
    db.close()
    return 0


# ------------------------------------------------------------------ 备考计划
def cmd_plan(args) -> int:
    """备考倒计时与目标分拆解。"""
    db = Database()
    planner = PlanService(db)
    action = getattr(args, "plan_action", None)
    if action == "set":
        try:
            planner.set_plan(
                exam_name=getattr(args, "name", "") or config.DEFAULT_EXAM_NAME,
                exam_date_raw=args.date,
                target_raw=args.target,
                essay_raw=getattr(args, "essay", "") or "",
            )
        except PlanError as exc:
            _print(f"设置失败：{exc}")
            db.close()
            return 1
        _print("已设置备考计划。")
        _print()
    for line in planner.summary_lines():
        _print(line)
    db.close()
    return 0


# ------------------------------------------------------------------ 闪卡抽测
def cmd_quiz(args) -> int:
    """弱项考点极速抽测闪卡。"""
    db = Database()
    db.seed()
    quiz = QuizService(db)
    if getattr(args, "stats", False):
        _print(quiz.stats_text())
        db.close()
        return 0

    if db.get_exam_plan() is None:
        _print("提示：尚未设置备考计划。执行 python -m src.main plan set --date 考试日期 "
               "后，系统每次启动会提醒剩余天数。")
        _print()
    _print("=" * 50)
    _print("CEATS 极速抽测闪卡：从知识库随机抽题，答完自动判分")
    _print("=" * 50)
    try:
        results = quiz.run_session(
            count=getattr(args, "count", config.QUIZ_DEFAULT_COUNT),
            category=getattr(args, "category", None),
        )
    except ValueError as exc:
        _print(f"无法开始抽测：{exc}")
        db.close()
        return 1
    if results:
        _print()
        _print(quiz.stats_text())
    db.close()
    return 0


# ------------------------------------------------------------------ 复盘清单
def cmd_review(args) -> int:
    """今日优先复盘清单。"""
    db = Database()
    reviewer = ReviewService(db)
    _print(
        reviewer.format_list(
            days=getattr(args, "days", config.REVIEW_RECENT_DAYS),
            top_n=getattr(args, "top", config.REVIEW_TOP_N),
        )
    )
    db.close()
    return 0


def cmd_note(args) -> int:
    """补打 / 取消错题标记。"""
    db = Database()
    reviewer = ReviewService(db)
    record = reviewer.mark(args.id, is_wrong=not getattr(args, "clear", False))
    if record is None:
        _print(f"未找到记录：{args.id}")
        db.close()
        return 1
    flag = "已标记为错题" if record.is_wrong else "已取消错题标记"
    _print(
        f"{flag}：#{record.id} {record.record_date} "
        f"{record.module_name}"
        + (f" / {record.topic_name}" if record.topic_name else "")
    )
    db.close()
    return 0


def cmd_web(args) -> int:
    """启动本地 Web 界面（延迟导入 flask，便于未安装依赖时给出友好提示）。"""
    try:
        from .webapp import main as web_main
    except ImportError as exc:  # pragma: no cover - 依赖缺失时的兜底提示
        _print(f"启动失败：缺少 Web 依赖（{exc}），请先执行 pip install flask")
        return 1
    argv = ["--host", args.host, "--port", str(args.port)]
    if getattr(args, "open", False):
        argv.append("--open")
    return web_main(argv)


def cmd_delete(args) -> int:
    """删除一条练习记录（默认需要二次确认，``--yes`` 可跳过）。"""
    db = Database()
    record = db.get_record(args.id)
    if record is None:
        _print(f"未找到记录：{args.id}（可先执行 list 命令查看现有 ID）")
        db.close()
        return 1
    _print(
        f"待删除：#{record.id} {record.record_date} {record.module_name}"
        + (f" / {record.topic_name}" if record.topic_name else "")
        + f"  {record.correct_questions}/{record.total_questions} 题"
    )
    if not getattr(args, "yes", False):
        try:
            confirm = _prompt("确认删除？该操作不可撤销(y/N)", "n")
        except EOFError:
            # 无人值守场景（管道 / 重定向）读不到输入时按“取消”处理，避免误删
            confirm = "n"
        if confirm.lower() not in {"y", "yes", "是"}:
            _print("已取消删除，数据未改动。")
            db.close()
            return 0
    db.delete_record(record.id)
    _print(f"已删除记录 #{record.id}，数据库现有 {db.count_records()} 条练习记录。")
    db.close()
    return 0


# ------------------------------------------------------------------ 导出与备份
def cmd_export(args) -> int:
    """导出 Markdown 诊断报告 / CSV 明细。"""
    db = Database()
    fmt = getattr(args, "format", "md")
    out = getattr(args, "out", None)
    try:
        paths = []
        if fmt in ("md", "all"):
            paths.append(export_markdown(db, Path(out) if out else None))
        if fmt in ("csv", "all"):
            paths.append(export_csv(db, Path(out) if out else None))
    except (ExportError, OSError) as exc:
        _print(f"导出失败：{exc}")
        db.close()
        return 1
    _print("导出完成：")
    for path in paths:
        _print(f"  - {path}")
    if fmt in ("md", "all"):
        _print("提示：Markdown 文件可直接用 Typora / VS Code 打开并打印，"
               "或粘贴到 Word 中排版。")
    db.close()
    return 0


def cmd_backup(args) -> int:
    """一键备份数据库。"""
    if getattr(args, "list", False):
        backups = list_backups()
        if not backups:
            _print(f"暂无备份文件（备份目录：{config.BACKUP_DIR}）。")
            return 0
        _print(f"已有 {len(backups)} 份备份（{config.BACKUP_DIR}）：")
        for path in backups:
            _print(f"  - {path.name}（{round(path.stat().st_size / 1024, 1)} KB）")
        return 0

    db_file = Path(config.DB_PATH)
    if not db_file.exists():
        _print(f"备份失败：数据库文件不存在（{db_file}），请先执行 python -m src.main init")
        return 1
    db = Database()
    records = db.count_records()
    db.close()
    if records == 0:
        # 空快照既没有备份价值，日后误还原还会顶掉真实成绩，因此直接拒绝
        _print("备份失败：当前数据库还没有任何练习记录，空快照没有意义。")
        _print("请先执行 python -m src.main init 并录入成绩，再执行备份。")
        return 1
    try:
        path = backup_database()
    except ExportError as exc:
        _print(f"备份失败：{exc}")
        return 1
    _print(f"数据库已备份：{path}")
    _print(f"备份目录共 {len(list_backups())} 份文件（{config.BACKUP_DIR}）。")
    return 0


def cmd_restore(args) -> int:
    """从备份还原数据库。"""
    source = getattr(args, "file", "") or ""
    if not source:
        backups = list_backups()
        if not backups:
            _print(f"没有可用的备份文件（备份目录：{config.BACKUP_DIR}）。")
            return 1
        source = str(backups[0])
        _print(f"未指定备份文件，自动使用最新备份：{source}")
    try:
        result = restore_database(source)
    except ExportError as exc:
        _print(f"还原失败：{exc}")
        return 1
    _print(f"已从备份还原：{result['restored_from']}")
    if result["safety_backup"]:
        _print(f"还原前的数据库已自动另存为：{result['safety_backup']}")
    db = Database()
    _print(f"当前数据库共有 {db.count_records()} 条练习记录、"
           f"{db.count_wrong_records()} 条错题标记。")
    db.close()
    return 0


def cmd_demo(args) -> int:
    """写入一批演示数据（按日期分散，便于生成趋势图）。"""
    db = Database()
    db.seed()
    rng = random.Random(20260920)
    modules = db.list_modules()
    inserted = 0
    for offset in range(args.days, 0, -1):
        record_date = (date.today() - timedelta(days=offset)).isoformat()
        for module in modules:
            if rng.random() < 0.25:
                continue
            topics = db.list_topics(module.id)
            topic = rng.choice(topics) if topics else None
            total = rng.choice([10, 15, 20])
            base = {"言语理解与表达": 0.72, "判断推理": 0.68, "数量关系": 0.45,
                    "资料分析": 0.60, "常识判断": 0.55}.get(module.name, 0.6)
            correct = max(0, min(total, int(round(total * (base + rng.uniform(-0.12, 0.12))))))
            per_question = {"言语理解与表达": 40, "判断推理": 50, "数量关系": 85,
                            "资料分析": 70, "常识判断": 30}.get(module.name, 50)
            duration = int(total * per_question * rng.uniform(0.85, 1.2))
            db.add_record(
                record_date=record_date,
                module_id=module.id,
                topic_id=topic.id if topic else None,
                total_questions=total,
                correct_questions=correct,
                duration_seconds=duration,
                note="演示数据",
                # 正确率偏低的记录顺带打上错题标记，便于演示复盘清单
                is_wrong=correct / total < 0.6,
            )
            inserted += 1
    db.set_exam_plan(
        config.DEFAULT_EXAM_NAME,
        config.DEFAULT_EXAM_DATE,
        config.DEFAULT_TARGET_TOTAL,
        config.DEFAULT_ESSAY_SCORE,
    )
    _print(f"已写入 {inserted} 条演示记录（近 {args.days} 天），可用 report / chart 查看效果。")
    db.close()
    return 0


# ------------------------------------------------------------------ 交互模式
def _prompt(text: str, default: str = "") -> str:
    """读取用户输入，支持默认值（输入 q 返回哨兵值以便退出）。"""
    tip = f"{text}" + (f"[{default}]" if default else "")
    return input(f"{tip}: ").strip() or default


def _interactive_record(db: Database) -> None:
    """交互式成绩录入：逐项引导，非法输入不退出程序。"""
    service = RecordService(db)
    modules = service.modules()
    if not modules:
        db.seed()
        modules = service.modules()
    _print("可选模块：")
    for index, module in enumerate(modules, start=1):
        _print(f"  {index}. {module.name}")

    module_raw = _prompt("请选择模块（序号或名称）")
    module = service.match_module(module_raw)
    topics = service.topics(module.id)
    if topics:
        _print("可选考点：" + "、".join(f"{i}.{t.name}" for i, t in enumerate(topics, 1)))
    topic_raw = _prompt("请选择考点（可留空）")
    total_raw = _prompt("总题数")
    correct_raw = _prompt("对题数")
    duration_raw = _prompt("用时（如 12:30 或 1500 秒）")
    date_raw = _prompt("日期（默认今天）")
    note = _prompt("备注（可留空）")
    wrong_raw = _prompt("是否标记为错题(y/N)", "n")

    record = service.submit(
        module_raw=module_raw,
        total_raw=total_raw,
        correct_raw=correct_raw,
        duration_raw=duration_raw,
        topic_raw=topic_raw,
        date_raw=date_raw,
        note=note,
        is_wrong=wrong_raw.strip().lower() in {"y", "yes", "是", "1", "true"},
    )
    _print()
    _print(build_feedback(record))


def cmd_menu(args) -> int:
    """交互式主菜单。"""
    db = Database()
    db.seed()
    analyzer = Analyzer(db)
    kb = KnowledgeBase(db)
    planner = PlanService(db)
    quiz = QuizService(db)
    reviewer = ReviewService(db)

    while True:
        _print(MENU_TEXT)
        try:
            # 读取菜单编号也必须在 try 内：否则在菜单处按 Ctrl+C 会直接终止程序
            choice = _prompt("请输入功能编号").strip()
            if choice == "1":
                _interactive_record(db)
            elif choice == "2":
                cmd_list(argparse.Namespace(limit=15))
            elif choice == "3":
                _print(analyzer.text_report())
            elif choice == "4":
                diagnoses = analyzer.diagnose_modules()
                paths = plot_all(diagnoses, analyzer.trend(days=30))
                _print("图表已生成：")
                for path in paths:
                    _print(f"  - {path}")
                if display_charts(paths):
                    _print("图表窗口已弹出，关闭后返回菜单。")
                else:
                    _print("当前环境不支持弹窗，请直接打开上述图片文件查看。")
            elif choice == "5":
                result = scrape_and_store(db)
                _print(result.summary())
                _print("-" * 60)
                _print_announcements(result.announcements, 10)
                _print(_announcement_count_text(db))
            elif choice == "6":
                keyword = _prompt("请输入关键词（如 隔年增长率 / 申论）")
                if keyword:
                    _print(KnowledgeBase.format_items(kb.search(keyword)))
            elif choice == "7":
                current = planner.current() or {}
                _print("设置备考计划（方括号内为默认值，直接回车即采用）：")
                _print("  考试日期须为 YYYY-MM-DD 且不早于今天；目标总分为 1~200；"
                       "申论预期分须小于目标总分。")
                name = _prompt(
                    "考试名称（同名视为同一条计划）",
                    str(current.get("exam_name") or config.DEFAULT_EXAM_NAME),
                )
                exam_date = _prompt(
                    "考试日期（YYYY-MM-DD）",
                    str(current.get("exam_date") or config.DEFAULT_EXAM_DATE),
                )
                score = _prompt(
                    "目标总分（行测+申论，200 分制）",
                    f"{float(current.get('target_score') or config.DEFAULT_TARGET_TOTAL):g}",
                )
                essay = _prompt(
                    "申论预期得分",
                    f"{float(current.get('essay_score') or config.DEFAULT_ESSAY_SCORE):g}",
                )
                try:
                    planner.set_plan(name, exam_date, score, essay)
                except PlanError as exc:
                    _print(f"设置失败：{exc}")
                    continue
                _print(f"已设置备考目标：{name} @ {exam_date}")
                for line in planner.summary_lines(with_table=False):
                    _print(line)
            elif choice == "8":
                count = _prompt("抽测题数", str(config.QUIZ_DEFAULT_COUNT))
                try:
                    quiz.run_session(count=int(count or config.QUIZ_DEFAULT_COUNT))
                except ValueError as exc:
                    _print(f"无法开始抽测：{exc}")
            elif choice == "9":
                _print(reviewer.format_list())
            elif choice == "10":
                fmt = _prompt("导出格式 md / csv / all", "md")
                try:
                    paths = []
                    if fmt in ("md", "all"):
                        paths.append(export_markdown(db))
                    if fmt in ("csv", "all"):
                        paths.append(export_csv(db))
                    for path in paths:
                        _print(f"已导出：{path}")
                except (ExportError, OSError) as exc:
                    _print(f"导出失败：{exc}")
            elif choice == "11":
                action = _prompt("请输入 b 备份 / r 还原 / l 查看备份", "b").lower()
                if action.startswith("r"):
                    backups = list_backups()
                    if not backups:
                        _print(f"没有可用的备份文件（{config.BACKUP_DIR}）。")
                        continue
                    _print(f"最新备份：{backups[0].name}")
                    confirm = _prompt("确认还原？将覆盖当前数据库(y/N)", "n")
                    if confirm.lower() not in {"y", "yes", "是"}:
                        _print("已取消还原。")
                        continue
                    result = restore_database(str(backups[0]))
                    _print(f"已从备份还原：{result['restored_from']}")
                    if result["safety_backup"]:
                        _print(f"还原前的数据已另存为：{result['safety_backup']}")
                elif action.startswith("l"):
                    backups = list_backups()
                    if not backups:
                        _print(f"暂无备份文件（{config.BACKUP_DIR}）。")
                    for path in backups:
                        _print(f"  - {path.name}")
                else:
                    _print(f"数据库已备份：{backup_database()}")
            elif choice == "12":
                cmd_list(argparse.Namespace(limit=10, wrong=False))
                _print("（上表最后一列「错题」显示「是」表示已标记，直接填该行 ID 可取消标记）")
                record_id = _prompt("要标记 / 取消标记的记录 ID")
                if not record_id.isdigit():
                    _print("记录 ID 必须是数字。")
                    continue
                clear = _prompt("取消标记？(y/N)", "n").lower() in {"y", "yes", "是"}
                record = reviewer.mark(int(record_id), is_wrong=not clear)
                if record is None:
                    _print(f"未找到记录：{record_id}")
                else:
                    _print(f"{'已取消错题标记' if clear else '已标记为错题'}：#{record.id}")
            elif choice == "13":
                cmd_list(argparse.Namespace(limit=10, wrong=False))
                _print("（删除后无法撤销，可先用功能 11 备份数据库）")
                record_id = _prompt("要删除的记录 ID")
                if not record_id.isdigit():
                    _print("记录 ID 必须是数字。")
                    continue
                cmd_delete(argparse.Namespace(id=int(record_id), yes=False))
            elif choice in {"0", "q", "quit", "exit"}:
                _print("已退出 CEATS，祝你早日上岸！")
                break
            else:
                _print("无效的编号，请输入 0-13。")
        except RecordError as exc:
            _print(f"输入有误：{exc}")
        except PlanError as exc:
            _print(f"输入有误：{exc}")
        except KnowledgeBaseError as exc:
            _print(f"查询失败：{exc}")
        except ExportError as exc:
            _print(f"操作失败：{exc}")
        except KeyboardInterrupt:
            _print("\n已取消当前操作。")
        except Exception as exc:  # noqa: BLE001 - 交互模式不允许因单次异常退出
            _print(f"操作失败（已捕获，程序继续运行）：{exc}")

    db.close()
    return 0


# ------------------------------------------------------------------ 参数解析
def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="ceats",
        description="CEATS 公考量化分析系统 - 命令行入口",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="初始化数据库与字典数据")
    subparsers.add_parser("menu", help="进入交互式菜单（默认）")

    record_parser = subparsers.add_parser("record", help="录入一条练习记录")
    record_parser.add_argument("--module", required=True, help="模块名称或序号")
    record_parser.add_argument("--total", required=True, help="总题数")
    record_parser.add_argument("--correct", required=True, help="对题数")
    record_parser.add_argument("--duration", required=True, help="用时，如 12:30 或 1500")
    record_parser.add_argument("--topic", default="", help="考点名称或序号")
    record_parser.add_argument("--date", default="", help="日期，默认今天")
    record_parser.add_argument("--note", default="", help="备注")
    record_parser.add_argument(
        "--wrong", action="store_true", help="标记为错题/难题，进入复盘清单"
    )

    list_parser = subparsers.add_parser("list", help="查看最近记录")
    list_parser.add_argument("--limit", type=int, default=15)
    list_parser.add_argument(
        "--wrong", action="store_true", help="只查看带错题标记的记录"
    )

    report_parser = subparsers.add_parser("report", help="生成弱项诊断报告")
    report_parser.add_argument("--days", type=int, default=0, help="统计最近 N 天")
    report_parser.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD")
    report_parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")

    chart_parser = subparsers.add_parser("chart", help="生成可视化图表")
    chart_parser.add_argument("--days", type=int, default=30, help="趋势图天数")
    chart_parser.add_argument(
        "--show", action="store_true", help="生成后用图形窗口弹出展示（答辩演示用）"
    )

    scrape_parser = subparsers.add_parser("scrape", help="抓取招考公告（--list 只看已入库）")
    scrape_parser.add_argument("--keywords", default="", help="逗号分隔的关注关键词")
    scrape_parser.add_argument("--limit", type=int, default=15, help="展示条数")
    scrape_parser.add_argument(
        "--list", action="store_true", help="只列出已入库公告，不发起网络请求"
    )

    kb_parser = subparsers.add_parser("kb", help="知识库查询")
    kb_parser.add_argument("--keyword", default="", help="查询关键词")
    kb_parser.add_argument("--category", default=None, help="按分类浏览")

    plan_parser = subparsers.add_parser("plan", help="备考倒计时与目标分拆解")
    plan_sub = plan_parser.add_subparsers(dest="plan_action")
    plan_set = plan_sub.add_parser("set", help="设置考试日期与目标总分")
    plan_set.add_argument("--date", required=True, help="考试日期 YYYY-MM-DD")
    plan_set.add_argument("--target", default=str(config.DEFAULT_TARGET_TOTAL),
                          help="目标总分（行测 + 申论，200 分制）")
    plan_set.add_argument("--essay", default=str(config.DEFAULT_ESSAY_SCORE),
                          help="申论预期得分")
    plan_set.add_argument("--name", default=config.DEFAULT_EXAM_NAME, help="考试名称")

    quiz_parser = subparsers.add_parser("quiz", help="弱项考点极速抽测闪卡")
    quiz_parser.add_argument("--count", type=int, default=config.QUIZ_DEFAULT_COUNT,
                             help="单次抽测题数")
    quiz_parser.add_argument("--category", default=None, help="限定知识库分类")
    quiz_parser.add_argument("--stats", action="store_true", help="只看历史抽测统计")

    review_parser = subparsers.add_parser("review", help="今日优先复盘清单")
    review_parser.add_argument("--days", type=int, default=config.REVIEW_RECENT_DAYS,
                               help="统计最近 N 天")
    review_parser.add_argument("--top", type=int, default=config.REVIEW_TOP_N,
                               help="输出条数")

    note_parser = subparsers.add_parser("note", help="补打 / 取消错题标记")
    note_parser.add_argument("--id", type=int, required=True, help="练习记录 ID")
    note_parser.add_argument("--clear", action="store_true", help="取消错题标记")

    delete_parser = subparsers.add_parser("delete", help="删除一条练习记录")
    delete_parser.add_argument("--id", type=int, required=True, help="练习记录 ID")
    delete_parser.add_argument(
        "--yes", action="store_true", help="跳过二次确认（脚本调用时使用）"
    )

    web_parser = subparsers.add_parser("web", help="启动本地 Web 界面")
    web_parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认仅本机")
    web_parser.add_argument("--port", type=int, default=5000, help="监听端口，默认 5000")
    web_parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")

    export_parser = subparsers.add_parser("export", help="导出诊断报告")
    export_parser.add_argument("--format", choices=["md", "csv", "all"], default="md",
                               help="导出格式，默认 Markdown")
    export_parser.add_argument("--out", default=None, help="输出文件路径（可选）")

    backup_parser = subparsers.add_parser("backup", help="一键备份数据库")
    backup_parser.add_argument("--list", action="store_true", help="列出已有备份")

    restore_parser = subparsers.add_parser("restore", help="从备份还原数据库")
    restore_parser.add_argument("--file", default="", help="备份文件路径，留空用最新备份")

    demo_parser = subparsers.add_parser("demo", help="写入演示数据")
    demo_parser.add_argument("--days", type=int, default=30, help="覆盖天数")

    return parser


def _startup_banner() -> None:
    """打印启动倒计时提醒。

    数据库不存在或读取失败时静默跳过：启动提醒属于附加信息，
    绝不能因为数据文件异常而阻断主流程。
    """
    try:
        if not Path(config.DB_PATH).exists():
            return
        with Database() as db:
            line = PlanService(db).banner()
    except Exception:  # noqa: BLE001 - 启动阶段必须保持健壮
        return
    if line:
        _print(line)


def main(argv: Optional[List[str]] = None) -> int:
    """程序主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "init": cmd_init,
        "record": cmd_record,
        "list": cmd_list,
        "report": cmd_report,
        "chart": cmd_chart,
        "scrape": cmd_scrape,
        "kb": cmd_kb,
        "plan": cmd_plan,
        "quiz": cmd_quiz,
        "review": cmd_review,
        "note": cmd_note,
        "delete": cmd_delete,
        "web": cmd_web,
        "export": cmd_export,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "demo": cmd_demo,
        "menu": cmd_menu,
        None: cmd_menu,
    }
    if args.command != "init":
        _startup_banner()
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
