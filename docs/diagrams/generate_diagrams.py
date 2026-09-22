# -*- coding: utf-8 -*-
"""
CEATS 公考量化分析系统 —— UML / 设计图批量生成脚本。

本脚本仅依赖 matplotlib（不依赖 networkx / graphviz / pydot），
全部图形使用 patches（FancyBboxPatch / Ellipse / FancyArrowPatch / Circle / Line2D）
手工绘制，坐标系使用 ax.set_xlim / ax.set_ylim + ax.axis("off")。

运行方式:
    python generate_diagrams.py

输出:
    9 张 PNG，统一写入 OUT_DIR（d:\\ruangongshiyan\\docs\\diagrams）,
    保存参数为 dpi=140, bbox_inches="tight", facecolor="white"。
"""

import math
import os

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import (Circle, Ellipse, FancyArrowPatch, FancyBboxPatch,
                                Polygon, Rectangle)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

# ----------------------------------------------------------------------------
# 全局配置
# ----------------------------------------------------------------------------
# 输出目录默认为脚本所在目录，便于把本文件连同图片一起复制到任意位置后直接运行
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 配色
C_EDGE = "#2F5597"          # 普通方框描边
C_FILL = "#EAF1FB"          # 普通方框填充
C_UC_FILL = "#FFF2CC"       # 用例椭圆填充
C_UC_EDGE = "#BF8F00"       # 用例椭圆描边
C_ACTOR = "#3F3F3F"         # 参与者（火柴人）
C_MOD_FILL = "#E2EFDA"      # 模块框
C_MOD_EDGE = "#548235"
C_GRAY = "#595959"
C_RED = "#C00000"
C_LINE = "#333333"
C_NOTE = "#7F7F7F"

FS_TITLE = 13
FS_BODY = 10
FS_SMALL = 9


# ----------------------------------------------------------------------------
# 公共绘图工具
# ----------------------------------------------------------------------------
def fig_ax(w, h, xlim, ylim, title=None, subtitle=None):
    """创建画布：返回 (fig, ax)，关闭坐标轴并设置数据范围。"""
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=FS_TITLE, fontweight="bold", pad=14, color="#1F3864")
    if subtitle:
        ax.text((xlim[0] + xlim[1]) / 2.0, ylim[1] - (ylim[1] - ylim[0]) * 0.012,
                subtitle, ha="center", va="top", fontsize=FS_BODY, color=C_GRAY)
    return fig, ax


def save(fig, name):
    """保存图片到 OUT_DIR 并关闭 figure，返回完整路径。"""
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def box(ax, cx, cy, w, h, text="", fs=FS_BODY, fc=C_FILL, ec=C_EDGE, lw=1.3, ls="-",
        tc="#1F1F1F", round_=False, bold=False, z=3, rs=0.28, alpha=1.0):
    """绘制矩形（或圆角矩形）并居中写文字；(cx, cy) 为矩形中心。"""
    style = "round,pad=0,rounding_size=%.2f" % rs if round_ else "square,pad=0"
    ax.add_patch(FancyBboxPatch((cx - w / 2.0, cy - h / 2.0), w, h, boxstyle=style,
                                fc=fc, ec=ec, lw=lw, linestyle=ls, zorder=z, alpha=alpha))
    if text:
        ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, color=tc,
                zorder=z + 1, fontweight="bold" if bold else "normal", linespacing=1.4)


def ellipse(ax, cx, cy, w, h, text="", fs=FS_BODY, fc=C_UC_FILL, ec=C_UC_EDGE, lw=1.3, z=3):
    """绘制 UML 用例椭圆。"""
    ax.add_patch(Ellipse((cx, cy), w, h, fc=fc, ec=ec, lw=lw, zorder=z))
    if text:
        ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, color="#1F1F1F",
                zorder=z + 1, linespacing=1.35)


def diamond(ax, cx, cy, w, h, text="", fs=FS_SMALL, fc="#FCE4EC", ec="#C2185B", z=3):
    """绘制流程图判断菱形。"""
    pts = [(cx, cy + h / 2.0), (cx + w / 2.0, cy), (cx, cy - h / 2.0), (cx - w / 2.0, cy)]
    ax.add_patch(Polygon(pts, closed=True, fc=fc, ec=ec, lw=1.3, zorder=z))
    if text:
        ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, color="#1F1F1F",
                zorder=z + 1, linespacing=1.4)


def para(ax, cx, cy, w, h, text="", fs=FS_SMALL, fc="#E1F5FE", ec="#0277BD", z=3):
    """绘制流程图输入/输出平行四边形。"""
    sk = h * 0.42
    pts = [(cx - w / 2.0 + sk, cy + h / 2.0), (cx + w / 2.0, cy + h / 2.0),
           (cx + w / 2.0 - sk, cy - h / 2.0), (cx - w / 2.0, cy - h / 2.0)]
    ax.add_patch(Polygon(pts, closed=True, fc=fc, ec=ec, lw=1.3, zorder=z))
    if text:
        ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, color="#1F1F1F",
                zorder=z + 1, linespacing=1.4)


def actor(ax, cx, cy, label, sx=0.32, sy=0.55, fs=FS_BODY, color=C_ACTOR):
    """绘制 UML 参与者火柴人；(cx, cy) 为躯干中心。"""
    ax.add_patch(Ellipse((cx, cy + 1.55 * sy), 0.9 * sx, 0.72 * sy, fc="white",
                         ec=color, lw=1.3, zorder=4))
    ax.add_line(Line2D([cx, cx], [cy + 1.19 * sy, cy - 0.12 * sy], color=color, lw=1.3, zorder=4))
    ax.add_line(Line2D([cx - 0.68 * sx, cx + 0.68 * sx], [cy + 0.85 * sy, cy + 0.85 * sy],
                       color=color, lw=1.3, zorder=4))
    ax.add_line(Line2D([cx, cx - 0.58 * sx], [cy - 0.12 * sy, cy - 1.25 * sy],
                       color=color, lw=1.3, zorder=4))
    ax.add_line(Line2D([cx, cx + 0.58 * sx], [cy - 0.12 * sy, cy - 1.25 * sy],
                       color=color, lw=1.3, zorder=4))
    ax.text(cx, cy - 1.85 * sy, label, ha="center", va="top", fontsize=fs, color=color,
            zorder=5, linespacing=1.3)


