# -*- coding: utf-8 -*-
"""命令行入口测试：参数解析、命令分发与交互模式容错。"""

import argparse
import builtins
from pathlib import Path

import pytest

from src import config
from src.database import Database
from src.exporter import list_backups
from src.main import (
    _prompt,
    build_parser,
    cmd_backup,
    cmd_chart,
    cmd_delete,
    cmd_demo,
    cmd_init,
    cmd_menu,
    cmd_quiz,
    cmd_record,
    cmd_report,
    cmd_restore,
    cmd_scrape,
    main,
)


@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    """把数据库、图表、导出与备份目录全部重定向到临时目录。

    EXPORT_DIR / BACKUP_DIR 在 config 导入时由 DATA_DIR 派生，
    因此必须单独替换，否则测试会写进仓库的 data/ 目录。
    """
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cli.db")
    monkeypatch.setattr(config, "CHART_DIR", tmp_path / "charts")
    monkeypatch.setattr(config, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    return tmp_path


class _InputExhausted(BaseException):
    """脚本化输入耗尽时抛出。

    必须是 BaseException 而非 Exception：``cmd_menu`` 为保持交互会话存活会
    捕获所有 Exception，若用普通异常会被吞掉并导致用例死循环。
    """


def _fake_input(monkeypatch, answers):
    """用脚本化的答案替换 input()，模拟用户键入序列。"""
    queue = list(answers)

    def _reader(prompt=""):
        if not queue:
            raise _InputExhausted(f"用户输入不足，剩余提示：{prompt}")
        return queue.pop(0)

    monkeypatch.setattr(builtins, "input", _reader)


# ------------------------------------------------------------------ 参数解析
def test_build_parser_recognizes_all_commands():
    parser = build_parser()
    assert parser.parse_args(["report", "--days", "7"]).days == 7
    assert parser.parse_args(["init"]).command == "init"
    assert parser.parse_args([]).command is None  # 无参数时进入交互菜单
    assert parser.parse_args(["kb", "--keyword", "增长率"]).keyword == "增长率"
    assert parser.parse_args(["demo", "--days", "10"]).days == 10


def test_record_requires_mandatory_arguments():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["record", "--module", "数量关系"])


def test_main_dispatches_init(cli_env, capsys):
    assert main(["init"]) == 0
    assert "数据库初始化完成" in capsys.readouterr().out


# ------------------------------------------------------------------ 命令行为
def test_cmd_demo_then_report_and_chart(cli_env, capsys):
    cmd_init(argparse.Namespace())
    assert cmd_demo(argparse.Namespace(days=10)) == 0
    assert "已写入" in capsys.readouterr().out

    db = Database()
    assert db.count_records() > 0
    assert db.get_exam_plan()["target_score"] == config.DEFAULT_TARGET_TOTAL
    assert db.get_exam_plan()["essay_score"] == config.DEFAULT_ESSAY_SCORE
    db.close()

    assert cmd_report(argparse.Namespace(days=0, start=None, end=None)) == 0
    assert "弱项诊断报告" in capsys.readouterr().out

    assert cmd_chart(argparse.Namespace(days=10)) == 0
    output = capsys.readouterr().out
    assert "图表已生成" in output
    assert (cli_env / "charts" / "radar.png").exists()


def test_cmd_chart_with_show_flag_pops_window(cli_env, monkeypatch, capsys):
    """带上 --show 时应调用弹窗展示函数（此处用桩替换，避免测试期弹窗）。"""
    import src.main as main_module

    cmd_init(argparse.Namespace())
    cmd_demo(argparse.Namespace(days=8))
    captured = {}

    def fake_display(paths, block=True):
        captured["paths"] = list(paths)
        captured["block"] = block
        return True

    monkeypatch.setattr(main_module, "display_charts", fake_display)
    capsys.readouterr()

    assert cmd_chart(argparse.Namespace(days=8, show=True)) == 0
    output = capsys.readouterr().out
    assert "已在图形窗口中打开图表" in output
    assert captured["paths"] and captured["block"] is True


