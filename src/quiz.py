# -*- coding: utf-8 -*-
"""业务层：弱项考点 "极速抽测闪卡" 模块。

对应需求 FR-QUIZ-01 / FR-QUIZ-02，把知识库中的公式、解题技巧、申论模板
变成可作答的闪卡，在不连接任何大模型的前提下实现 "互动刷题"：

1. 从知识库随机抽题（同一次抽测不重复）；
2. 用户在终端输入答案，系统按 "关键字片段覆盖率" 自动判分；
3. 作答结果写入 ``quiz_log``，可统计平均分与通过率。

判分算法（可解释、可离线、无外部依赖）::

    1. 归一化：全角转半角、统一 ×/÷ 等符号、忽略空白与标点、忽略大小写；
    2. 若答案完整包含标准答案（或反之）-> 100 分，判为 "完全正确"；
    3. 否则按片段覆盖率打分：
       覆盖率 = 命中片段权重之和 / 全部片段权重之和
       其中字母数字片段（公式变量、数字）权重 2，中文片段权重 1。

这样 "只写出公式骨架、漏掉变量含义" 的答案能拿到部分分，并通过
"遗漏要点" 提示用户补齐，符合错题复盘的教学目的。
"""

import random
import re
from typing import Callable, Dict, List, Optional

from . import config
from .database import Database
from .models import KnowledgeItem, QuizQuestion, QuizResult

#: 片段切分：以 "非中文且非字母数字" 作为分隔符
_FRAGMENT_SPLIT = re.compile(r"[^\u4e00-\u9fffa-z0-9]+")
#: 全角字符转换为半角的偏移量
_FULLWIDTH_OFFSET = 0xFEE0
#: 数学符号统一映射（左为多种写法，右为标准写法）
_SYMBOL_MAP = {
    "×": "*",
    "✕": "*",
    "✖": "*",
    "x": "*",
    "＊": "*",
    "÷": "/",
    "／": "/",
    "－": "-",
    "−": "-",
    "＝": "=",
}
#: 各分类对应的提问方式
_QUESTION_TEMPLATE = {
    "公式": "「{keyword}」的计算公式是什么？请写出公式与关键变量含义",
    "解题技巧": "「{keyword}」的解题思路/步骤是什么？",
    "申论模板": "「{keyword}」的作答结构是什么？",
}
_DEFAULT_QUESTION = "请写出「{keyword}」的核心要点。"


def loosen(text: str) -> str:
    """仅做全角转半角、符号统一与转小写，保留空白与标点作为分隔符。

    先完成全角转半角再转小写，最后映射数学符号，
    这样全角 ``Ｘ``、半角 ``x`` 与 ``×`` 都能统一为 ``*``。
    """
    chars = []
    for char in str(text or ""):
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:  # 全角 ASCII
            char = chr(code - _FULLWIDTH_OFFSET)
        elif code == 0x3000:  # 全角空格
            char = " "
        chars.append(char)
    return "".join(_SYMBOL_MAP.get(char, char) for char in "".join(chars).lower())


def normalize(text: str) -> str:
    """归一化文本：在半角化基础上压缩掉全部空白，用于 "包含关系" 判定。"""
    return re.sub(r"\s+", "", loosen(text))


def compact(text: str) -> str:
    """仅保留中文与字母数字，用于 "包含关系" 判定。"""
    return re.sub(r"[^\u4e00-\u9fffa-z0-9]", "", normalize(text))


def extract_fragments(text: str) -> List[str]:
    """从标准答案中切分出关键片段（去重且保持原顺序）。

    切分基于保留空白的 ``loosen`` 结果，因此 ``"隔年增长率 R = r1 + r2"``
    会被切成 ``["隔年增长率", "r", "r1", "r2"]`` 四个独立片段，
    不会因为去空格而粘连成 ``"隔年增长率r"``。
    中文片段要求长度 >= 2，字母数字片段长度 >= 1。
    """
    pieces: List[str] = []
    for raw in _FRAGMENT_SPLIT.split(loosen(text)):
        if not raw:
            continue
        if raw.isascii():
            pieces.append(raw)
        elif len(raw) >= 2:
            pieces.append(raw)
    seen = set()
    unique = []
    for piece in pieces:
        if piece not in seen:
            seen.add(piece)
            unique.append(piece)
    return unique