def poly_arrow(ax, pts, dashed=False, color=C_LINE, lw=1.2, head=12, z=5, back=0.34):
    """绘制折线箭头：前面的线段用 Line2D，最后一段用实心箭头，避免箭头被虚线打断。"""
    pts = [tuple(p) for p in pts]
    p_end, p_prev = pts[-1], pts[-2]
    dx, dy = p_end[0] - p_prev[0], p_end[1] - p_prev[1]
    length = math.hypot(dx, dy) or 1.0
    bx = p_end[0] - dx / length * back
    by = p_end[1] - dy / length * back
    line_pts = pts[:-1] + [(bx, by)]
    ax.add_line(Line2D([p[0] for p in line_pts], [p[1] for p in line_pts], color=color, lw=lw,
                       linestyle=(0, (5, 3)) if dashed else "-", zorder=z, solid_capstyle="butt"))
    ax.add_patch(FancyArrowPatch((bx, by), p_end, arrowstyle="-|>", mutation_scale=head,
                                 lw=lw, color=color, shrinkA=0, shrinkB=0, zorder=z))


def arrow(ax, p1, p2, dashed=False, color=C_LINE, lw=1.2, head=12, rad=0.0, z=5):
    """绘制单段箭头（支持虚线 / 弧线）。"""
    if rad:
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=head, lw=lw,
                                     color=color,
                                     linestyle=(0, (5, 3)) if dashed else "-",
                                     connectionstyle="arc3,rad=%.2f" % rad,
                                     shrinkA=0, shrinkB=0, zorder=z))
        return
    if dashed:
        poly_arrow(ax, [p1, p2], dashed=True, color=color, lw=lw, head=head, z=z)
    else:
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=head, lw=lw,
                                     color=color, shrinkA=0, shrinkB=0, zorder=z))


def text(ax, x, y, s, fs=FS_SMALL, color=C_LINE, ha="center", va="center", bold=False,
         z=8, box_=False):
    """在指定位置写文字。"""
    kw = {}
    if box_:
        kw["bbox"] = dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.92)
    ax.text(x, y, s, fontsize=fs, color=color, ha=ha, va=va, zorder=z,
            fontweight="bold" if bold else "normal", linespacing=1.4, **kw)


# ============================================================================
# 图 1：用例图 —— 公告获取与知识库模块
# ============================================================================
def draw_usecase_announcement():
    """绘制公告获取与知识库模块的 UML 用例图。"""
    fig, ax = fig_ax(11.5, 8.5, (0, 15.2), (0, 12.4),
                     "图 1  CEATS 公告获取与知识库模块 —— 用例图")

    # 系统边界（顶部留出标题带，避免标题压到"解析网页标题"用例）
    ax.add_patch(Rectangle((2.7, 0.5), 8.9, 10.9, fc="#FCFCFC", ec=C_GRAY, lw=1.2,
                           ls=(0, (7, 4)), zorder=1))
    text(ax, 7.15, 11.15, "CEATS 公告获取与知识库模块", fs=11, bold=True, color="#1F3864")

    # 用例：左侧一列为考生主干流程，右上为抓取的内部细节，右下为管理员用例
    ellipse(ax, 5.4, 9.4, 3.3, 1.15, "抓取最新公告")
    ellipse(ax, 5.4, 7.4, 3.3, 1.15, "按关键词检索公告")
    ellipse(ax, 5.4, 5.4, 3.3, 1.15, "一键跳转官网")
    ellipse(ax, 5.4, 3.4, 3.3, 1.25, "查阅逻辑公式/申论模板", fs=9.5)
    ellipse(ax, 9.6, 10.3, 3.3, 1.15, "解析网页标题")
    ellipse(ax, 9.6, 2.0, 3.3, 1.15, "维护监控站点列表")

    # 参与者：招考官方网站与"抓取最新公告"同侧对齐，避免关联线斜穿用例
    actor(ax, 1.2, 6.6, "备考考生", sx=0.34, sy=0.5)
    actor(ax, 1.2, 2.0, "系统管理员", sx=0.34, sy=0.5)
    actor(ax, 14.2, 8.2, "招考官方网站", sx=0.34, sy=0.5)

    # 参与者与用例的关联
    for uy in (9.4, 7.4, 5.4, 3.4):
        ax.add_line(Line2D([1.5, 3.75], [6.6, uy], color=C_LINE, lw=1.0, zorder=2))
    ax.add_line(Line2D([1.5, 7.95], [2.0, 2.0], color=C_LINE, lw=1.0, zorder=2))
    ax.add_line(Line2D([13.85, 7.05], [8.2, 9.4], color=C_LINE, lw=1.0, zorder=2))

    # <<include>>：抓取最新公告 -> 解析网页标题
    arrow(ax, (7.0, 9.78), (8.05, 10.14), dashed=True, color="#1F6F3F")
    text(ax, 7.42, 10.42, "<<include>>", fs=8.5, color="#1F6F3F")

    # <<extend>>：一键跳转官网 -> 按关键词检索公告
    arrow(ax, (5.4, 5.98), (5.4, 6.82), dashed=True, color="#A33E00")
    text(ax, 5.65, 6.4, "<<extend>>", fs=8.5, color="#A33E00", ha="left")

    return save(fig, "usecase_announcement.png")


