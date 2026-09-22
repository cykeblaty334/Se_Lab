# -*- coding: utf-8 -*-
"""知识库模块单元测试：检索、分类校验与格式化输出。"""

import pytest

from src.knowledge import KnowledgeBase, KnowledgeBaseError


def test_search_by_keyword(seeded_db):
    kb = KnowledgeBase(seeded_db)
    items = kb.search("隔年增长率")
    assert items
    assert items[0].keyword == "隔年增长率"
    assert "r1" in items[0].content


def test_search_partial_keyword(seeded_db):
    """支持模糊匹配（如只输入「增长率」）。"""
    kb = KnowledgeBase(seeded_db)
    keywords = {item.keyword for item in kb.search("增长率")}
    assert {"隔年增长率", "增长率"} <= keywords


def test_search_by_content(seeded_db):
    """关键词未命中时应回退到正文检索。"""
    kb = KnowledgeBase(seeded_db)
    hits = kb.search("最小公倍数")
    assert any(item.keyword == "工程问题" for item in hits)


def test_search_unknown_keyword_returns_empty(seeded_db):
    assert KnowledgeBase(seeded_db).search("量子力学") == []


@pytest.mark.parametrize("raw", ["", "   "])
def test_search_blank_keyword_raises(seeded_db, raw):
    with pytest.raises(KnowledgeBaseError, match="不能为空"):
        KnowledgeBase(seeded_db).search(raw)


def test_browse_by_category(seeded_db):
    kb = KnowledgeBase(seeded_db)
    templates = kb.browse("申论模板")
    assert len(templates) == 3
    assert all(item.category == "申论模板" for item in templates)

    assert len(kb.browse()) == len(seeded_db.list_knowledge())
    assert set(kb.categories()) == {"公式", "解题技巧", "申论模板"}


def test_add_item(seeded_db):
    kb = KnowledgeBase(seeded_db)
    assert kb.add("尾数法", "解题技巧", "只算末位数字快速排除选项", "123×47 取 3×7=21") > 0
    assert kb.search("尾数法")


def test_add_item_validates_input(seeded_db):
    kb = KnowledgeBase(seeded_db)
    with pytest.raises(KnowledgeBaseError, match="不能为空"):
        kb.add("", "公式", "内容")
    with pytest.raises(KnowledgeBaseError, match="不能为空"):
        kb.add("关键词", "公式", "   ")
    with pytest.raises(KnowledgeBaseError, match="分类非法"):
        kb.add("关键词", "随意分类", "内容")


def test_format_items_output(seeded_db):
    kb = KnowledgeBase(seeded_db)
    text = KnowledgeBase.format_items(kb.search("申论大作文"))
    assert "【申论模板】申论大作文" in text
    assert "示例：" in text


def test_format_empty_items_hint(seeded_db):
    text = KnowledgeBase.format_items([])
    assert "未找到匹配的知识条目" in text