def fragment_weight(fragment: str) -> float:
    """片段权重：字母数字（公式变量/数字）权重更高。"""
    return config.QUIZ_WEIGHT_ALNUM if fragment.isascii() else config.QUIZ_WEIGHT_CJK


def grade_answer(
    user_answer: str, expected: str, pass_score: float = config.QUIZ_PASS_SCORE
) -> Dict[str, object]:
    """对用户答案自动判分。

    :return: ``{score, passed, level, hit, missed}``（score 为 0~100）。
    """
    answer = compact(user_answer)
    target = compact(expected)
    fragments = extract_fragments(expected)

    if not answer:
        return {
            "score": 0.0,
            "passed": False,
            "level": "未作答",
            "hit": [],
            "missed": fragments,
        }

    hit = [frag for frag in fragments if compact(frag) in answer]
    missed = [frag for frag in fragments if frag not in hit]

    if target and target in answer:
        return {
            "score": 100.0,
            "passed": True,
            "level": "完全正确",
            "hit": fragments,
            "missed": [],
        }

    total_weight = sum(fragment_weight(frag) for frag in fragments) or 1.0
    hit_weight = sum(fragment_weight(frag) for frag in hit)
    score = round(hit_weight / total_weight * 100, 1)

    if score >= 85:
        level = "完全正确"
    elif score >= pass_score:
        level = "基本正确"
    elif score >= 30:
        level = "部分正确"
    else:
        level = "需加强"
    return {
        "score": score,
        "passed": score >= pass_score,
        "level": level,
        "hit": hit,
        "missed": missed,
    }


def build_question(item: KnowledgeItem) -> QuizQuestion:
    """把一条知识库条目转换为闪卡题目。"""
    template = _QUESTION_TEMPLATE.get(item.category, _DEFAULT_QUESTION)
    return QuizQuestion(
        item_id=item.id,
        keyword=item.keyword,
        category=item.category,
        question=template.format(keyword=item.keyword),
        expected=item.content,
        example=item.example,
    )


def format_result(result: QuizResult, show_expected: bool = True) -> str:
    """把一次作答渲染为可读文本。"""
    lines = [
        f"[{result.level}] 得分 {result.score:g} / 100"
        f"（{'通过' if result.passed else '未通过'}）",
    ]
    if show_expected:
        lines.append(f"标准答案：{result.question.expected}")
    if result.missed_fragments:
        lines.append("遗漏要点：" + "、".join(result.missed_fragments[:6]))
    if result.question.example:
        lines.append(f"示例：{result.question.example}")
    return "\n".join(lines)