# ============================================================================
# 图 2：用例图 —— 练题记录与弱项诊断模块
# ============================================================================
def draw_usecase_practice():
    """绘制练题记录与弱项诊断模块的 UML 用例图。"""
    fig, ax = fig_ax(11, 9.4, (0, 15.8), (0, 12.6),
                     "图 2  CEATS 练题记录与弱项诊断模块 —— 用例图")

    # 系统边界
    ax.add_patch(Rectangle((3.0, 0.25), 8.9, 11.4, fc="#FCFCFC", ec=C_GRAY, lw=1.2,
                           ls=(0, (7, 4)), zorder=1))
    text(ax, 7.45, 11.3, "CEATS 练题记录与弱项诊断模块", fs=11, bold=True, color="#1F3864")

    left = [("录入练习表现", 9.9), ("查询历史记录", 8.4), ("修改/删除记录", 6.9),
            ("生成能力雷达图", 5.4), ("查看正确率趋势", 3.9), ("查看效率预警", 2.4),
            ("设置备考目标", 0.9)]
    for name, y in left:
        ellipse(ax, 5.5, y, 3.2, 1.0, name, fs=9.5)

    ellipse(ax, 9.9, 9.9, 3.4, 1.0, "计算正确率与效率", fs=9.5)
    ellipse(ax, 9.9, 5.4, 3.4, 1.0, "读取历史练习数据", fs=9.5)

    # 参与者
    actor(ax, 1.25, 5.4, "备考考生", sx=0.34, sy=0.5)
    actor(ax, 14.5, 5.4, "本地数据库\n(SQLite)", sx=0.34, sy=0.5, fs=9.5)

    # 关联
    for _, y in left:
        ax.add_line(Line2D([1.55, 3.9], [5.4, y], color=C_LINE, lw=1.0, zorder=2))
    ax.add_line(Line2D([14.05, 11.6], [5.4, 5.4], color=C_LINE, lw=1.0, zorder=2))

    # <<include>>
    arrow(ax, (7.1, 9.9), (8.2, 9.9), dashed=True, color="#1F6F3F")
    text(ax, 7.65, 10.12, "<<include>>", fs=8.5, color="#1F6F3F")
    arrow(ax, (7.1, 5.4), (8.2, 5.4), dashed=True, color="#1F6F3F")
    text(ax, 7.65, 5.62, "<<include>>", fs=8.5, color="#1F6F3F")

    # <<extend>>：查看正确率趋势 -> 生成能力雷达图
    arrow(ax, (6.3, 4.42), (6.3, 4.88), dashed=True, color="#A33E00")
    text(ax, 6.55, 4.63, "<<extend>>", fs=8.5, color="#A33E00", ha="left")

    return save(fig, "usecase_practice.png")


# ============================================================================
# 图 3：系统结构图（四层架构）
# ============================================================================
def draw_architecture():
    """绘制 CEATS 的四层系统结构图。"""
    fig, ax = fig_ax(12, 8.2, (0, 16), (0, 13),
                     "图 3  CEATS 系统结构图（四层架构）")

    bands = [
        ("展示层\nPresentation", 10.2, "#DEEBF7", "#2F5597",
         ["main.py\n命令行菜单", "webapp.py\n本地 Web 界面", "visualizer.py\n图表渲染",
          "文本诊断报告"]),
        ("业务层\nLogic", 7.4, "#E2EFDA", "#548235",
         ["recorder.py\n成绩录入与校验", "analyzer.py\n弱项诊断",
          "scraper.py\n公告抓取", "knowledge.py\n知识库检索"]),
        ("数据层\nData", 4.6, "#FFF2CC", "#BF8F00",
         ["database.py\n数据访问对象(DAO)", "SQLite 本地库\nceats.db",
          "config.py\n配置与字典", "models.py\n领域模型"]),
        ("外部依赖\nExternal", 1.8, "#F2F2F2", "#7F7F7F",
         ["招考官网\n(人社局/国家公务员局)", "matplotlib\n绘图库", "requests / bs4\n网络请求与解析"]),
    ]

    band_w = 15.0
    band_x = 0.5
    for label, cy, fc, ec, items in bands:
        box(ax, band_x + band_w / 2.0, cy, band_w, 2.2, "", fc=fc, ec=ec, lw=1.4, z=1, alpha=0.55)
        box(ax, 1.65, cy, 2.3, 1.7, label, fs=10, fc="white", ec=ec, lw=1.3, tc=ec,
            bold=True, z=3)
        n = len(items)
        start, end = 3.15, band_x + band_w - 0.25
        gap = 0.25
        cw = (end - start - gap * (n - 1)) / n
        for i, it in enumerate(items):
            cx = start + cw / 2.0 + i * (cw + gap)
            box(ax, cx, cy, cw, 1.65, it, fs=9.5, fc="white", ec=ec, lw=1.1, z=3)

    # 层间调用方向箭头
    for y_top, y_bot in [(9.1, 8.5), (6.3, 5.7), (3.5, 2.9)]:
        for x in (5.0, 8.0, 11.0):
            arrow(ax, (x, y_top), (x, y_bot), color="#C00000", lw=1.5, head=13, z=4)

    text(ax, 8.0, 12.3, "轻界面、重逻辑、数据驱动", fs=11, color="#C00000", bold=True)
    text(ax, 8.0, 0.3, "红色箭头表示层间调用方向：展示层 → 业务层 → 数据层 → 外部依赖", fs=9.5,
         color=C_GRAY)

    return save(fig, "architecture.png")


