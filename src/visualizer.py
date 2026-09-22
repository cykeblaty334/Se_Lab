# -*- coding: utf-8 -*-
"""展示层：数据可视化模块。

对应需求 FR-ANA-01，使用 Matplotlib 把抽象练习数据渲染为图表：

* ``plot_radar``   —— 五大模块能力雷达图（极坐标系实现）
* ``plot_trend``   —— 正确率 / 单题耗时双轴折线图
* ``plot_weak_bar`` —— 模块综合得分横向柱状图

所有函数均返回图片保存路径，便于 CLI 层提示用户查看。
"""

from pathlib import Path
from typing import List, Optional, Sequence

import matplotlib

import matplotlib.image as mpimg

# 图表一律先落盘（保证无图形界面/测试环境也能出图），
# 需要弹窗展示时由 display_charts() 临时切换到交互式后端。
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (需在 use 之后导入)
import numpy as np  # noqa: E402

from . import config  # noqa: E402
from .models import ModuleDiagnosis  # noqa: E402

#: 中文字体候选，按优先级尝试，避免图表出现方块乱码
_CJK_FONTS = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "PingFang SC"]
#: 弱项模块的强调色
_WEAK_COLOR = "#d9534f"
#: 正常模块的配色
_NORMAL_COLOR = "#3d7ebf"


def configure_fonts() -> str:
    """配置 Matplotlib 中文字体，返回实际选用的字体名。"""
    available = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
    for candidate in _CJK_FONTS:
        if candidate in available:
            plt.rcParams["font.sans-serif"] = [candidate]
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["axes.unicode_minus"] = False
            return candidate
    # 找不到中文字体时退回默认字体，保证程序不中断
    plt.rcParams["axes.unicode_minus"] = False
    return "default"