def test_cmd_chart_reports_when_popup_unsupported(cli_env, monkeypatch, capsys):
    """环境不支持弹窗时给出明确提示，而不是报错。"""
    import src.main as main_module

    cmd_init(argparse.Namespace())
    cmd_demo(argparse.Namespace(days=8))
    monkeypatch.setattr(main_module, "display_charts", lambda paths, block=True: False)
    capsys.readouterr()

    assert cmd_chart(argparse.Namespace(days=8, show=True)) == 0
    assert "不支持弹窗" in capsys.readouterr().out


def test_cmd_chart_without_show_flag_does_not_popup(cli_env, monkeypatch, capsys):
    """不带 --show 时只落盘，不弹窗（默认行为适合脚本化调用）。"""
    import src.main as main_module

    cmd_init(argparse.Namespace())
    cmd_demo(argparse.Namespace(days=8))
    called = {"n": 0}

    def fake_display(paths, block=True):
        called["n"] += 1
        return True

    monkeypatch.setattr(main_module, "display_charts", fake_display)
    capsys.readouterr()

    assert cmd_chart(argparse.Namespace(days=8)) == 0
    assert called["n"] == 0


def test_cmd_chart_warns_when_data_insufficient(cli_env, capsys):
    cmd_init(argparse.Namespace())
    cmd_record(
        argparse.Namespace(
            module="资料分析",
            total="10",
            correct="8",
            duration="08:00",
            topic="",
            date="",
            note="",
        )
    )
    capsys.readouterr()
    cmd_chart(argparse.Namespace(days=30))
    assert "记录不足" in capsys.readouterr().out


def test_cmd_record_returns_error_code_on_bad_input(cli_env, capsys):
    cmd_init(argparse.Namespace())
    code = cmd_record(
        argparse.Namespace(
            module="数量关系",
            total="20",
            correct="30",
            duration="20:00",
            topic="",
            date="",
            note="",
        )
    )
    assert code == 1
    assert "录入失败" in capsys.readouterr().out


def test_cmd_quiz_does_not_create_default_plan(cli_env, monkeypatch, capsys):
    """回归 ISSUE-003：抽测不应悄悄写入用户没有设置过的备考计划。"""
    cmd_init(argparse.Namespace())
    _fake_input(monkeypatch, ["q"])
    assert cmd_quiz(argparse.Namespace(count=1, category=None, stats=False)) == 0
    assert "尚未设置备考计划" in capsys.readouterr().out

    db = Database()
    assert db.get_exam_plan() is None
    db.close()


def test_cmd_backup_refuses_empty_database(cli_env, capsys):
    """回归 ISSUE-004：没有练习记录时不应生成空快照。"""
    cmd_init(argparse.Namespace())
    assert cmd_backup(argparse.Namespace(list=False)) == 1
    assert "没有任何练习记录" in capsys.readouterr().out
    assert list_backups() == []


def test_cmd_backup_refuses_missing_database(cli_env, capsys):
    """数据库尚未初始化时不创建空文件，直接给出提示。"""
    assert cmd_backup(argparse.Namespace(list=False)) == 1
    output = capsys.readouterr().out
    assert "数据库文件不存在" in output
    assert not Path(config.DB_PATH).exists()


def test_cmd_backup_then_restore_roundtrip(cli_env, capsys):
    """备份 -> 新增记录 -> 还原，数据应回到备份时刻。"""
    cmd_init(argparse.Namespace())
    cmd_demo(argparse.Namespace(days=5))
    recorded = Database().count_records()
    capsys.readouterr()

    assert cmd_backup(argparse.Namespace(list=False)) == 0
    assert "数据库已备份" in capsys.readouterr().out

    cmd_init(argparse.Namespace())
    cmd_demo(argparse.Namespace(days=5))
    assert Database().count_records() > recorded  # 备份后数据被"误改"

    assert cmd_restore(argparse.Namespace(file="")) == 0
    output = capsys.readouterr().out
    assert "已从备份还原" in output
    assert "自动另存为" in output
    assert Database().count_records() == recorded