# ============================================================================
# 图 4：模块依赖图
# ============================================================================
def draw_module_dependency():
    """绘制 .py 模块之间的 import 依赖有向图（无环）。"""
    fig, ax = fig_ax(13.5, 9.4, (-0.5, 17), (0, 14.4),
                     "图 4  CEATS 模块依赖图（import 依赖，无循环依赖）")

    w, h = 2.4, 1.2
    nodes = {
        "main": (4.6, 11.4, 4.0, 1.3),
        "webapp": (11.2, 11.4, 4.0, 1.3),
        "recorder": (2.0, 8.8, w, h),
        "analyzer": (4.8, 8.8, w, h),
        "scraper": (7.6, 8.8, w, h),
        "visualizer": (10.4, 8.8, w, h),
        "knowledge": (13.2, 8.8, w, h),
        "database": (7.0, 5.8, 3.6, 1.3),
        "models": (5.0, 2.8, 3.0, 1.3),
        "config": (11.4, 2.8, 3.0, 1.3),
    }
    for name, (cx, cy, bw, bh) in nodes.items():
        fc = C_MOD_FILL if name in ("models", "config") else C_FILL
        ec = C_MOD_EDGE if name in ("models", "config") else C_EDGE
        if name in ("main", "webapp"):
            fc, ec = "#FCE4D6", "#C55A11"
        box(ax, cx, cy, bw, bh, "%s.py" % name, fs=10.5, fc=fc, ec=ec, lw=1.4, bold=True, z=4)

    # main / webapp -> 业务层各模块（同为展示层入口，各司其职）
    for x, tx in [(3.6, 2.0), (4.4, 4.8), (5.2, 7.6)]:
        arrow(ax, (x, 10.75), (tx, 9.4), color="#C55A11", lw=1.2)
    for x, tx in [(10.2, 4.8), (11.2, 10.4), (12.2, 13.2)]:
        arrow(ax, (x, 10.75), (tx, 9.4), color="#C55A11", lw=1.2, dashed=True)
    # main / webapp -> 数据层
    poly_arrow(ax, [(3.0, 11.4), (0.3, 11.4), (0.3, 5.8), (5.2, 5.8)], color="#C55A11", lw=1.2)
    poly_arrow(ax, [(12.9, 11.4), (16.6, 11.4), (16.6, 4.9), (8.8, 4.9)], color="#C55A11", lw=1.2)
    # main / webapp -> config
    poly_arrow(ax, [(6.4, 11.4), (15.4, 11.4), (15.4, 2.8), (12.9, 2.8)], color="#C55A11", lw=1.2)

    # 业务层 -> database
    arrow(ax, (2.4, 8.2), (5.6, 6.45), color=C_GRAY, lw=1.1)
    arrow(ax, (4.8, 8.2), (6.2, 6.45), color=C_GRAY, lw=1.1)
    arrow(ax, (7.6, 8.2), (6.9, 6.45), color=C_GRAY, lw=1.1)
    poly_arrow(ax, [(13.2, 8.2), (8.8, 8.2), (8.8, 5.8)], color=C_GRAY, lw=1.1)

    # 业务层 -> models / config
    arrow(ax, (1.4, 8.2), (4.4, 3.45), color=C_GRAY, lw=1.1)
    poly_arrow(ax, [(2.6, 8.2), (2.6, 4.8), (10.2, 4.8), (10.2, 3.45)], color=C_GRAY, lw=1.1)
    arrow(ax, (5.4, 8.2), (5.4, 3.45), color=C_GRAY, lw=1.1)
    poly_arrow(ax, [(7.0, 8.2), (7.0, 7.0), (12.4, 7.0), (12.4, 3.45)], color=C_GRAY, lw=1.1)
    poly_arrow(ax, [(7.6, 8.2), (7.6, 7.2), (5.0, 7.2), (5.1, 3.45)], color=C_GRAY, lw=1.1)
    arrow(ax, (8.3, 8.2), (10.6, 3.45), color=C_GRAY, lw=1.1)
    poly_arrow(ax, [(10.4, 8.2), (10.4, 7.6), (4.0, 7.6), (4.2, 3.45)], color=C_GRAY, lw=1.1)
    arrow(ax, (10.9, 8.2), (12.0, 3.45), color=C_GRAY, lw=1.1)
    poly_arrow(ax, [(13.2, 8.2), (13.2, 7.4), (5.0, 7.4), (5.3, 3.45)], color=C_GRAY, lw=1.1)

    # database -> models / config；models -> config
    arrow(ax, (6.0, 5.15), (5.4, 3.45), color=C_GRAY, lw=1.1)
    poly_arrow(ax, [(8.0, 5.8), (10.6, 5.8), (10.6, 3.45)], color=C_GRAY, lw=1.1)
    arrow(ax, (6.5, 2.8), (9.9, 2.8), color="#548235", lw=1.3)

    # 图例
    box(ax, 8.6, 13.5, 16.6, 1.2,
        "箭头方向：源模块 import 目标模块；分层摆放（main / webapp → 业务 → database → "
        "models/config）保证无环",
        fs=9.5, fc="#FBFBFB", ec="#BFBFBF", lw=0.9, z=3)

    return save(fig, "module_dependency.png")


# ============================================================================
# 图 5：核心类图
# ============================================================================
def uml_class(ax, cx, y_top, w, name, attrs, methods, stereotype=None, fs=8.4,
              fc="#FDF6EC", ec="#B45309", line_h=0.36):
    """绘制 UML 三段式类框，返回 (y_bottom, h)；(cx, y_top) 为顶边中点。"""
    x_left = cx - w / 2.0
    header_h = 0.5 + (0.34 if stereotype else 0.0)
    attr_h = len(attrs) * line_h + 0.16 if attrs else 0.0
    meth_h = len(methods) * line_h + 0.16 if methods else 0.0
    total_h = header_h + attr_h + meth_h
    y_bottom = y_top - total_h

    ax.add_patch(Rectangle((x_left, y_bottom), w, total_h, fc=fc, ec=ec, lw=1.4, zorder=4))
    ax.add_line(Line2D([x_left, x_left + w], [y_top - header_h, y_top - header_h],
                       color=ec, lw=1.1, zorder=5))
    if attrs and methods:
        ax.add_line(Line2D([x_left, x_left + w], [y_bottom + meth_h, y_bottom + meth_h],
                           color=ec, lw=1.1, zorder=5))

    y = y_top - 0.28
    if stereotype:
        ax.text(cx, y, stereotype, ha="center", va="center", fontsize=fs - 0.4, color="#7F7F7F",
                style="italic", zorder=6)
        y -= 0.34
    ax.text(cx, y, name, ha="center", va="center", fontsize=fs + 1.0, fontweight="bold",
            color="#1F3864", zorder=6)

    ty = y_top - header_h - 0.1
    for a in attrs:
        ax.text(x_left + 0.18, ty, a, ha="left", va="top", fontsize=fs, color="#1F1F1F", zorder=6)
        ty -= line_h
    ty = y_top - header_h - attr_h - 0.1
    for m in methods:
        ax.text(x_left + 0.18, ty, m, ha="left", va="top", fontsize=fs, color="#1F1F1F", zorder=6)
        ty -= line_h
    return y_bottom, total_h


