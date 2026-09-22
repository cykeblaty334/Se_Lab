# -*- coding: utf-8 -*-
"""可视化模块单元测试：图表文件生成与数据不足时的容错。"""

from src.analyzer import Analyzer
from src.models import ModuleDiagnosis
from src.visualizer import configure_fonts, plot_all, plot_radar, plot_trend, plot_weak_bar


def test_configure_fonts_returns_name():
    assert isinstance(configure_fonts(), str)


def test_plot_radar_creates_file(sample_records, tmp_path):
    db, _ = sample_records
    diagnoses = Analyzer(db).diagnose_modules()
    path = plot_radar(diagnoses, save_path=tmp_path / "radar.png")
    assert path.exists()
    assert path.stat().st_size > 1000  # 确认写入的是真实图片而非空文件


def test_plot_trend_creates_file(sample_records, tmp_path):
    db, _ = sample_records
    series = Analyzer(db).trend(days=30)
    path = plot_trend(series, save_path=tmp_path / "trend.png")
    assert path.exists()
    assert path.stat().st_size > 1000


def test_plot_weak_bar_creates_file(sample_records, tmp_path):
    db, _ = sample_records
    diagnoses = Analyzer(db).diagnose_modules()
    path = plot_weak_bar(diagnoses, save_path=tmp_path / "bar.png")
    assert path.exists()


def test_plot_radar_handles_empty_diagnosis(tmp_path):
    """无数据时雷达图仍需生成（以「无数据」占位），不得抛异常。"""
    path = plot_radar([], save_path=tmp_path / "empty.png")
    assert path.exists()


def test_plot_trend_handles_empty_series(tmp_path):
    path = plot_trend([], save_path=tmp_path / "empty_trend.png")
    assert path.exists()


def test_plot_all_generates_multiple_charts(sample_records, tmp_path, monkeypatch):
    """plot_all 应同时产出雷达图、趋势图与排名图。"""
    from src import config

    monkeypatch.setattr(config, "CHART_DIR", tmp_path)
    db, _ = sample_records
    analyzer = Analyzer(db)
    outputs = plot_all(analyzer.diagnose_modules(), analyzer.trend(days=30))
    names = {path.name for path in outputs}
    assert {"radar.png", "trend.png", "weak_bar.png"} == names
    assert all(path.exists() for path in outputs)


def test_plot_all_skips_charts_without_data(tmp_path, monkeypatch):
    """无记录时仅生成雷达图，避免产出无意义的空白图表。"""
    from src import config

    monkeypatch.setattr(config, "CHART_DIR", tmp_path)
    diagnoses = [
        ModuleDiagnosis(module_id=1, module_name="数量关系"),
        ModuleDiagnosis(module_id=2, module_name="资料分析"),
    ]
    outputs = plot_all(diagnoses, [])
    assert [path.name for path in outputs] == ["radar.png"]


def test_weak_module_marked_in_radar(sample_records, tmp_path):
    """含弱项时雷达图仍能正常渲染（覆盖弱项散点分支）。"""
    db, _ = sample_records
    diagnoses = Analyzer(db).diagnose_modules()
    assert any(item.is_weak for item in diagnoses)
    path = plot_radar(diagnoses, save_path=tmp_path / "radar_weak.png", title="弱项雷达图")
    assert path.exists()


# ---------------------------------------------------------------- 弹窗展示
def test_display_charts_shows_saved_images(sample_records, tmp_path, monkeypatch):
    """弹窗展示：应从已保存的 PNG 重新载入并弹出窗口（此处替换掉后端切换与 show）。"""
    from src import visualizer

    db, _ = sample_records
    paths = [
        visualizer.plot_radar(Analyzer(db).diagnose_modules(), save_path=tmp_path / "r.png"),
        visualizer.plot_weak_bar(Analyzer(db).diagnose_modules(), save_path=tmp_path / "b.png"),
    ]
    # 保持 Agg 后端并屏蔽阻塞式 show，避免测试期间真的弹出窗口
    monkeypatch.setattr(visualizer.matplotlib, "use", lambda *args, **kwargs: None)
    monkeypatch.setattr(visualizer.plt, "show", lambda *args, **kwargs: None)

    assert visualizer.display_charts(paths) is True


def test_display_charts_returns_false_without_files(tmp_path, monkeypatch):
    """文件不存在时安静返回 False，不抛异常。"""
    from src import visualizer

    monkeypatch.setattr(visualizer.matplotlib, "use", lambda *args, **kwargs: None)
    assert visualizer.display_charts([tmp_path / "not_exist.png"]) is False


def test_display_charts_swallows_backend_errors(tmp_path, monkeypatch):
    """后端不可用（如无图形界面）时降级为返回 False，保证主流程不中断。"""
    from src import visualizer

    good_path = plot_radar([], save_path=tmp_path / "ok.png")

    def boom(*args, **kwargs):
        raise RuntimeError("no display")

    monkeypatch.setattr(visualizer.matplotlib, "use", lambda *args, **kwargs: None)
    monkeypatch.setattr(visualizer.plt, "figure", boom)
    assert visualizer.display_charts([good_path]) is False
