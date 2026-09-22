# -*- coding: utf-8 -*-
"""展示层：CEATS 本地 Web 界面（Flask）。

设计约定：

1. **只监听回环地址**（127.0.0.1），练习数据不出本机，满足 NFR-SEC-01；
2. **展示层不写 SQL、不写业务规则**，全部调用 recorder / analyzer / planner /
   quiz / reviewer / exporter / knowledge 等业务模块，与 CLI 共用同一套 Service；
3. 图表直接复用 visualizer 生成的 PNG（matplotlib 已固定 Agg 后端），
   因此服务进程不依赖图形界面，也不会弹窗。

启动方式::

    python -m src.main web            # 推荐：从统一入口启动
    python -m src.webapp --port 5000  # 也可单独启动
"""

import argparse
import sys
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from . import config
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
from .planner import PlanError, PlanService
from .quiz import QuizQuestion, QuizService
from .recorder import RecordError, RecordService, build_feedback
from .reviewer import ReviewService
from .visualizer import plot_all

#: 页面导航配置：(路由名, 菜单文字, 说明)
NAV_ITEMS = (
    ("dashboard", "仪表盘", "关键指标与三张分析图"),
    ("record", "成绩录入", "录入一次练习并即时反馈"),
    ("records", "练习记录", "查看、标错题与删除"),
    ("report", "弱项诊断", "模块/考点两级的量化结论"),
    ("charts", "可视化图表", "雷达图 / 趋势图 / 排名图"),
    ("plan", "备考计划", "倒计时与目标分拆解"),
    ("review", "今日复盘", "优先复习清单与知识卡片"),
    ("quiz", "闪卡抽测", "手打作答并自动判分"),
    ("knowledge", "知识库", "公式 / 技巧 / 申论模板检索"),
    ("data", "数据管理", "导出报告与备份还原"),
)

#: 图表文件名（与 visualizer 的输出保持一致）
CHART_FILES = ("radar.png", "trend.png", "weak_bar.png")