def draw_class_diagram():
    """绘制 CEATS 的核心类图（含类、数据模型与关系）。"""
    fig, ax = fig_ax(15.5, 11, (-1.5, 29), (-3.5, 18.5),
                     "图 5  CEATS 核心类图（Class Diagram）")

    # ---- 业务类（第一层）----
    uml_class(ax, 3.4, 17.4, 5.6, "RecordService", ["- db: Database"],
              ["+ submit()", "+ match_module()", "+ match_topic()", "+ recent()", "+ remove()"])
    uml_class(ax, 10.0, 17.4, 6.0, "Analyzer", ["- db: Database"],
              ["+ diagnose_modules()", "+ trend()", "+ slow_modules()", "+ overall()",
               "+ text_report()"])
    uml_class(ax, 16.6, 17.4, 6.2, "AnnouncementScraper",
              ["- timeout: int", "- retries: int", "- session: Session"],
              ["+ fetch()", "+ parse()", "+ scrape_site()", "+ crawl()", "+ fallback_links()"])
    uml_class(ax, 23.2, 17.4, 5.6, "KnowledgeBase", ["- db: Database"],
              ["+ search()", "+ browse()", "+ add()"])

    # ---- 数据访问层（第二层）----
    uml_class(ax, 12.0, 13.6, 6.6, "Database", ["- db_path: str", "- _conn: Connection"],
              ["+ init_schema()", "+ seed()", "+ add_record()", "+ list_records()",
               "+ module_aggregate()", "+ save_announcements()", "+ search_knowledge()"],
              stereotype="<<class>>")
    uml_class(ax, 24.6, 13.6, 7.2, "Visualizer", [],
              ["+ plot_all(diagnoses, series)", "+ plot_radar()", "+ plot_trend()",
               "+ plot_ranking()"], stereotype="<<module>>", fc="#E8F5E9", ec="#2E7D32")

    # ---- 数据模型（第三、四层）----
    uml_class(ax, 2.6, 8.6, 5.2, "Module",
              ["- id: int", "- code: str", "- name: str", "- weight: float"], [],
              stereotype="<<dataclass>>", fc="#EAF1FB", ec="#2F5597")
    uml_class(ax, 8.6, 8.6, 5.2, "Topic",
              ["- id: int", "- module_id: int", "- name: str", "- difficulty: float"], [],
              stereotype="<<dataclass>>", fc="#EAF1FB", ec="#2F5597")
    uml_class(ax, 15.0, 8.6, 6.0, "Announcement",
              ["- id: int", "- source: str", "- title: str", "- url: str",
               "- publish_date: str", "- fetched_at: str"], [],
              stereotype="<<dataclass>>", fc="#EAF1FB", ec="#2F5597")
    uml_class(ax, 22.4, 8.6, 6.0, "KnowledgeItem",
              ["- id: int", "- keyword: str", "- category: str", "- content: str",
               "- example: str"], [],
              stereotype="<<dataclass>>", fc="#EAF1FB", ec="#2F5597")
    uml_class(ax, 4.6, 4.4, 7.0, "PracticeRecord",
              ["- id: int", "- record_date: str", "- total_questions: int",
               "- correct_questions: int", "- duration_seconds: int", "- note: str"],
              ["+ accuracy: float", "+ seconds_per_question: float"],
              stereotype="<<dataclass>>", fc="#EAF1FB", ec="#2F5597")
    uml_class(ax, 16.0, 4.4, 7.0, "ModuleDiagnosis",
              ["- module: str", "- accuracy: float", "- efficiency: float",
               "- stability: float", "- score: float", "- is_weak: bool"], [],
              stereotype="<<dataclass>>", fc="#EAF1FB", ec="#2F5597")

    # ---- 关联关系（1 — 1）----
    ax.add_line(Line2D([2.9, 8.7], [14.46, 12.8], color=C_LINE, lw=1.4, zorder=3))
    text(ax, 3.1, 14.62, "1", fs=9, color=C_LINE)
    text(ax, 8.55, 12.55, "1", fs=9, color=C_LINE)
    text(ax, 5.6, 13.35, "db", fs=8.5, color=C_GRAY)

    arrow(ax, (10.0, 14.46), (10.4, 13.6), color=C_LINE, lw=1.4)
    text(ax, 10.6, 14.1, "1 .. 1  db", fs=9, color=C_LINE, ha="left")

    ax.add_line(Line2D([23.2, 15.3], [14.46, 12.8], color=C_LINE, lw=1.4, zorder=3))
    text(ax, 15.5, 12.55, "1", fs=9, color=C_LINE)
    text(ax, 22.9, 14.62, "1", fs=9, color=C_LINE)
    text(ax, 18.3, 13.05, "db", fs=8.5, color=C_GRAY)

    # ---- 依赖关系（虚线箭头）----
    dep = "#8E44AD"
    arrow(ax, (9.0, 9.94), (2.6, 8.62), dashed=True, color=dep, head=11)
    text(ax, 5.0, 9.45, "<<create>>", fs=8, color=dep)
    arrow(ax, (10.5, 9.94), (8.6, 8.62), dashed=True, color=dep, head=11)
    text(ax, 10.2, 9.3, "<<create>>", fs=8, color=dep)
    arrow(ax, (12.5, 9.94), (15.0, 8.62), dashed=True, color=dep, head=11)
    text(ax, 14.4, 9.4, "<<create>>", fs=8, color=dep)
    arrow(ax, (15.0, 9.94), (22.4, 8.62), dashed=True, color=dep, head=11)
    text(ax, 19.2, 9.45, "<<create>>", fs=8, color=dep)
    poly_arrow(ax, [(11.6, 9.94), (11.6, 5.0), (4.6, 5.0), (4.6, 4.42)], dashed=True, color=dep,
               head=11)
    text(ax, 9.4, 5.25, "<<create>>", fs=8, color=dep)
    arrow(ax, (17.3, 14.46), (17.3, 8.62), dashed=True, color=dep, head=11)
    text(ax, 17.5, 12.4, "<<create>>", fs=8, color=dep, ha="left")
    poly_arrow(ax, [(27.6, 11.54), (28.4, 11.54), (28.4, 3.0), (19.5, 3.0)], dashed=True,
               color="#2E7D32", head=11)
    text(ax, 24.4, 3.3, "<<use>>", fs=8, color="#2E7D32")

    return save(fig, "class_diagram.png")


# ============================================================================
# 图 6：时序图 —— 录入练习表现
# ============================================================================
def lifeline(ax, cx, top_y, bot_y, name, w=3.1, h=0.95, fc="#DEEBF7", ec=C_EDGE):
    """绘制时序图生命线（顶部名称框 + 向下虚线）。"""
    box(ax, cx, top_y - h / 2.0, w, h, name, fs=9.5, fc=fc, ec=ec, lw=1.3, z=4)
    ax.add_line(Line2D([cx, cx], [top_y - h, bot_y], color=C_GRAY, lw=1.0,
                       ls=(0, (6, 4)), zorder=1))


