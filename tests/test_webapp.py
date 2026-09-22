# -*- coding: utf-8 -*-
"""本地 Web 界面（Flask）路由测试。

覆盖点：

* 十个功能页在“空库”与“有数据”两种状态下都能正常渲染；
* 成绩录入的合法提交与非法输入（错误提示且不落库）；
* 练习记录的错题标记 / 取消标记 / 删除（含 ID 不存在）；
* 图表刷新、图片下载与图片缺失时的兜底跳转；
* 备考计划的设置成功与校验失败；
* 闪卡抽测的抽题与判分链路；
* 知识库的关键词检索与按分类浏览；
* 数据管理的导出、备份、还原与空库拒绝备份；
* 启动函数 main 的参数解析（运行服务被替换为桩函数，避免用例阻塞）。
"""

import webbrowser

import pytest

from src import config
from src.database import Database
from src.webapp import create_app, main


@pytest.fixture()
def web_env(tmp_path, monkeypatch):
    """把数据目录整体重定向到临时目录，并返回 Flask 测试客户端。"""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "web.db")
    monkeypatch.setattr(config, "CHART_DIR", tmp_path / "charts")
    monkeypatch.setattr(config, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    with Database() as db:
        db.seed()
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client


@pytest.fixture()
def web_with_records(web_env):
    """在临时库中写入两条练习记录，用于验证“有数据”时的页面表现。"""
    client = web_env
    client.post(
        "/record",
        data={
            "module": "数量关系",
            "topic": "行程问题",
            "total": "20",
            "correct": "9",
            "duration": "25:30",
            "note": "第一次模考",
        },
    )
    client.post(
        "/record",
        data={
            "module": "资料分析",
            "topic": "增长率",
            "total": "20",
            "correct": "17",
            "duration": "18:00",
            "is_wrong": "on",
        },
    )
    return client


# ---------------------------------------------------------------- 仪表盘
def test_dashboard_renders_on_empty_database(web_env):
    response = web_env.get("/")
    assert response.status_code == 200
    assert "备考仪表盘" in response.get_data(as_text=True)


def test_dashboard_shows_records_and_diagnosis(web_with_records):
    response = web_with_records.get("/")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "数量关系" in body
    assert "弱项诊断" in body
    assert "目标拆解" in body


# ---------------------------------------------------------------- 成绩录入
def test_record_form_lists_modules(web_env):
    response = web_env.get("/record")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "言语理解与表达" in body
    assert "用时" in body


def test_record_post_persists_and_redirects(web_env):
    response = web_env.post(
        "/record",
        data={
            "module": "判断推理",
            "topic": "逻辑判断",
            "total": "30",
            "correct": "21",
            "duration": "1:05:00",
            "record_date": "2026-09-18",
            "note": "专项",
            "is_wrong": "on",
        },
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "已保存" in body

    with Database() as db:
        assert db.count_records() == 1
        record = db.list_records()[0]
        assert record.duration_seconds == 3900
        assert record.record_date == "2026-09-18"
        assert record.is_wrong is True


def test_record_post_rejects_illegal_input(web_env):
    response = web_env.post(
        "/record",
        data={"module": "数量关系", "total": "20", "correct": "25", "duration": "25:30"},
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "录入失败" in body
    with Database() as db:
        assert db.count_records() == 0


# ---------------------------------------------------------------- 练习记录
def test_records_page_filters_wrong_records(web_with_records):
    body = web_with_records.get("/records").get_data(as_text=True)
    assert "第一次模考" in body

    wrong_body = web_with_records.get("/records?wrong=1").get_data(as_text=True)
    assert "资料分析" in wrong_body
    assert "第一次模考" not in wrong_body


def test_toggle_wrong_flag(web_with_records):
    with Database() as db:
        record_id = db.list_records()[0].id

    web_with_records.post(f"/records/{record_id}/wrong")
    with Database() as db:
        assert db.get_record(record_id).is_wrong is True

    web_with_records.post(f"/records/{record_id}/wrong", data={"clear": "1"})
    with Database() as db:
        assert db.get_record(record_id).is_wrong is False


def test_toggle_wrong_on_missing_record_flashes_error(web_with_records):
    response = web_with_records.post("/records/999/wrong", follow_redirects=True)
    assert "未找到记录" in response.get_data(as_text=True)


def test_delete_record_from_web(web_with_records):
    with Database() as db:
        record_id = db.list_records()[0].id

    response = web_with_records.post(f"/records/{record_id}/delete", follow_redirects=True)
    assert "已删除记录" in response.get_data(as_text=True)
    with Database() as db:
        assert db.get_record(record_id) is None


def test_delete_missing_record_flashes_error(web_with_records):
    response = web_with_records.post("/records/999/delete", follow_redirects=True)
    assert "未找到记录" in response.get_data(as_text=True)


# ---------------------------------------------------------------- 诊断与图表
def test_report_page_with_days_window(web_with_records):
    body = web_with_records.get("/report?days=30").get_data(as_text=True)
    assert "模块诊断明细" in body
    assert "文本版诊断报告" in body


def test_charts_page_without_files(web_env):
    body = web_env.get("/charts").get_data(as_text=True)
    assert "尚未生成" in body


def test_refresh_charts_creates_files(web_with_records):
    response = web_with_records.post("/charts/refresh", follow_redirects=True)
    assert response.status_code == 200
    assert "已重新生成" in response.get_data(as_text=True)
    for name in ("radar.png", "trend.png", "weak_bar.png"):
        assert (config.CHART_DIR / name).exists()


def test_refresh_charts_hints_when_data_insufficient(web_env):
    """记录不足时只生成雷达图，并给出补全提示。"""
    response = web_env.post("/charts/refresh", follow_redirects=True)
    body = response.get_data(as_text=True)
    assert "记录不足" in body
    assert (config.CHART_DIR / "radar.png").exists()


def test_chart_file_is_served_after_refresh(web_env):
    web_env.post("/charts/refresh")
    response = web_env.get("/charts/radar.png")
    assert response.status_code == 200
    assert response.mimetype == "image/png"


def test_missing_chart_file_redirects_with_hint(web_env):
    response = web_env.get("/charts/not-exists.png", follow_redirects=True)
    assert "图表尚未生成" in response.get_data(as_text=True)


# ---------------------------------------------------------------- 备考计划
def test_plan_page_without_plan(web_env):
    body = web_env.get("/plan").get_data(as_text=True)
    assert "尚未设置备考计划" in body


def test_plan_post_saves_and_shows_gap(web_env):
    response = web_env.post(
        "/plan",
        data={
            "exam_name": "2027 年国家公务员考试",
            "exam_date": "2027-11-28",
            "target_score": "135",
            "essay_score": "65",
        },
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)
    assert "备考计划已保存" in body
    assert "剩余时间" in body
    assert "行测可得约" in body


def test_plan_post_rejects_essay_not_less_than_target(web_env):
    response = web_env.post(
        "/plan",
        data={"exam_date": "2027-11-28", "target_score": "120", "essay_score": "130"},
        follow_redirects=True,
    )
    assert "设置失败" in response.get_data(as_text=True)


# ---------------------------------------------------------------- 复盘清单
def test_review_page_without_triggered_topics(web_env):
    body = web_env.get("/review").get_data(as_text=True)
    assert "今日优先复盘清单" in body


def test_review_page_lists_wrong_topic(web_with_records):
    body = web_with_records.get("/review").get_data(as_text=True)
    assert "资料分析" in body
    assert "优先级" in body


# ---------------------------------------------------------------- 闪卡抽测
def test_quiz_draws_questions(web_env):
    response = web_env.get("/quiz?count=2")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "请作答" in body


def test_quiz_grades_answers(web_env):
    web_env.get("/quiz?count=2")
    response = web_env.post(
        "/quiz",
        data={"answer_0": "完全不记得", "answer_1": "完全不记得"},
    )
    body = response.get_data(as_text=True)
    assert "本轮结果" in body
    assert "标准答案" in body

    with Database() as db:
        assert db.quiz_stats(days=30)["attempts"] >= 1


def test_quiz_post_without_session_flashes(web_env):
    response = web_env.post("/quiz", data={}, follow_redirects=True)
    assert "本轮题目已失效" in response.get_data(as_text=True)


# ---------------------------------------------------------------- 知识库
def test_knowledge_search_by_keyword(web_env):
    body = web_env.get("/knowledge?q=增长率").get_data(as_text=True)
    assert "隔年增长率" in body


def test_knowledge_browse_by_category(web_env):
    body = web_env.get("/knowledge?category=公式").get_data(as_text=True)
    assert "增长率" in body


def test_knowledge_empty_result_hint(web_env):
    body = web_env.get("/knowledge?q=不存在的关键词xyz").get_data(as_text=True)
    assert "未找到匹配条目" in body


# ---------------------------------------------------------------- 数据管理
def test_data_page_shows_totals(web_with_records):
    body = web_with_records.get("/data").get_data(as_text=True)
    assert "数据管理" in body
    assert "备份与还原" in body


def test_export_reports(web_with_records):
    response = web_with_records.post(
        "/data/export", data={"format": "all"}, follow_redirects=True
    )
    body = response.get_data(as_text=True)
    assert "导出完成" in body
    assert list(config.EXPORT_DIR.glob("*.md"))
    assert list(config.EXPORT_DIR.glob("*.csv"))


def test_backup_and_restore_roundtrip(web_with_records):
    response = web_with_records.post("/data/backup", follow_redirects=True)
    assert "数据库已备份" in response.get_data(as_text=True)

    response = web_with_records.post("/data/restore", follow_redirects=True)
    body = response.get_data(as_text=True)
    assert "已从备份还原" in body
    with Database() as db:
        assert db.count_records() == 2


def test_backup_refuses_empty_database(web_env):
    response = web_env.post("/data/backup", follow_redirects=True)
    assert "空快照没有意义" in response.get_data(as_text=True)


def test_restore_without_backup_flashes_hint(web_env):
    response = web_env.post("/data/restore", follow_redirects=True)
    assert "没有可用的备份文件" in response.get_data(as_text=True)


# ---------------------------------------------------------------- 启动函数
def test_main_starts_server_with_stubbed_run(monkeypatch):
    """用桩替换 Flask.run 与 webbrowser.open，验证启动参数传递与提示输出。"""
    called = {}

    def fake_run(self, host=None, port=None, debug=None):
        called["host"] = host
        called["port"] = port
        called["debug"] = debug

    monkeypatch.setattr("flask.Flask.run", fake_run)
    monkeypatch.setattr(webbrowser, "open", lambda url: called.setdefault("url", url))

    assert main(["--host", "127.0.0.1", "--port", "5123", "--open"]) == 0
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 5123
    assert called["debug"] is False
    assert called["url"].endswith(":5123/")


def test_main_uses_default_port_without_open(monkeypatch, capsys):
    monkeypatch.setattr("flask.Flask.run", lambda self, host=None, port=None, debug=None: None)
    monkeypatch.setattr(webbrowser, "open", lambda url: pytest.fail("不应打开浏览器"))

    assert main([]) == 0
    assert "127.0.0.1:5000" in capsys.readouterr().out