class QuizService:
    """闪卡抽测服务：抽题 -> 判分 -> 记账。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------- 抽题
    def pool(self, category: Optional[str] = None) -> List[KnowledgeItem]:
        """返回可抽题的知识库条目。"""
        items = self.db.list_knowledge(category)
        return [item for item in items if item.content]

    def draw(
        self,
        count: int = config.QUIZ_DEFAULT_COUNT,
        category: Optional[str] = None,
        rng: Optional[random.Random] = None,
    ) -> List[QuizQuestion]:
        """随机抽取 ``count`` 道题目（不重复）。

        :raises ValueError: 知识库为空。
        """
        items = self.pool(category)
        if not items:
            raise ValueError(
                "知识库为空，无法抽题；可先执行 python -m src.main init 载入字典数据"
            )
        rng = rng or random.Random()
        size = max(1, min(int(count), len(items)))
        picked = rng.sample(items, size)
        return [build_question(item) for item in picked]

    # ---------------------------------------------------------- 判分记账
    def submit(
        self, question: QuizQuestion, answer: str, elapsed_seconds: float = 0.0
    ) -> QuizResult:
        """判分并写入抽测日志。"""
        graded = grade_answer(answer, question.expected)
        result = QuizResult(
            question=question,
            answer=answer,
            score=float(graded["score"]),
            passed=bool(graded["passed"]),
            level=str(graded["level"]),
            hit_fragments=list(graded["hit"]),
            missed_fragments=list(graded["missed"]),
        )
        self.db.add_quiz_log(
            keyword=question.keyword,
            category=question.category,
            user_answer=answer,
            score=result.score,
            passed=result.passed,
            elapsed_seconds=elapsed_seconds,
        )
        return result

    def run_session(
        self,
        count: int = config.QUIZ_DEFAULT_COUNT,
        category: Optional[str] = None,
        input_func: Optional[Callable[[str], str]] = None,
        output_func: Optional[Callable[[str], None]] = None,
        rng: Optional[random.Random] = None,
    ) -> List[QuizResult]:
        """在终端中完成一次抽测（输入 q 可提前结束）。

        ``input_func`` / ``output_func`` 默认为内置 ``input`` / ``print``，
        并在调用时解析，便于测试替换与界面层注入。
        """
        ask = input_func or input
        show = output_func or print
        questions = self.draw(count=count, category=category, rng=rng)
        results: List[QuizResult] = []
        total = len(questions)
        for index, question in enumerate(questions, start=1):
            show("")
            show(f"--- 第 {index}/{total} 题 · {question.category} ---")
            show(question.question)
            try:
                answer = ask("你的答案（输入 q 结束抽测）: ")
            except (EOFError, KeyboardInterrupt):
                show("\n检测到中断，本次抽测提前结束。")
                break
            if str(answer).strip().lower() in {"q", "quit", "exit"}:
                show("已结束本次抽测。")
                break
            result = self.submit(question, str(answer))
            show(format_result(result))
            results.append(result)
        if results:
            show("")
            show(self.summary_text(results))
        return results

    # ---------------------------------------------------------- 统计与渲染
    def stats(self, days: Optional[int] = None) -> Dict[str, object]:
        """返回闪卡作答统计。"""
        return self.db.quiz_stats(days)

    @staticmethod
    def summary_text(results: List[QuizResult]) -> str:
        """汇总一次抽测的成绩。"""
        if not results:
            return "本次抽测没有有效作答记录。"
        scores = [item.score for item in results]
        passed = sum(1 for item in results if item.passed)
        lines = [
            "=" * 50,
            "本次抽测结果",
            "-" * 50,
            f"作答题数：{len(results)}    通过：{passed}    未通过：{len(results) - passed}",
            f"平均得分：{round(sum(scores) / len(scores), 1)}    最高：{max(scores):g}",
        ]
        weak = [item for item in results if not item.passed]
        if weak:
            lines.append("需要巩固：" + "、".join(item.question.keyword for item in weak))
        else:
            lines.append("全部通过，知识库掌握良好。")
        lines.append("=" * 50)
        return "\n".join(lines)

    def stats_text(self, days: Optional[int] = None) -> str:
        """渲染历史抽测统计文本。"""
        stats = self.stats(days)
        if not stats["attempts"]:
            return "暂无闪卡抽测记录，可执行 python -m src.main quiz 开始刷题。"
        scope = f"最近 {days} 天" if days else "累计"
        lines = [
            f"{scope}闪卡作答：{stats['attempts']} 次，"
            f"通过率 {stats['pass_rate']}%，平均得分 {stats['avg_score']}",
        ]
        weak = self.db.quiz_weak_keywords(limit=3)
        if weak:
            lines.append(
                "掌握最弱的知识点："
                + "、".join(
                    f"{row['keyword']}（{round(float(row['avg_score']), 1)} 分）" for row in weak
                )
            )
        return "\n".join(lines)