def message(ax, x1, x2, y, label, dashed=False, color=C_LINE, fs=8.8, dx=0.0, ha="center"):
    """绘制一条消息箭头 + 上方文字（文字带白色底衬，避免被生命线干扰）。"""
    arrow(ax, (x1, y), (x2, y), dashed=dashed, color=color, lw=1.1, head=11, z=6)
    ax.text((x1 + x2) / 2.0 + dx, y + 0.18, label, ha=ha, va="bottom", fontsize=fs,
            color=color, zorder=9,
            bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.88))


def activation(ax, cx, y_top, y_bot, w=0.3, fc="#BDD7EE", ec=C_EDGE):
    """绘制时序图激活条。"""
    ax.add_patch(Rectangle((cx - w / 2.0, y_bot), w, y_top - y_bot, fc=fc, ec=ec, lw=1.0,
                           zorder=4))


def self_call(ax, cx, y, label, w=1.15, h=0.6, color=C_LINE, fs=8.6):
    """绘制时序图自调用（环回箭头）。"""
    poly_arrow(ax, [(cx + 0.15, y), (cx + w, y), (cx + w, y - h), (cx + 0.17, y - h)],
               color=color, lw=1.1, head=10)
    ax.text(cx + 0.3, y + 0.1, label, ha="left", va="bottom", fontsize=fs, color=color, zorder=9,
            bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.88))


def draw_sequence_record():
    """绘制"录入练习表现"时序图。"""
    fig, ax = fig_ax(11.5, 10.8, (0, 16.4), (-2.3, 18.4),
                     "图 6  时序图：录入练习表现")

    xs = [1.8, 5.0, 8.2, 11.4, 14.6]
    names = ["备考考生", "main.py\n(CLI)", "RecordService", "Database", "SQLite\n(ceats.db)"]
    top = 17.6
    for cx, nm in zip(xs, names):
        lifeline(ax, cx, top, 0.2, nm)

    x_std, x_main, x_rec, x_db, x_sql = xs
    y = 16.0
    step = 1.35

    message(ax, x_std, x_main, y, "1. 选择「成绩录入」")
    y -= step
    message(ax, x_std, x_main, y, "2. 依次输入 模块 / 考点 / 题数 / 对题数 / 用时")
    y -= step
    message(ax, x_main, x_rec, y, "3. submit(module, topic, total, correct, duration)")
    y -= step
    self_call(ax, x_rec, y, "4. 校验 match_module() / parse_duration()", w=1.3)
    y -= step + 0.3
    message(ax, x_rec, x_main, y, "5. [异常] 抛 RecordError → 提示「输入有误，请重新输入」",
            dashed=True, color=C_RED)
    y -= step + 0.2
    message(ax, x_rec, x_db, y, "6. add_record(...)")
    y -= step
    message(ax, x_db, x_sql, y, "7. INSERT practice_records")
    y -= step
    message(ax, x_sql, x_db, y, "8. 返回 record_id", dashed=True, color="#1F6F3F")
    y -= step
    message(ax, x_db, x_sql, y, "9. 查询回读记录 SELECT ...")
    y -= step
    message(ax, x_sql, x_db, y, "10. 返回 PracticeRecord", dashed=True, color="#1F6F3F")
    y -= step
    message(ax, x_rec, x_main, y, "11. 返回反馈文本「已保存：正确率 45.0%，单题耗时 76.5s」",
            dashed=True, color="#1F6F3F", fs=8.4)
    y -= step
    message(ax, x_main, x_std, y, "12. 命令行显示反馈结果", dashed=True, color="#1F6F3F")

    # 激活条（自首次参与的消息起，到最后一次参与的消息止）
    activation(ax, x_main, 16.35, 0.5)
    activation(ax, x_rec, 13.6, 1.85)
    activation(ax, x_db, 9.05, 3.2)
    activation(ax, x_sql, 7.7, 3.2)
    activation(ax, x_std, 16.3, 0.5, w=0.26, fc="#F8CBAD", ec="#C55A11")

    box(ax, 8.2, -1.1, 15.4, 1.8,
        "异常分支：模块 / 考点不存在、对题数 > 总题数、用时格式非法时，RecordService 抛出 RecordError，\n"
        "CLI 捕获后提示「输入有误，请重新输入」",
        fs=9, fc="#FDECEA", ec=C_RED, lw=1.2, tc="#8B1A1A", z=3)

    return save(fig, "sequence_record.png")


# ============================================================================
# 图 7：时序图 —— 弱项诊断与雷达图生成
# ============================================================================
def draw_sequence_analyze():
    """绘制"弱项诊断与雷达图生成"时序图。"""
    fig, ax = fig_ax(12.5, 10.8, (0, 20.4), (-1.8, 17.6),
                     "图 7  时序图：弱项诊断与雷达图生成")

    xs = [1.8, 5.2, 8.6, 12.0, 15.4, 18.8]
    names = ["备考考生", "main.py\n(CLI)", "Analyzer", "Database", "visualizer",
             "PNG 图表文件"]
    top = 16.9
    for cx, nm in zip(xs, names):
        lifeline(ax, cx, top, 0.6, nm, w=3.2)

    x_std, x_main, x_ana, x_db, x_vis, x_png = xs
    step = 1.35
    y = 15.4

    message(ax, x_std, x_main, y, "1. 选择「弱项诊断报告」")
    y -= step
    message(ax, x_main, x_ana, y, "2. text_report()")
    y -= step
    message(ax, x_ana, x_db, y, "3. module_aggregate() / topic_aggregate()（读 SQLite）")
    y -= step
    message(ax, x_db, x_ana, y, "4. 返回聚合数据", dashed=True, color="#1F6F3F")
    y -= step
    self_call(ax, x_ana, y, "5. 综合得分 = 0.6×正确率 + 0.3×效率 + 0.1×稳定性", w=1.3)
    y -= step + 0.3
    message(ax, x_ana, x_main, y, "6. 返回带弱项标记的 ModuleDiagnosis 列表",
            dashed=True, color="#1F6F3F")
    y -= step + 0.2
    message(ax, x_std, x_main, y, "7. 选择「生成图表」")
    y -= step
    message(ax, x_main, x_vis, y, "8. plot_all(diagnoses, series)")
    y -= step
    self_call(ax, x_vis, y, "9. 生成五角雷达图 / 趋势折线图 / 得分排名图", w=1.3)
    y -= step + 0.3
    message(ax, x_vis, x_png, y, "10. savefig() 写 PNG 文件")
    y -= step
    message(ax, x_vis, x_main, y, "11. 返回图片路径，CLI 打印「图表已生成」",
            dashed=True, color="#1F6F3F")

    activation(ax, x_main, 15.75, 0.95)
    activation(ax, x_ana, 14.35, 8.2)
    activation(ax, x_db, 13.0, 11.2)
    activation(ax, x_vis, 5.75, 0.95)
    activation(ax, x_std, 15.75, 6.65, w=0.26, fc="#F8CBAD", ec="#C55A11")

    box(ax, 7.0, -0.7, 13.6, 1.7,
        "诊断公式：综合得分 = 0.6×正确率 + 0.3×效率 + 0.1×稳定性；\n"
        "弱项判定：得分低于全科均值一定阈值即标记为弱项",
        fs=9, fc="#EAF1FB", ec=C_EDGE, lw=1.2, z=3)

    return save(fig, "sequence_analyze.png")