def test_cmd_scrape_uses_service_layer(cli_env, monkeypatch, capsys):
    """用桩对象替换 scrape_and_store，验证 CLI 与业务层的接口契约。"""
    import src.main as main_module
    from src.models import Announcement
    from src.scraper import ScrapeResult, SiteResult

    result = ScrapeResult(
        sites=[SiteResult(source="测试站", url="http://x.com", success=True, count=1)],
        announcements=[
            Announcement(None, "测试站", "2026年省考报名公告", "http://x.com/1", None, "报名", "")
        ],
    )
    monkeypatch.setattr(main_module, "scrape_and_store", lambda db, keywords=None: result)

    cmd_init(argparse.Namespace())
    assert cmd_scrape(argparse.Namespace(keywords="报名,公告", limit=5)) == 0
    output = capsys.readouterr().out
    assert "抓取完成" in output
    assert "2026年省考报名公告" in output


def test_cmd_scrape_persists_results(cli_env, monkeypatch, capsys):
    """真实调用业务层：公告需落库（验证 CLI -> scraper -> database 链路）。"""
    import src.scraper as scraper_module
    from src.models import Announcement
    from src.scraper import AnnouncementScraper, ScrapeResult, SiteResult

    class StubScraper(AnnouncementScraper):
        """本地桩：不发真实 HTTP 请求，直接返回固定页面解析结果。"""

        def __init__(self):
            super().__init__(retries=0)

        def crawl(self, sites=None, keywords=(), limit_per_site=30):
            return ScrapeResult(
                sites=[SiteResult("测试站", "http://x.com", True, count=1)],
                announcements=[
                    Announcement(
                        None, "测试站", "2026年省考报名公告", "http://x.com/1", None, "报名", ""
                    )
                ],
            )

    monkeypatch.setattr(scraper_module, "AnnouncementScraper", StubScraper)
    cmd_init(argparse.Namespace())
    assert cmd_scrape(argparse.Namespace(keywords="", limit=5)) == 0
    assert "抓取完成" in capsys.readouterr().out

    db = Database()
    assert db.count_announcements() == 1
    db.close()


# ------------------------------------------------------------------ 删除记录
def _record_one_via_cli() -> int:
    """用 CLI 录一条记录并返回其 ID，供删除相关用例复用。"""
    assert cmd_record(
        argparse.Namespace(
            module="数量关系",
            total="20",
            correct="9",
            duration="25:30",
            topic="行程问题",
            date="",
            note="",
            wrong=False,
        )
    ) == 0
    db = Database()
    record_id = db.list_records()[0].id
    db.close()
    return record_id


def test_cmd_delete_removes_record(cli_env, capsys):
    """delete --yes 应删除指定记录，并回报剩余条数。"""
    record_id = _record_one_via_cli()

    assert cmd_delete(argparse.Namespace(id=record_id, yes=True)) == 0
    output = capsys.readouterr().out
    assert "已删除记录" in output
    assert "现有 0 条练习记录" in output

    db = Database()
    assert db.count_records() == 0
    assert db.get_record(record_id) is None
    db.close()


def test_cmd_delete_missing_record_returns_error(cli_env, capsys):
    """删除不存在的 ID 时返回非零退出码，且不抛异常。"""
    assert cmd_delete(argparse.Namespace(id=999, yes=True)) == 1
    assert "未找到记录" in capsys.readouterr().out


def test_cmd_delete_cancelled_keeps_record(cli_env, monkeypatch, capsys):
    """未加 --yes 时必须经二次确认，回答 n 则数据保持不变。"""
    record_id = _record_one_via_cli()
    monkeypatch.setattr(builtins, "input", lambda prompt="": "n")

    assert cmd_delete(argparse.Namespace(id=record_id, yes=False)) == 0
    assert "已取消删除" in capsys.readouterr().out

    db = Database()
    assert db.count_records() == 1
    db.close()


def test_cmd_delete_cancelled_when_no_input(cli_env, monkeypatch, capsys):
    """无人值守（读到 EOF）时不得删除，按取消处理。"""
    record_id = _record_one_via_cli()

    def _raise_eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", _raise_eof)
    assert cmd_delete(argparse.Namespace(id=record_id, yes=False)) == 0
    assert "已取消删除" in capsys.readouterr().out

    db = Database()
    assert db.count_records() == 1
    db.close()


# ------------------------------------------------------------------ 交互模式
def test_prompt_returns_default(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt="": "")
    assert _prompt("请输入", "默认值") == "默认值"


