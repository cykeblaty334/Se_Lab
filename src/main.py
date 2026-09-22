# -*- coding: utf-8 -*-
"""展示层：命令行交互入口。

统一入口支持两种使用方式：

1. 交互模式（默认）：``python -m src.main`` 进入菜单，适合日常备考录入；
2. 命令模式：``python -m src.main report --days 30`` 适合脚本化/演示。

命令清单：
    init     初始化数据库（建表 + 写入模块/考点/知识库字典）
    record   录入一条练习记录
    list     查看最近练习记录
    report   生成文本诊断报告
    chart    生成雷达图 / 趋势图 / 得分排名图
    scrape   抓取招考公告（失败自动降级为链接导航）
    kb       知识库检索 / 浏览
    demo     写入一批演示数据，便于演示与出图
    menu     进入交互式菜单
"""

import argparse
import random
import sys
from datetime import date, timedelta
from typing import List, Optional

from . import config
from .analyzer import Analyzer
from .database import Database
from .knowledge import KnowledgeBase, KnowledgeBaseError
from .recorder import RecordError, RecordService, build_feedback
from .scraper import scrape_and_store
from .visualizer import display_charts, plot_all

#: 交互菜单文本
MENU_TEXT = """
============================================================
 CEATS 公考量化分析系统  v1.0.0
============================================================
 1. 成绩录入        2. 查看历史记录     3. 弱项诊断报告
 4. 生成可视化图表  5. 招考公告抓取     6. 知识库查询
 7. 备考目标设置    0. 退出
============================================================"""


def _print(text: str = "") -> None:
    """统一输出封装，便于后续替换为日志。"""
    print(text)


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
        )
    except RecordError as exc:
        _print(f"录入失败：{exc}")
        db.close()
        return 1
    _print(build_feedback(record))
    db.close()
    return 0


def cmd_list(args) -> int:
    """查看最近的练习记录。"""
    db = Database()
    records = db.list_records(limit=args.limit)
    if not records:
        _print("暂无练习记录。")
        db.close()
        return 0
    _print(f"{'ID':<5}{'日期':<12}{'模块':<16}{'考点':<12}{'对/总':<9}{'正确率':<9}{'单题':<6}")
    _print("-" * 74)
    for record in records:
        topic = record.topic_name or "-"
        ratio = f"{record.correct_questions}/{record.total_questions}"
        _print(
            f"{record.id:<5}{record.record_date:<12}{record.module_name:<16}"
            f"{topic:<12}{ratio:<9}{record.accuracy * 100:>6.1f}%"
            f"{record.seconds_per_question:>8.1f}s"
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
    """抓取招考公告并入库。"""
    db = Database()
    keywords = args.keywords.split(",") if args.keywords else None
    result = scrape_and_store(db, keywords=keywords)
    _print(result.summary())
    _print("-" * 60)
    for index, item in enumerate(result.announcements[: args.limit], start=1):
        tag = f"[{item.matched_keyword}]" if item.matched_keyword else ""
        _print(f"{index:>2}. {tag}{item.title}\n    {item.url}")
    _print(f"数据库中累计公告：{db.count_announcements()} 条")
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
            )
            inserted += 1
    db.set_exam_plan("2027 年国家公务员考试", "2027-11-28", 75.0)
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

    record = service.submit(
        module_raw=module_raw,
        total_raw=total_raw,
        correct_raw=correct_raw,
        duration_raw=duration_raw,
        topic_raw=topic_raw,
        date_raw=date_raw,
        note=note,
    )
    _print()
    _print(build_feedback(record))


def cmd_menu(args) -> int:
    """交互式主菜单。"""
    db = Database()
    db.seed()
    analyzer = Analyzer(db)
    kb = KnowledgeBase(db)

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
                for index, item in enumerate(result.announcements[:10], start=1):
                    _print(f"{index:>2}. {item.title}\n    {item.url}")
            elif choice == "6":
                keyword = _prompt("请输入关键词（如 隔年增长率 / 申论）")
                if keyword:
                    _print(KnowledgeBase.format_items(kb.search(keyword)))
            elif choice == "7":
                name = _prompt("考试名称", "2027 年国家公务员考试")
                exam_date = _prompt("考试日期（YYYY-MM-DD）", "2027-11-28")
                score = _prompt("目标分数", "75")
                db.set_exam_plan(name, exam_date, float(score))
                _print(f"已设置备考目标：{name} @ {exam_date}，目标 {score} 分")
            elif choice in {"0", "q", "quit", "exit"}:
                _print("已退出 CEATS，祝你早日上岸！")
                break
            else:
                _print("无效的编号，请输入 0-7。")
        except RecordError as exc:
            _print(f"输入有误：{exc}")
        except KnowledgeBaseError as exc:
            _print(f"查询失败：{exc}")
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

    list_parser = subparsers.add_parser("list", help="查看最近记录")
    list_parser.add_argument("--limit", type=int, default=15)

    report_parser = subparsers.add_parser("report", help="生成弱项诊断报告")
    report_parser.add_argument("--days", type=int, default=0, help="统计最近 N 天")
    report_parser.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD")
    report_parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")

    chart_parser = subparsers.add_parser("chart", help="生成可视化图表")
    chart_parser.add_argument("--days", type=int, default=30, help="趋势图天数")
    chart_parser.add_argument(
        "--show", action="store_true", help="生成后用图形窗口弹出展示（答辩演示用）"
    )

    scrape_parser = subparsers.add_parser("scrape", help="抓取招考公告")
    scrape_parser.add_argument("--keywords", default="", help="逗号分隔的关注关键词")
    scrape_parser.add_argument("--limit", type=int, default=15, help="展示条数")

    kb_parser = subparsers.add_parser("kb", help="知识库查询")
    kb_parser.add_argument("--keyword", default="", help="查询关键词")
    kb_parser.add_argument("--category", default=None, help="按分类浏览")

    demo_parser = subparsers.add_parser("demo", help="写入演示数据")
    demo_parser.add_argument("--days", type=int, default=30, help="覆盖天数")

    return parser


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
        "demo": cmd_demo,
        "menu": cmd_menu,
        None: cmd_menu,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