# ============================================================================
# 图 8：数据库 ER 图
# ============================================================================
def entity_box(ax, cx, y_top, w, title, fields, fc="#EAF1FB", ec=C_EDGE, line_h=0.42,
               fs=9.0):
    """绘制 ER 图实体框（标题栏 + 字段列表），字段格式为 (标记, 名称)。"""
    x_left = cx - w / 2.0
    head_h = 0.6
    h = head_h + len(fields) * line_h + 0.15
    y_bottom = y_top - h
    ax.add_patch(Rectangle((x_left, y_bottom), w, h, fc="white", ec=ec, lw=1.4, zorder=4))
    ax.add_patch(Rectangle((x_left, y_top - head_h), w, head_h, fc=fc, ec=ec, lw=1.4, zorder=5))
    ax.text(cx, y_top - head_h / 2.0, title, ha="center", va="center", fontsize=fs + 1.2,
            fontweight="bold", color="#1F3864", zorder=6)
    ty = y_top - head_h - 0.12
    for tag, fname in fields:
        if tag:
            ax.text(x_left + 0.18, ty - 0.09, tag, ha="left", va="top", fontsize=fs - 1.2,
                    color="#C00000", fontweight="bold", zorder=6)
        ax.text(x_left + 1.0, ty - 0.09, fname, ha="left", va="top", fontsize=fs,
                color="#1F1F1F", zorder=6)
        ty -= line_h
    return y_bottom


def crow_foot(ax, x, y, sign=1, size=0.42, color=C_LINE, lw=1.2):
    """绘制鸦爪（多端）标记，sign=1 表示爪口朝右。"""
    bx = x - sign * size
    for dy in (0.0, size * 0.62, -size * 0.62):
        ax.add_line(Line2D([x, bx], [y, y + dy], color=color, lw=lw, zorder=6))


def draw_er_diagram():
    """绘制数据库 ER 图（6 张表 + 1:N 关系 + 3NF 说明）。"""
    fig, ax = fig_ax(12.5, 9, (-1, 21), (0, 15.6),
                     "图 8  CEATS 数据库 ER 图（SQLite: ceats.db）")

    # 实体
    entity_box(ax, 3.2, 14.2, 5.0, "modules",
               [("PK", "id : INTEGER"), ("UK", "code : TEXT"), ("", "name : TEXT"),
                ("", "weight : REAL")])
    entity_box(ax, 9.2, 14.2, 5.4, "topics",
               [("PK", "id : INTEGER"), ("FK", "module_id : INTEGER"), ("", "name : TEXT"),
                ("", "difficulty : REAL")], fc="#E2EFDA", ec=C_MOD_EDGE)
    entity_box(ax, 17.0, 14.6, 6.4, "practice_records",
               [("PK", "id : INTEGER"), ("", "record_date : TEXT"),
                ("FK", "module_id : INTEGER"), ("FK", "topic_id : INTEGER"),
                ("", "total_questions : INTEGER"), ("", "correct_questions : INTEGER"),
                ("", "duration_seconds : INTEGER"), ("", "note : TEXT"),
                ("", "created_at : TEXT")], fc="#FFF2CC", ec=C_UC_EDGE)
    entity_box(ax, 3.2, 9.4, 5.6, "announcements",
               [("PK", "id : INTEGER"), ("", "source : TEXT"), ("", "title : TEXT"),
                ("UK", "url : TEXT"), ("", "publish_date : TEXT"),
                ("", "matched_keyword : TEXT"), ("", "fetched_at : TEXT")],
               fc="#E2EFDA", ec=C_MOD_EDGE)
    entity_box(ax, 9.9, 9.4, 5.8, "knowledge_items",
               [("PK", "id : INTEGER"), ("UK", "keyword : TEXT"), ("", "category : TEXT"),
                ("", "content : TEXT"), ("", "example : TEXT")])
    entity_box(ax, 16.8, 9.4, 6.0, "exam_plans",
               [("PK", "id : INTEGER"), ("UK", "exam_name : TEXT"), ("", "exam_date : TEXT"),
                ("", "target_score : REAL"), ("", "created_at : TEXT")],
               fc="#FFF2CC", ec=C_UC_EDGE)

    # modules 1 — N topics
    ax.add_line(Line2D([5.7, 6.5], [13.0, 13.0], color=C_LINE, lw=1.4, zorder=3))
    ax.add_line(Line2D([5.9, 5.9], [12.72, 13.28], color=C_LINE, lw=1.4, zorder=3))
    crow_foot(ax, 6.5, 13.0, sign=-1)
    text(ax, 6.0, 13.42, "1", fs=10, color=C_LINE, bold=True)
    text(ax, 6.25, 12.72, "N", fs=10, color=C_LINE, bold=True)

    # modules 1 — N practice_records
    ax.add_line(Line2D([3.2, 13.8], [10.6, 10.6], color=C_LINE, lw=1.4, zorder=3))
    ax.add_line(Line2D([3.2, 3.2], [10.6, 11.77], color=C_LINE, lw=1.4, zorder=3))
    ax.add_line(Line2D([3.0, 3.4], [11.55, 11.55], color=C_LINE, lw=1.4, zorder=3))
    crow_foot(ax, 13.8, 10.6, sign=-1)
    text(ax, 3.75, 11.48, "1", fs=10, color=C_LINE, bold=True, ha="left")
    text(ax, 12.9, 10.85, "N", fs=10, color=C_LINE, bold=True)

    # topics 1 — N practice_records（可空 0..N）
    ax.add_line(Line2D([11.9, 13.8], [12.4, 12.4], color=C_LINE, lw=1.4, zorder=3))
    ax.add_line(Line2D([12.15, 12.15], [12.12, 12.68], color=C_LINE, lw=1.4, zorder=3))
    crow_foot(ax, 13.8, 12.4, sign=-1, size=0.38)
    ax.add_patch(Circle((13.42, 12.4), 0.11, fc="white", ec=C_LINE, lw=1.2, zorder=6))
    text(ax, 12.25, 12.72, "1", fs=10, color=C_LINE, bold=True)
    text(ax, 12.9, 11.95, "0..N", fs=9, color=C_LINE, bold=True)

    text(ax, 10.0, 4.7, "满足第三范式(3NF)：非主属性完全依赖主键，无传递依赖", fs=10.5,
         color="#1F3864", bold=True)
    text(ax, 10.0, 3.9, "practice_records 为事实表（PK id），modules / topics 为维表；"
                        "FK 建立 1→N 关联，支持按模块与时间聚合", fs=9, color=C_GRAY)

    return save(fig, "er_diagram.png")


