# -*- coding: utf-8 -*-
"""业务层：专家规则知识库模块。

对应需求 FR-KB-01，把行测公式、解题技巧、申论模板沉淀为可检索条目，
支持按关键词模糊查询与按分类浏览，并在用户新增条目时做去重与校验。
"""

from typing import List, Optional

from .database import Database
from .models import KnowledgeItem


class KnowledgeBaseError(ValueError):
    """知识库操作异常。"""


class KnowledgeBase:
    """知识库服务。"""

    #: 允许的分类，避免分类名称随意扩散
    CATEGORIES = ("公式", "解题技巧", "申论模板")

    def __init__(self, db: Database) -> None:
        self.db = db

    def search(self, keyword: str, limit: int = 20) -> List[KnowledgeItem]:
        """按关键词检索。

        :raises KnowledgeBaseError: 关键词为空。
        """
        text = (keyword or "").strip()
        if not text:
            raise KnowledgeBaseError("查询关键词不能为空")
        return self.db.search_knowledge(text, limit=limit)

    def browse(self, category: Optional[str] = None) -> List[KnowledgeItem]:
        """按分类浏览知识条目。"""
        return self.db.list_knowledge(category)

    def categories(self) -> List[str]:
        """返回已存在的全部分类。"""
        return self.db.list_knowledge_categories()

    def add(
        self, keyword: str, category: str, content: str, example: str = ""
    ) -> int:
        """新增知识条目。

        :raises KnowledgeBaseError: 字段缺失或分类非法。
        """
        keyword = (keyword or "").strip()
        category = (category or "").strip()
        content = (content or "").strip()
        if not keyword or not content:
            raise KnowledgeBaseError("关键词与内容均不能为空")
        if category not in self.CATEGORIES:
            raise KnowledgeBaseError(
                f"分类非法：{category!r}，可选：{'、'.join(self.CATEGORIES)}"
            )
        return self.db.add_knowledge(keyword, category, content, example)

    @staticmethod
    def format_items(items: List[KnowledgeItem]) -> str:
        """把知识条目渲染为命令行可读文本。"""
        if not items:
            return "未找到匹配的知识条目，可尝试更简短的关键词（如「增长率」「申论」）。"
        blocks = []
        for index, item in enumerate(items, start=1):
            block = [f"{index}. 【{item.category}】{item.keyword}", f"   {item.content}"]
            if item.example:
                block.append(f"   示例：{item.example}")
            blocks.append("\n".join(block))
        return "\n".join(blocks)