def _ensure_dir(save_path: Optional[Path]) -> Path:
    """确定输出路径并确保目录存在。"""
    path = Path(save_path) if save_path else config.CHART_DIR / "chart.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def plot_radar(
    diagnoses: Sequence[ModuleDiagnosis],
    save_path: Optional[Path] = None,
    title: str = "行测五大模块能力雷达图",
) -> Path:
    """绘制五角雷达图，展示各模块正确率。

    :param diagnoses: 诊断结果列表（按模块顺序传入）。
    :param save_path: 图片保存路径，默认为 data/charts/radar.png。
    :return: 实际保存路径。
    """
    configure_fonts()
    path = _ensure_dir(save_path or config.CHART_DIR / "radar.png")

    labels = [item.module_name for item in diagnoses]
    values = [item.accuracy * 100 for item in diagnoses]
    if not labels:
        labels, values = ["无数据"], [0.0]

    # 闭合极坐标：首尾相接
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    values_closed = values + values[:1]
    angles_closed = angles + angles[:1]

    fig = plt.figure(figsize=(7.2, 7.2), dpi=110)
    ax = fig.add_subplot(111, polar=True)
    ax.set_theta_offset(np.pi / 2)  # 第一个模块朝正上方
    ax.set_theta_direction(-1)      # 顺时针排列，符合阅读习惯

    ax.plot(angles_closed, values_closed, color=_NORMAL_COLOR, linewidth=2, label="正确率")
    ax.fill(angles_closed, values_closed, color=_NORMAL_COLOR, alpha=0.25)

    # 弱项用红色散点强调
    weak = [(a, v) for a, v, item in zip(angles, values, diagnoses) if item.is_weak]
    if weak:
        ax.scatter(
            [a for a, _ in weak],
            [v for _, v in weak],
            color=_WEAK_COLOR,
            s=60,
            zorder=5,
            label="弱项模块",
        )

    # 60 分参考线，直观看出哪些模块未达标
    ax.plot(
        angles_closed,
        [config.WEAK_SCORE_THRESHOLD] * len(angles_closed),
        color=_WEAK_COLOR,
        linestyle="--",
        linewidth=1,
        alpha=0.7,
        label=f"{int(config.WEAK_SCORE_THRESHOLD)} 分警戒线",
    )

    ax.set_xticks(angles)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=8, color="grey")
    ax.set_title(title, fontsize=14, pad=22)
    ax.legend(loc="upper right", bbox_to_anchor=(1.18, 1.10), fontsize=9)

    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_trend(
    series: Sequence[tuple],
    save_path: Optional[Path] = None,
    title: str = "正确率与答题效率趋势",
) -> Path:
    """绘制正确率 / 单题耗时双轴折线图。

    :param series: ``[(日期, 正确率%, 单题耗时), ...]``。
    """
    configure_fonts()
    path = _ensure_dir(save_path or config.CHART_DIR / "trend.png")

    dates = [item[0] for item in series]
    accuracy = [item[1] for item in series]
    per_question = [item[2] for item in series]

    fig, ax1 = plt.subplots(figsize=(9, 4.6), dpi=110)
    ax1.plot(dates, accuracy, marker="o", color=_NORMAL_COLOR, label="正确率(%)")
    ax1.axhline(
        config.WEAK_SCORE_THRESHOLD,
        color=_WEAK_COLOR,
        linestyle="--",
        linewidth=1,
        label=f"{int(config.WEAK_SCORE_THRESHOLD)}% 警戒线",
    )
    ax1.set_xlabel("日期")
    ax1.set_ylabel("正确率 (%)", color=_NORMAL_COLOR)
    ax1.set_ylim(0, 105)
    ax1.tick_params(axis="x", rotation=30)
    ax1.grid(alpha=0.25)

    ax2 = ax1.twinx()
    ax2.plot(
        dates,
        per_question,
        marker="s",
        linestyle="--",
        color="#f0ad4e",
        label="单题耗时(秒)",
    )
    ax2.set_ylabel("单题耗时 (秒)", color="#f0ad4e")

    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="lower left", fontsize=9)
    ax1.set_title(title, fontsize=13)

    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_weak_bar(
    diagnoses: Sequence[ModuleDiagnosis],
    save_path: Optional[Path] = None,
    title: str = "模块综合得分排名",
) -> Path:
    """绘制模块综合得分横向柱状图，弱项标红。"""
    configure_fonts()
    path = _ensure_dir(save_path or config.CHART_DIR / "weak_bar.png")

    ordered = [item for item in diagnoses if item.records > 0]
    names = [item.module_name for item in ordered][::-1]
    scores = [item.final_score for item in ordered][::-1]
    colors = [_WEAK_COLOR if item.is_weak else _NORMAL_COLOR for item in ordered][::-1]

    fig, ax = plt.subplots(figsize=(8, 4.4), dpi=110)
    ax.barh(names, scores, color=colors)
    ax.axvline(config.WEAK_SCORE_THRESHOLD, color=_WEAK_COLOR, linestyle="--", linewidth=1)
    for index, score in enumerate(scores):
        ax.text(score + 1, index, f"{score:.1f}", va="center", fontsize=9)
    ax.set_xlim(0, 110)
    ax.set_xlabel("综合得分（正确率 0.6 + 效率 0.3 + 稳定性 0.1）")
    ax.set_title(title, fontsize=13)
    ax.grid(axis="x", alpha=0.25)

    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_all(diagnoses: Sequence[ModuleDiagnosis], series: Sequence[tuple]) -> List[Path]:
    """一次性生成全部图表，返回路径列表。"""
    outputs = [plot_radar(diagnoses)]
    if series:
        outputs.append(plot_trend(series))
    if any(item.records > 0 for item in diagnoses):
        outputs.append(plot_weak_bar(diagnoses))
    return outputs


def display_charts(paths: Sequence[Path], block: bool = True) -> bool:
    """在图形窗口中弹出展示已生成的图表（供交互菜单与答辩演示使用）。

    实现要点：图片已经落盘，这里临时切换到交互式后端重新载入 PNG 展示，
    因此即使当前环境没有图形界面，也只是返回 False 而不会抛异常。

    :param paths: 由 plot_* 系列函数返回的图片路径。
    :param block: True 时阻塞直到用户关闭窗口。
    :return: 是否成功弹出窗口。
    """
    try:
        matplotlib.use("TkAgg", force=True)
    except Exception:  # noqa: BLE001 - 后端不可用时继续尝试默认后端
        pass

    figures = []
    try:
        for path in paths:
            if not Path(path).exists():
                continue
            image = mpimg.imread(str(path))
            height, width = image.shape[0], image.shape[1]
            figure = plt.figure(figsize=(width / 120, height / 120), dpi=120)
            figure.canvas.manager.set_window_title(Path(path).stem)
            axes = figure.add_axes([0, 0, 1, 1])
            axes.axis("off")
            axes.imshow(image)
            figures.append(figure)
        if not figures:
            return False
        plt.show(block=block)
        return True
    except Exception:  # noqa: BLE001 - 无图形环境时安静降级为"仅保存图片"
        return False
    finally:
        for figure in figures:
            plt.close(figure)