def create_app() -> Flask:
    """创建 Flask 应用（工厂函数，便于测试时反复构造）。"""
    app = Flask(__name__)
    # 本地单机使用，密钥仅用于 flash 消息，不涉及任何远程会话
    app.config["SECRET_KEY"] = "ceats-local-session-key"
    app.config["JSON_AS_ASCII"] = False

    # ------------------------------------------------------------ 公共上下文
    @app.context_processor
    def inject_common():
        with Database() as db:
            banner = PlanService(db).banner()
            analyzer = Analyzer(db)
            ready = analyzer.ready_for_radar()
        return {
            "nav_items": NAV_ITEMS,
            "countdown_banner": banner,
            "has_enough_records": ready,
            "chart_files": CHART_FILES,
        }

    # ------------------------------------------------------------ 仪表盘
    @app.route("/")
    def dashboard():
        with Database() as db:
            analyzer = Analyzer(db)
            overall = analyzer.overall()
            diagnoses = analyzer.diagnose_modules()
            weak = [item for item in diagnoses if item.is_weak][:3]
            recent = RecordService(db).recent(8)
            plan = PlanService(db).current()
            rows = PlanService(db).target_table()
            stats = QuizService(db).stats(days=30)
        charts = _existing_charts()
        return render_template(
            "index.html",
            overall=overall,
            diagnoses=diagnoses,
            weak=weak,
            recent=recent,
            plan=plan,
            target_rows=rows[:5],
            quiz_stats=stats,
            charts=charts,
        )

    # ------------------------------------------------------------ 成绩录入
    @app.route("/record", methods=["GET", "POST"])
    def record():
        with Database() as db:
            service = RecordService(db)
            modules = service.modules()
            if request.method == "POST":
                try:
                    saved = service.submit(
                        module_raw=request.form.get("module", ""),
                        total_raw=request.form.get("total", ""),
                        correct_raw=request.form.get("correct", ""),
                        duration_raw=request.form.get("duration", ""),
                        topic_raw=request.form.get("topic", ""),
                        date_raw=request.form.get("record_date", ""),
                        note=request.form.get("note", ""),
                        is_wrong=request.form.get("is_wrong") == "on",
                    )
                except RecordError as exc:
                    flash(f"录入失败：{exc}", "error")
                else:
                    flash(build_feedback(saved), "ok")
                    return redirect(url_for("records"))
            topics = []
            for module in modules:
                topics.extend(service.topics(module.id))
        return render_template("record_form.html", modules=modules, topics=topics)

    # ------------------------------------------------------------ 练习记录
    @app.route("/records")
    def records():
        limit = request.args.get("limit", type=int) or 20
        only_wrong = request.args.get("wrong") == "1"
        with Database() as db:
            service = RecordService(db)
            items = (
                ReviewService(db).wrong_records(limit)
                if only_wrong
                else service.recent(limit)
            )
            total = db.count_records()
            wrong_total = db.count_wrong_records()
        return render_template(
            "records.html",
            records=items,
            total=total,
            wrong_total=wrong_total,
            limit=limit,
            only_wrong=only_wrong,
        )

    @app.post("/records/<int:record_id>/delete")
    def delete_record(record_id: int):
        with Database() as db:
            record = db.get_record(record_id)
            if record is None:
                flash(f"未找到记录：{record_id}", "error")
            else:
                db.delete_record(record_id)
                flash(f"已删除记录 #{record_id}，剩余 {db.count_records()} 条练习记录。", "ok")
        return redirect(url_for("records"))

    @app.post("/records/<int:record_id>/wrong")
    def toggle_wrong(record_id: int):
        with Database() as db:
            clear = request.form.get("clear") == "1"
            updated = ReviewService(db).mark(record_id, is_wrong=not clear)
        if updated is None:
            flash(f"未找到记录：{record_id}", "error")
        else:
            flash(f"{'已取消错题标记' if clear else '已标记为错题'}：#{record_id}", "ok")
        return redirect(url_for("records"))

    # ------------------------------------------------------------ 诊断与图表
    @app.route("/report")
    def report():
        days = request.args.get("days", type=int) or 0
        with Database() as db:
            analyzer = Analyzer(db)
            start = None
            if days:
                start = (date.today() - timedelta(days=days)).isoformat()
            diagnoses = analyzer.diagnose_modules()
            slow = analyzer.slow_modules()
            overall = analyzer.overall(start)
            text = analyzer.text_report(start)
        return render_template(
            "report.html",
            diagnoses=diagnoses,
            slow=slow,
            overall=overall,
            text_report=text,
            days=days,
        )

    @app.route("/charts")
    def charts():
        return render_template("charts.html", charts=_existing_charts())

    @app.post("/charts/refresh")
    def refresh_charts():
        with Database() as db:
            analyzer = Analyzer(db)
            ready = analyzer.ready_for_radar()
            paths = plot_all(analyzer.diagnose_modules(), analyzer.trend(days=30))
        flash(f"已重新生成 {len(paths)} 张图表。", "ok")
        if not ready:
            flash(
                f"提示：当前练习记录不足 {config.MIN_RECORDS_FOR_RADAR} 条，"
                "趋势图与排名图会在数据充足后自动补全。",
                "error",
            )
        return redirect(url_for("charts"))

    @app.route("/charts/<path:filename>")
    def chart_file(filename: str):
        """对外提供图表 PNG（仅限图表目录内的文件）。"""
        directory = Path(config.CHART_DIR)
        if not (directory / filename).exists():
            flash(f"图表尚未生成：{filename}，请点击“重新生成图表”。", "error")
            return redirect(url_for("charts"))
        return send_from_directory(directory, filename)

    # ------------------------------------------------------------ 备考计划
    @app.route("/plan", methods=["GET", "POST"])
    def plan():
        with Database() as db:
            service = PlanService(db)
            if request.method == "POST":
                try:
                    service.set_plan(
                        exam_name=request.form.get("exam_name", ""),
                        exam_date_raw=request.form.get("exam_date", ""),
                        target_raw=request.form.get("target_score", ""),
                        essay_raw=request.form.get("essay_score", ""),
                    )
                except PlanError as exc:
                    flash(f"设置失败：{exc}", "error")
                else:
                    flash("备考计划已保存。", "ok")
                    return redirect(url_for("plan"))
            current = service.current()
            rows = service.target_table()
            estimated = service.estimated_xingce_score()
        return render_template(
            "plan.html",
            plan=current,
            rows=rows,
            estimated=estimated,
            default_name=config.DEFAULT_EXAM_NAME,
            default_date=config.DEFAULT_EXAM_DATE,
            default_target=config.DEFAULT_TARGET_TOTAL,
            default_essay=config.DEFAULT_ESSAY_SCORE,
        )

    # ------------------------------------------------------------ 复盘清单
    @app.route("/review")
    def review():
        days = request.args.get("days", type=int) or config.REVIEW_RECENT_DAYS
        with Database() as db:
            service = ReviewService(db)
            items = service.review_items(days=days)
            enriched = [
                {
                    "item": item,
                    "references": service.references_for(item.topic_name),
                }
                for item in items
            ]
            wrong = service.wrong_records(limit=10)
            wrong_total = db.count_wrong_records()
            weak_keywords = db.quiz_weak_keywords(limit=3)
        return render_template(
            "review.html",
            rows=enriched,
            wrong_records=wrong,
            wrong_total=wrong_total,
            weak_keywords=weak_keywords,
            days=days,
        )

    # ------------------------------------------------------------ 闪卡抽测
    @app.route("/quiz", methods=["GET", "POST"])
    def quiz():
        with Database() as db:
            service = QuizService(db)
            if request.method == "POST":
                questions = _questions_from_session()
                answers = [
                    request.form.get(f"answer_{index}", "")
                    for index in range(len(questions))
                ]
                if not questions:
                    flash("本轮题目已失效，请重新抽题。", "error")
                    return redirect(url_for("quiz"))
                results = [
                    service.submit(question, answer)
                    for question, answer in zip(questions, answers)
                ]
                graded = [
                    {"result": result, "expected": result.question.expected}
                    for result in results
                ]
                summary = QuizService.summary_text(results)
                session.pop("quiz_questions", None)
                return render_template("quiz.html", graded=graded, summary=summary)
            try:
                count = request.args.get("count", type=int) or config.QUIZ_DEFAULT_COUNT
                questions = service.draw(count=count, category=request.args.get("category"))
            except ValueError as exc:
                flash(str(exc), "error")
                questions = []
            else:
                session["quiz_questions"] = [_question_to_dict(q) for q in questions]
            categories = sorted({item.category for item in service.pool()})
            stats = service.stats_text(days=30)
        return render_template(
            "quiz.html",
            questions=questions,
            graded=[],
            summary="",
            categories=categories,
            stats=stats,
        )

    # ------------------------------------------------------------ 知识库
    @app.route("/knowledge")
    def knowledge():
        keyword = (request.args.get("q") or "").strip()
        category = request.args.get("category") or None
        with Database() as db:
            base = KnowledgeBase(db)
            categories = base.categories()
            if keyword:
                try:
                    items = base.search(keyword)
                except KnowledgeBaseError as exc:
                    flash(str(exc), "error")
                    items = []
            else:
                items = base.browse(category)
        return render_template(
            "knowledge.html",
            items=items,
            categories=categories,
            keyword=keyword,
            category=category or "",
        )

    # ------------------------------------------------------------ 数据管理
    @app.route("/data")
    def data():
        with Database() as db:
            totals = {
                "records": db.count_records(),
                "wrong": db.count_wrong_records(),
                "knowledge": len(db.list_knowledge()),
            }
        export_dir = Path(config.EXPORT_DIR)
        exports = sorted(export_dir.glob("*"), reverse=True)[:6] if export_dir.exists() else []
        return render_template(
            "data.html",
            totals=totals,
            backups=list_backups()[:6],
            exports=exports,
            db_path=config.DB_PATH,
        )

    @app.post("/data/export")
    def data_export():
        fmt = request.form.get("format", "all")
        try:
            with Database() as db:
                paths = []
                if fmt in ("md", "all"):
                    paths.append(export_markdown(db))
                if fmt in ("csv", "all"):
                    paths.append(export_csv(db))
        except (ExportError, OSError) as exc:
            flash(f"导出失败：{exc}", "error")
        else:
            flash("导出完成：" + "、".join(Path(path).name for path in paths), "ok")
        return redirect(url_for("data"))

    @app.post("/data/backup")
    def data_backup():
        with Database() as db:
            if db.count_records() == 0:
                flash("备份失败：当前数据库还没有任何练习记录，空快照没有意义。", "error")
                return redirect(url_for("data"))
        try:
            path = backup_database()
        except ExportError as exc:
            flash(f"备份失败：{exc}", "error")
        else:
            flash(f"数据库已备份：{Path(path).name}", "ok")
        return redirect(url_for("data"))

    @app.post("/data/restore")
    def data_restore():
        backups = list_backups()
        if not backups:
            flash("没有可用的备份文件，请先执行备份。", "error")
            return redirect(url_for("data"))
        try:
            result = restore_database(str(backups[0]))
        except ExportError as exc:
            flash(f"还原失败：{exc}", "error")
        else:
            message = f"已从备份还原：{Path(str(result['restored_from'])).name}"
            if result["safety_backup"]:
                message += f"；还原前的数据库已另存为 {Path(str(result['safety_backup'])).name}"
            flash(message, "ok")
        return redirect(url_for("data"))

    return app


