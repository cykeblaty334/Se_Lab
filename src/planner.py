# -*- coding: utf-8 -*-
"""业务层：备考计划模块（考试倒计时 + 上岸目标分拆解）。

对应需求 FR-PLAN-01 / FR-PLAN-02，解决 "不知道还剩多少天、不知道各模块
要考到多少分" 的备考焦虑问题：

1. **倒计时**：保存考试日期后，每次启动系统自动播报剩余天数；
2. **目标分拆解**：输入目标总分（默认 135 分），按公考黄金比例把总分
   折算为五大模块的建议正确率，并与当前实际正确率对比出差额。

拆解算法（可解释、可回溯）::

    建议正确率 = 黄金基准正确率 × 目标总分 / 基准总分
    建议得分   = 模块参考满分 × 建议正确率

其中基准总分 ``BASE_TARGET_TOTAL = 135`` 时结果即黄金比例原值
（言语 75、判断 75、资料 85、数量 60、常识 55），可在 config 中调整。
"""

import re
from datetime import date
from typing import Dict, List, Optional

from . import config
from .database import Database

#: 考试日期写法，如 2027-11-28 / 2027/11/28
_DATE_PATTERN = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")


class PlanError(ValueError):
    """备考计划参数非法时抛出的业务异常。"""


# ------------------------------------------------------------------ 纯函数
def parse_exam_date(raw: str, today: Optional[date] = None) -> str:
    """解析考试日期，返回 ``YYYY-MM-DD`` 字符串。

    :raises PlanError: 格式非法、日期不存在或早于今天。
    """
    text = (raw or "").strip()
    if not text:
        raise PlanError("考试日期不能为空，正确示例 2027-11-28")
    match = _DATE_PATTERN.match(text)
    if not match:
        raise PlanError(f"考试日期格式非法：{raw!r}，正确示例 2027-11-28")
    year, month, day = (int(group) for group in match.groups())
    try:
        parsed = date(year, month, day)
    except ValueError as exc:
        raise PlanError(f"考试日期不存在：{raw!r}（{exc}）") from exc
    base = today or date.today()
    if parsed < base:
        raise PlanError(f"考试日期不能早于今天（{base.isoformat()}）：{parsed.isoformat()}")
    return parsed.isoformat()


def parse_score(raw: str, field_name: str, upper: float = 200.0) -> float:
    """解析分数输入（允许小数）。

    :raises PlanError: 非数字、非正数或超出上限。
    """
    text = str(raw).strip()
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise PlanError(f"{field_name}必须是数字，当前输入：{raw!r}") from exc
    if value <= 0:
        raise PlanError(f"{field_name}必须大于 0，当前输入：{value}")
    if value > upper:
        raise PlanError(f"{field_name}不应超过 {upper:g}，当前输入：{value}")
    return value


def days_remaining(exam_date: str, today: Optional[date] = None) -> int:
    """返回距考试还有的天数；考试当天为 0，已过期为负数。"""
    base = today or date.today()
    try:
        target = date.fromisoformat(exam_date)
    except (TypeError, ValueError) as exc:
        raise PlanError(f"考试日期非法：{exam_date!r}") from exc
    return (target - base).days


def countdown_phrase(days: int) -> str:
    """把剩余天数翻译为口语化描述。"""
    if days > 0:
        return f"还有 {days} 天"
    if days == 0:
        return "就是今天，全力冲刺"
    return f"已过去 {abs(days)} 天"


def target_ratio(module_name: str, target_total: float) -> float:
    """按公考黄金比例把目标总分折算为某模块的建议正确率（%）。

    :return: 0.0 表示该模块未配置黄金比例基准。
    """
    base = config.GOLDEN_RATIO.get(module_name)
    if base is None:
        return 0.0
    scaled = base * target_total / config.BASE_TARGET_TOTAL
    return round(min(config.TARGET_RATIO_MAX, max(config.TARGET_RATIO_MIN, scaled)), 1)


def decompose_target(
    target_total: float, module_names: Optional[List[str]] = None
) -> List[Dict[str, object]]:
    """把目标总分拆解为各模块的建议正确率与建议得分。

    :param target_total: 目标总分（行测 + 申论，200 分制）。
    :param module_names: 参与拆解的模块；默认取黄金比例中配置的五大模块。
    :return: ``[{module_name, short, golden, ratio, full_score, target_score}, ...]``
    """
    names = module_names or list(config.GOLDEN_RATIO)
    rows: List[Dict[str, object]] = []
    for name in names:
        ratio = target_ratio(name, target_total)
        full_score = float(config.MODULE_FULL_SCORE.get(name, 0.0))
        rows.append(
            {
                "module_name": name,
                "short": config.MODULE_SHORT.get(name, name),
                "golden": float(config.GOLDEN_RATIO.get(name, 0.0)),
                "ratio": ratio,
                "full_score": full_score,
                "target_score": round(full_score * ratio / 100, 1),
            }
        )
    return rows


def judge_gap(current: Optional[float], target: float) -> str:
    """比较当前正确率与建议目标正确率，返回中文结论。"""
    if current is None:
        return "暂无数据"
    # 统一转 float：避免整数入参导致 "差 5 个百分点" 与 "差 5.0 个百分点" 两种写法
    diff = round(float(current) - float(target), 1)
    if diff >= 0:
        return f"已达标（+{diff}%）"
    return f"差 {abs(diff)} 个百分点"


