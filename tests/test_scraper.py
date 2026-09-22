# -*- coding: utf-8 -*-
"""公告抓取模块单元测试。

重点验证 "鲁棒性"：网络异常、超时重试、页面改版、内容去重等场景下
抓取器都不得抛出异常，而应返回结构化的失败结果并触发降级导航。
"""

import pytest
import requests

from src import config
from src.models import Announcement
from src.scraper import (
    AnnouncementScraper,
    ScrapeError,
    _is_valid_title,
    match_keywords,
    scrape_and_store,
)

#: 模拟页面：包含正常公告、短标题噪声与 javascript 伪链接
SAMPLE_HTML = """
<html><body>
  <div class="nav"><a href="/index.html">首页</a><a href="#">更多</a></div>
  <ul>
    <li><a href="/zwgk/1.html">关于公布2026年度考试录用公务员公告</a></li>
    <li><a href="/zwgk/2.html">2026年省考报名入口及职位表下载</a></li>
    <li><a href="/zwgk/1.html">关于公布2026年度考试录用公务员公告</a></li>
    <li><a href="javascript:void(0)">无效链接测试</a></li>
    <li><a href="https://other.example.com/notice/3.html">外部站点面试安排通知</a></li>
  </ul>
</body></html>
"""


class FakeResponse:
    """模拟 requests.Response。"""

    def __init__(self, text: str, status_code: int = 200, encoding: str = "utf-8") -> None:
        self.text = text
        self.status_code = status_code
        self.encoding = encoding
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """模拟 requests.Session，可配置返回内容或抛出网络异常。"""

    def __init__(self, text: str = SAMPLE_HTML, error: Exception = None) -> None:
        self.text = text
        self.error = error
        self.calls = 0
        self.headers = {}

    def get(self, url, timeout=None):  # noqa: ARG002 - 保持与 requests 一致的签名
        self.calls += 1
        if self.error is not None:
            raise self.error
        return FakeResponse(self.text)


# ------------------------------------------------------------------ 工具函数
def test_is_valid_title_filters_noise():
    assert _is_valid_title("关于公布2026年度考试录用公务员公告") is True
    assert _is_valid_title("首页") is False
    assert _is_valid_title("更多") is False
    assert _is_valid_title("公告") is False  # 长度不足


@pytest.mark.parametrize(
    "title, expected",
    [
        ("2026年省考报名入口及职位表下载", "报名"),
        ("关于公布录用公务员公告", "公告"),
        ("无关标题内容展示", ""),
    ],
)
def test_match_keywords(title, expected):
    assert match_keywords(title, config.DEFAULT_KEYWORDS) == expected


# ------------------------------------------------------------------ 解析层
def test_parse_extracts_and_dedupes():
    scraper = AnnouncementScraper(session=FakeSession())
    items = scraper.parse(SAMPLE_HTML, "https://rsks.gd.gov.cn/", "测试站", config.DEFAULT_KEYWORDS)

    urls = [item.url for item in items]
    assert len(urls) == len(set(urls))  # 去重生效
    assert len(items) == 3
    assert "https://rsks.gd.gov.cn/zwgk/1.html" in urls  # 相对路径已补全
    assert "https://other.example.com/notice/3.html" in urls  # 绝对路径保留
    assert all(item.source == "测试站" for item in items)
    assert all(item.fetched_at for item in items)
    # 命中关键词的条目排在前面
    assert items[0].matched_keyword != ""


def test_parse_handles_renovated_page():
    """页面改版（无有效链接）时返回空列表，而不是抛异常。"""
    scraper = AnnouncementScraper(session=FakeSession())
    assert scraper.parse("<html><body><p>页面维护中</p></body></html>", "http://x.com", "测试站") == []


# ------------------------------------------------------------------ 网络层
def test_fetch_success():
    session = FakeSession()
    assert "公告" in AnnouncementScraper(session=session).fetch("http://x.com")
    assert session.calls == 1


def test_fetch_retries_then_raises():
    """网络异常时按配置重试，重试耗尽后抛出 ScrapeError。"""
    session = FakeSession(error=requests.ConnectionError("断网"))
    scraper = AnnouncementScraper(retries=2, backoff=0, session=session)
    with pytest.raises(ScrapeError, match="网络连接失败"):
        scraper.fetch("http://x.com")
    assert session.calls == 3  # 首次 + 2 次重试