def test_interactive_menu_full_flow(cli_env, monkeypatch, capsys):
    """走通菜单各分支，验证非法编号、异常输入均不会导致程序退出。"""
    _fake_input(
        monkeypatch,
        [
            "99",           # 非法编号 -> 提示
            "3",            # 弱项诊断（无数据）
            "5",            # 公告抓取（网络可能失败，内部降级）
            "6", "增长率",   # 知识库查询
            "6", "",        # 空关键词 -> 不查询
            "7", "国考", "2027-11-28", "80", "60",  # 设置备考计划（含申论预期分）
            "2",            # 查看记录
            "0",            # 退出
        ],
    )
    import src.main as main_module
    from src.scraper import ScrapeResult

    monkeypatch.setattr(
        main_module, "scrape_and_store", lambda db, keywords=None: ScrapeResult()
    )
    assert cmd_menu(argparse.Namespace()) == 0
    output = capsys.readouterr().out
    assert "无效的编号" in output
    assert "尚无" in output or "暂无" in output
    assert "隔年增长率" in output
    assert "已设置备考目标" in output
    assert "已退出 CEATS" in output


def test_interactive_record_via_menu(cli_env, monkeypatch, capsys):
    """交互式录入：按提示逐项输入后应成功落库。"""
    _fake_input(
        monkeypatch,
        [
            "1",           # 成绩录入
            "3",           # 数量关系
            "2",           # 第二个考点
            "20",          # 总题数
            "9",           # 对题数
            "25:30",       # 用时
            "",            # 日期默认今天
            "专项突破",      # 备注
            "y",           # 标记为错题
            "0",           # 退出
        ],
    )
    assert cmd_menu(argparse.Namespace()) == 0
    assert "已保存" in capsys.readouterr().out

    db = Database()
    assert db.count_records() == 1
    record = db.list_records()[0]
    assert record.total_questions == 20
    assert record.duration_seconds == 1530
    assert record.note == "专项突破"
    assert record.is_wrong is True
    assert db.count_wrong_records() == 1
    db.close()


def test_interactive_record_rejects_illegal_input_without_exit(cli_env, monkeypatch, capsys):
    """交互模式下非法输入只提示错误，程序继续运行。"""
    _fake_input(
        monkeypatch,
        [
            "1",
            "数量关系",   # 模块
            "",           # 考点（留空）
            "20",         # 总题数
            "about",      # 非法对题数 -> RecordError
            "20:00",      # 用时
            "",           # 日期
            "",           # 备注
            "",           # 是否标记为错题
            "0",          # 退出
        ],
    )
    assert cmd_menu(argparse.Namespace()) == 0
    assert "输入有误" in capsys.readouterr().out


def test_interactive_keyboard_interrupt_is_caught(cli_env, monkeypatch, capsys):
    """Ctrl+C 只取消当前操作，不退出程序。"""
    answers = ["3", KeyboardInterrupt, "0"]
    queue = list(answers)

    def _reader(prompt=""):
        if not queue:
            raise _InputExhausted(f"用户输入不足，剩余提示：{prompt}")
        value = queue.pop(0)
        if value is KeyboardInterrupt:
            raise KeyboardInterrupt
        return value

    monkeypatch.setattr(builtins, "input", _reader)
    assert cmd_menu(argparse.Namespace()) == 0
    output = capsys.readouterr().out
    assert "已取消当前操作" in output
    assert "已退出 CEATS" in output


def test_delete_record_via_menu(cli_env, monkeypatch, capsys):
    """菜单功能 13：非数字 ID 被拦截，合法 ID 二次确认后删除。"""
    record_id = _record_one_via_cli()
    _fake_input(
        monkeypatch,
        [
            "13", "abc",                 # 非数字 -> 提示后继续
            "13", str(record_id), "y",   # 合法 ID + 确认删除
            "0",
        ],
    )
    assert cmd_menu(argparse.Namespace()) == 0
    output = capsys.readouterr().out
    assert "记录 ID 必须是数字" in output
    assert "待删除" in output
    assert "已删除记录" in output

    db = Database()
    assert db.count_records() == 0
    db.close()