# ------------------------------------------------------------------ 内部工具
def _existing_charts() -> List[dict]:
    """返回已经生成好的图表（文件名与用途）。"""
    labels = {
        "radar.png": "五角能力雷达图",
        "trend.png": "正确率 / 耗时趋势图",
        "weak_bar.png": "模块综合得分排名图",
    }
    directory = Path(config.CHART_DIR)
    charts = []
    for name in CHART_FILES:
        path = directory / name
        charts.append(
            {
                "name": name,
                "label": labels.get(name, name),
                "exists": path.exists(),
                "mtime": (
                    datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    if path.exists()
                    else ""
                ),
            }
        )
    return charts


def _question_to_dict(question: QuizQuestion) -> dict:
    """把题目转成可存入 session 的普通字典。"""
    return {
        "item_id": question.item_id,
        "keyword": question.keyword,
        "category": question.category,
        "question": question.question,
        "expected": question.expected,
        "example": question.example,
    }


def _questions_from_session() -> List[QuizQuestion]:
    """从 session 还原题目列表。"""
    return [QuizQuestion(**raw) for raw in session.get("quiz_questions", [])]


def main(argv: Optional[List[str]] = None) -> int:
    """启动本地 Web 服务（默认 http://127.0.0.1:5000）。"""
    parser = argparse.ArgumentParser(prog="ceats-web", description="CEATS 本地 Web 界面")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认仅本机")
    parser.add_argument("--port", type=int, default=5000, help="监听端口，默认 5000")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = parser.parse_args(argv)

    app = create_app()
    url = f"http://{args.host}:{args.port}/"
    print("=" * 60)
    print(" CEATS 公考量化分析系统 · 本地 Web 界面")
    print("=" * 60)
    print(f" 访问地址：{url}")
    print(f" 数据文件：{config.DB_PATH}")
    print(" 提示：服务只监听本机地址，练习数据不会离开这台电脑；按 Ctrl+C 退出。")
    print("=" * 60)
    if args.open:
        webbrowser.open(url)
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