def test_fetch_retries_then_succeeds(monkeypatch):
    """前两次失败、第三次成功，应正常返回内容。"""
    session = FakeSession()

    original_get = session.get
    attempts = {"n": 0}

    def flaky_get(url, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise requests.Timeout("超时")
        return original_get(url, timeout)

    session.get = flaky_get
    scraper = AnnouncementScraper(retries=2, backoff=0, session=session)
    assert "公告" in scraper.fetch("http://x.com")


def test_fetch_fixes_bad_encoding():
    """响应头编码异常（iso-8859-1）时应回退到 apparent_encoding。"""
    session = FakeSession()
    session.get = lambda url, timeout=None: FakeResponse("<html>公告</html>", encoding="iso-8859-1")
    AnnouncementScraper(session=session).fetch("http://x.com")


# ------------------------------------------------------------------ 业务层
def test_scrape_site_never_raises_on_network_error():
    """单站点断网时返回 success=False，不得抛异常。"""
    session = FakeSession(error=requests.ConnectionError("断网"))
    scraper = AnnouncementScraper(retries=0, backoff=0, session=session)
    site_result, items = scraper.scrape_site("测试站", "http://x.com", config.DEFAULT_KEYWORDS)
    assert site_result.success is False
    assert site_result.count == 0
    assert "网络连接失败" in site_result.message
    assert items == []


def test_scrape_site_reports_page_change():
    """页面改版导致解析为空时给出明确提示。"""
    session = FakeSession(text="<html><body>无链接</body></html>")
    scraper = AnnouncementScraper(retries=0, backoff=0, session=session)
    site_result, items = scraper.scrape_site("测试站", "http://x.com")
    assert site_result.success is False
    assert "未解析到有效公告链接" in site_result.message
    assert items == []


def test_scrape_site_success_and_limit():
    session = FakeSession()
    scraper = AnnouncementScraper(retries=0, session=session)
    site_result, items = scraper.scrape_site("测试站", "http://x.com", config.DEFAULT_KEYWORDS, limit=2)
    assert site_result.success is True
    assert site_result.count == 2
    assert len(items) == 2


def test_crawl_isolates_site_failures():
    """多站点抓取：单站失败不影响其他站点（故障隔离）。"""
    session = FakeSession()
    scraper = AnnouncementScraper(retries=0, backoff=0, session=session)
    sites = [("站点A", "http://a.com", "http://a.com"), ("站点B", "http://b.com", "http://b.com")]
    result = scraper.crawl(sites=sites, keywords=config.DEFAULT_KEYWORDS)
    assert len(result.sites) == 2
    assert result.announcements
    assert result.summary()


def test_crawl_all_failed_triggers_fallback():
    """全部站点失败时置位降级标记，由上层切换为链接导航。"""
    session = FakeSession(error=requests.ConnectionError("断网"))
    scraper = AnnouncementScraper(retries=0, backoff=0, session=session)
    result = scraper.crawl(keywords=config.DEFAULT_KEYWORDS)
    assert result.announcements == []
    assert result.used_fallback is True
    assert result.success_count == 0


def test_fallback_links_cover_official_sites():
    links = AnnouncementScraper.fallback_links()
    assert len(links) == len(config.FALLBACK_LINKS)
    assert all(item.url.startswith("http") for item in links)


def test_scrape_and_store_persists_announcements(seeded_db):
    """抓取结果应写入数据库（含去重）。"""
    scraper = AnnouncementScraper(retries=0, session=FakeSession())
    result = scrape_and_store(seeded_db, scraper=scraper)
    assert result.announcements
    unique_urls = {item.url for item in result.announcements}
    assert seeded_db.count_announcements() == len(unique_urls)

    # 第二次抓取全部命中 URL 唯一约束，数量不变
    scrape_and_store(seeded_db, scraper=scraper)
    assert seeded_db.count_announcements() == len(unique_urls)


def test_scrape_and_store_falls_back_to_navigation(seeded_db):
    """断网场景：仍能入库官方入口链接，功能不中断。"""
    scraper = AnnouncementScraper(retries=0, backoff=0, session=FakeSession(error=requests.ConnectionError("断网")))
    result = scrape_and_store(seeded_db, scraper=scraper)
    assert result.used_fallback is True
    stored = seeded_db.list_announcements()
    assert len(stored) == len(config.FALLBACK_LINKS)
    assert all(item.matched_keyword == "导航" for item in stored)


def test_announcement_search_by_keyword(seeded_db):
    seeded_db.save_announcements(
        [
            Announcement(None, "测试站", "2026年省考报名公告", "http://a.com/1", None, "报名", ""),
            Announcement(None, "测试站", "面试资格审查通知", "http://a.com/2", None, "面试", ""),
        ]
    )
    assert len(seeded_db.list_announcements(keyword="报名")) == 1
    assert len(seeded_db.list_announcements()) == 2