# ------------------------------------------------------------------ 服务类
class PlanService:
    """备考计划服务：保存考试信息、播报倒计时、拆解目标分。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------- 计划读写
    def set_plan(
        self,
        exam_name: str,
        exam_date_raw: str,
        target_raw: str,
        essay_raw: str = "",
    ) -> Dict[str, object]:
        """校验并保存备考计划。

        :raises PlanError: 考试名称、日期或分数非法。
        """
        name = (exam_name or "").strip() or config.DEFAULT_EXAM_NAME
        exam_date = parse_exam_date(exam_date_raw)
        target = parse_score(target_raw, "目标总分")
        essay = (
            parse_score(essay_raw, "申论预期分", upper=100.0)
            if str(essay_raw).strip()
            else config.DEFAULT_ESSAY_SCORE
        )
        if essay >= target:
            raise PlanError(
                f"申论预期分（{essay:g}）应小于目标总分（{target:g}），请检查输入"
            )
        self.db.set_exam_plan(name, exam_date, target, essay)
        return self.current() or {}

    def current(self, today: Optional[date] = None) -> Optional[Dict[str, object]]:
        """返回当前备考计划，并附加剩余天数与行测目标分。"""
        plan = self.db.get_exam_plan()
        if not plan:
            return None
        exam_date = str(plan["exam_date"])
        target = float(plan["target_score"])
        essay = float(plan.get("essay_score") or config.DEFAULT_ESSAY_SCORE)
        plan["days_remaining"] = days_remaining(exam_date, today)
        plan["essay_score"] = essay
        plan["target_score"] = target
        # 行测需拿到的分数 = 目标总分 - 申论预期分
        plan["xingce_target"] = round(max(0.0, target - essay), 1)
        return plan

    # ---------------------------------------------------------- 目标拆解
    def target_table(
        self, target_total: Optional[float] = None
    ) -> List[Dict[str, object]]:
        """返回模块级目标拆解表，并附带当前实际正确率与差距。"""
        plan = self.current()
        total = float(target_total) if target_total else float(
            (plan or {}).get("target_score") or config.DEFAULT_TARGET_TOTAL
        )
        modules = self.db.list_modules()
        names = [module.name for module in modules] or list(config.GOLDEN_RATIO)
        rows = decompose_target(total, names)

        current_map = {
            str(row["module_name"]): (
                round(int(row["correct_questions"]) / int(row["total_questions"]) * 100, 1)
                if int(row["total_questions"])
                else None
            )
            for row in self.db.module_aggregate()
        }
        for row in rows:
            current = current_map.get(str(row["module_name"]))
            row["current"] = current
            row["gap"] = judge_gap(current, float(row["ratio"]))
        return rows

    def estimated_xingce_score(self, target_total: Optional[float] = None) -> float:
        """按建议正确率估算行测可得分数（满分 100）。"""
        rows = self.target_table(target_total)
        return round(sum(float(row["target_score"]) for row in rows), 1)

    # ---------------------------------------------------------- 文本渲染
    def banner(self, today: Optional[date] = None) -> str:
        """生成一行启动提醒文本；未设置计划时返回空串。"""
        plan = self.current(today)
        if not plan:
            return ""
        days = int(plan["days_remaining"])
        return (
            f"[倒计时] 距离 {plan['exam_name']} {countdown_phrase(days)}"
            f" | 目标 {plan['target_score']:g} 分"
            f"（行测需 {plan['xingce_target']:g} 分）"
        )

    def summary_lines(
        self, today: Optional[date] = None, with_table: bool = True
    ) -> List[str]:
        """生成备考计划文本（倒计时 + 目标拆解表）。"""
        plan = self.current(today)
        if not plan:
            return [
                "尚未设置备考计划。",
                "请执行：python -m src.main plan set --date 2027-11-28 --target 135",
            ]

        days = int(plan["days_remaining"])
        lines = [
            "=" * 60,
            "CEATS 备考计划 · 倒计时与目标分拆解",
            "-" * 60,
            f"考试名称 : {plan['exam_name']}",
            f"考试日期 : {plan['exam_date']}",
            f"剩余时间 : {countdown_phrase(days)}",
            f"目标总分 : {plan['target_score']:g} 分"
            f"（行测目标 {plan['xingce_target']:g} 分 + 申论预期 {plan['essay_score']:g} 分）",
        ]
        if days >= 0 and days <= 30:
            lines.append("提醒     : 已进入冲刺期，建议以真题套卷与错题复盘为主。")
        elif days > 30:
            lines.append(f"提醒     : 平均每天推进约 {max(1, days // 30)} 天的复习量，注意按期复盘。")

        if not with_table:
            lines.append("=" * 60)
            return lines

        lines += [
            "-" * 60,
            f"{'模块':<6}{'黄金比例':>9}{'建议正确率':>11}{'建议得分':>9}"
            f"{'当前正确率':>11}{'差距':>16}",
        ]
        for row in self.target_table(float(plan["target_score"])):
            current = row["current"]
            current_text = f"{current}%" if current is not None else "—"
            lines.append(
                f"{row['short']:<6}{row['golden']:>8.0f}%{row['ratio']:>10.1f}%"
                f"{row['target_score']:>9.1f}{current_text:>11}{row['gap']:>16}"
            )
        lines.append("-" * 60)
        lines.append(
            f"按上述目标正确率估算，行测可得约 "
            f"{self.estimated_xingce_score(float(plan['target_score'])):g} / 100 分"
        )
        lines.append(
            "说明：建议正确率 = 黄金比例基准 × 目标总分 / 135，"
            "黄金基准可在 src/config.py 的 GOLDEN_RATIO 中调整。"
        )
        lines.append("=" * 60)
        return lines