# ============================================================================
# 图 9：流程图 —— 成绩录入与校验
# ============================================================================
def draw_flowchart_record():
    """绘制成绩录入与校验的流程图。"""
    fig, ax = fig_ax(9, 13.5, (-1.5, 15.5), (-3.8, 26),
                     "图 9  流程图：成绩录入与校验流程")

    cx, ex = 4.2, 11.4

    box(ax, cx, 23.8, 3.4, 1.1, "开始", fs=10, fc="#DEEBF7", ec=C_EDGE, round_=True, z=4)
    box(ax, cx, 21.0, 5.8, 1.3, "选择模块（校验模块是否存在）", fs=9.5, z=4)
    diamond(ax, cx, 17.9, 4.8, 2.0, "模块合法?", fs=9.5)
    para(ax, ex, 17.9, 5.0, 1.5, "输出「未找到模块，\n请重新选择」", fs=9)
    para(ax, cx, 14.8, 5.9, 1.5, "输入 总题数 / 对题数 / 用时", fs=9.5)
    diamond(ax, cx, 11.4, 5.2, 2.4, "对题数 ≤ 总题数\n且均为正整数?", fs=9)
    para(ax, ex, 11.4, 3.6, 1.3, "输出「输入非法」", fs=9)
    box(ax, cx, 8.2, 5.9, 1.3, "解析用时（支持 mm:ss 与纯秒）", fs=9.5, z=4)
    box(ax, cx, 5.8, 5.9, 1.3, "计算正确率与单题平均耗时", fs=9.5, z=4)
    box(ax, cx, 3.4, 5.9, 1.3, "写入 SQLite（practice_records）", fs=9.5, z=4)
    para(ax, cx, 1.0, 5.9, 1.5, "输出「已保存」+ 指标反馈", fs=9.5)
    box(ax, cx, -1.6, 3.4, 1.1, "结束", fs=10, fc="#DEEBF7", ec=C_EDGE, round_=True, z=4)

    # 主干
    arrow(ax, (cx, 23.25), (cx, 21.65))
    arrow(ax, (cx, 20.35), (cx, 18.9))
    arrow(ax, (cx, 16.9), (cx, 15.55))
    text(ax, cx + 0.25, 16.2, "是", fs=9.5, color="#1F6F3F", ha="left", bold=True)
    arrow(ax, (cx, 14.05), (cx, 12.6))
    arrow(ax, (cx, 10.2), (cx, 8.85))
    text(ax, cx + 0.25, 9.5, "是", fs=9.5, color="#1F6F3F", ha="left", bold=True)
    arrow(ax, (cx, 7.55), (cx, 6.45))
    arrow(ax, (cx, 5.15), (cx, 4.05))
    arrow(ax, (cx, 2.75), (cx, 1.75))
    arrow(ax, (cx, 0.25), (cx, -1.05))

    # 否分支 1
    arrow(ax, (cx + 2.4, 17.9), (ex - 2.5, 17.9), color="#C00000")
    text(ax, (cx + 2.4 + ex - 2.5) / 2.0, 18.12, "否", fs=9.5, color="#C00000", bold=True)
    poly_arrow(ax, [(ex, 18.65), (ex, 21.0), (cx + 2.9, 21.0)], color="#C00000")
    text(ax, ex - 0.2, 19.6, "重新选择", fs=8.5, color="#C00000", ha="right")

    # 否分支 2
    arrow(ax, (cx + 2.6, 11.4), (ex - 1.8, 11.4), color="#C00000")
    text(ax, (cx + 2.6 + ex - 1.8) / 2.0, 11.62, "否", fs=9.5, color="#C00000", bold=True)
    poly_arrow(ax, [(ex, 12.05), (ex, 14.8), (cx + 2.95, 14.8)], color="#C00000")
    text(ax, ex - 0.2, 13.1, "重新输入", fs=8.5, color="#C00000", ha="right")

    box(ax, 6.4, -2.7, 14.0, 1.1,
        "校验要点：模块 / 考点必须存在于字典表；题数须为正整数且 对题数 ≤ 总题数；"
        "用时支持 45 / 01:15 两种写法", fs=8.6, fc="#FBFBFB", ec="#BFBFBF", lw=1.0, z=3)

    return save(fig, "flowchart_record.png")


# ============================================================================
# 主流程
# ============================================================================
def main():
    """依次生成 9 张设计图，并打印每个文件的路径与字节数。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    tasks = [
        draw_usecase_announcement,
        draw_usecase_practice,
        draw_architecture,
        draw_module_dependency,
        draw_class_diagram,
        draw_sequence_record,
        draw_sequence_analyze,
        draw_er_diagram,
        draw_flowchart_record,
    ]
    print("输出目录：%s" % OUT_DIR)
    print("-" * 78)
    results = []
    for fn in tasks:
        path = fn()
        size = os.path.getsize(path)
        results.append((path, size))
        flag = "OK " if size > 5000 else "SMALL"
        print("[%s] %s  %d bytes" % (flag, path, size))
    print("-" * 78)
    print("共生成 %d 张图片，全部大于 5000 字节：%s"
          % (len(results), all(s > 5000 for _, s in results)))


if __name__ == "__main__":
    main()
