# -*- coding: utf-8 -*-
"""业务层：招考公告抓取模块。

对应需求 FR-INF-01 / NFR-STAB-01。本模块的工程重点不是 "抓到数据"，
而是 "抓不到数据时也不能崩"：

1. 统一超时 + 有限重试 + 退避等待，避免网络抖动导致失败；
2. 逐站点隔离异常，单站失败不影响其他站点；
3. 页面改版（找不到目标节点）时自动降级为 "链接导航" 模式；
4. 所有对外函数只返回结构化结果，不向上抛出网络异常。

因此上层 CLI 只需展示 ``ScrapeResult``，无需关心网络细节。
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import config
from .database import Database, now_str
from .models import Announcement


class ScrapeError(Exception):
    """抓取过程中的可预期异常（网络、超时、解析失败）。"""


@dataclass
class SiteResult:
    """单个站点的抓取结果。"""

    source: str
    url: str
    success: bool
    count: int = 0
    message: str = ""
    elapsed: float = 0.0


@dataclass
class ScrapeResult:
    """一次批量抓取的汇总结果。"""

    sites: List[SiteResult] = field(default_factory=list)
    announcements: List[Announcement] = field(default_factory=list)
    used_fallback: bool = False

    @property
    def success_count(self) -> int:
        """抓取成功的站点数量。"""
        return sum(1 for site in self.sites if site.success)

    def summary(self) -> str:
        """生成面向用户的文字摘要。"""
        lines = [
            f"抓取完成：成功 {self.success_count}/{len(self.sites)} 个站点，"
            f"共获得 {len(self.announcements)} 条公告",
        ]
        for site in self.sites:
            flag = "成功" if site.success else "失败"
            lines.append(
                f"  [{flag}] {site.source}  {site.count} 条  "
                f"{site.elapsed:.1f}s  {site.message}"
            )
        if self.used_fallback:
            lines.append("提示：部分站点访问失败，已切换为「链接导航」模式，请手动访问官网确认。")
        return "\n".join(lines)


def _is_valid_title(text: str, min_length: int = 8) -> bool:
    """过滤导航栏等噪声：标题需具备一定长度且不含明显无意义字符。"""
    stripped = " ".join(text.split())
    if len(stripped) < min_length:
        return False
    noisy = {"more", "更多", "首页", "下一页", "返回", "登录", "注册"}
    return stripped not in noisy


def match_keywords(title: str, keywords: Sequence[str]) -> str:
    """返回标题命中的第一个关键词，未命中返回空串。"""
    for keyword in keywords:
        if keyword in title:
            return keyword
    return ""


class AnnouncementScraper:
    """公告抓取器（含重试与降级策略）。"""

    def __init__(
        self,
        timeout: int = config.REQUEST_TIMEOUT,
        retries: int = config.REQUEST_RETRIES,
        backoff: float = config.RETRY_BACKOFF,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    # ------------------------------------------------------------ 网络层
    def fetch(self, url: str) -> str:
        """下载页面 HTML，失败自动重试。

        :raises ScrapeError: 超过重试次数仍失败。
        """
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                # 政府网站编码标注常不规范，交给 requests 猜测后再兜底
                if not response.encoding or response.encoding.lower() == "iso-8859-1":
                    response.encoding = response.apparent_encoding or "utf-8"
                return response.text
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
        raise ScrapeError(f"网络连接失败（已重试 {self.retries} 次）：{last_error}")

    # ------------------------------------------------------------ 解析层
    def parse(
        self,
        html: str,
        base_url: str,
        source: str,
        keywords: Sequence[str] = (),
    ) -> List[Announcement]:
        """从 HTML 中抽取公告条目。

        以 ``<a>`` 标签为最小抽取单位，按标题长度过滤导航噪声，
        并按 url 去重；页面改版导致抽取为空时返回空列表（由上层降级）。
        """
        soup = BeautifulSoup(html, "lxml")
        seen: Dict[str, Announcement] = {}
        fetched_at = now_str()

        for anchor in soup.find_all("a"):
            title = anchor.get_text(strip=True)
            href = anchor.get("href")
            if not href or not _is_valid_title(title):
                continue
            if href.startswith(("javascript:", "#", "mailto:")):
                continue
            url = urljoin(base_url, href)
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            if url in seen:
                continue
            seen[url] = Announcement(
                id=None,
                source=source,
                title=title[:120],
                url=url,
                publish_date=None,
                matched_keyword=match_keywords(title, keywords),
                fetched_at=fetched_at,
            )
        # 命中关键词的公告优先展示，其次按原页面顺序
        return sorted(seen.values(), key=lambda item: item.matched_keyword == "", reverse=False)

    # ------------------------------------------------------------ 业务层
    def scrape_site(
        self,
        source: str,
        url: str,
        keywords: Sequence[str] = (),
        limit: int = 30,
    ) -> tuple:
        """抓取单个站点，返回 ``(SiteResult, [Announcement, ...])``。

        本方法**不抛出异常**，任何失败都转换为 ``SiteResult.success=False``。
        """
        start = time.time()
        try:
            html = self.fetch(url)
        except ScrapeError as exc:
            return (
                SiteResult(
                    source=source,
                    url=url,
                    success=False,
                    message=str(exc),
                    elapsed=time.time() - start,
                ),
                [],
            )

        try:
            items = self.parse(html, url, source, keywords)[:limit]
        except Exception as exc:  # noqa: BLE001 - 解析异常统一降级，保证流程不中断
            return (
                SiteResult(
                    source=source,
                    url=url,
                    success=False,
                    message=f"页面解析失败（可能已改版）：{exc}",
                    elapsed=time.time() - start,
                ),
                [],
            )

        if not items:
            return (
                SiteResult(
                    source=source,
                    url=url,
                    success=False,
                    message="未解析到有效公告链接（页面结构可能已调整）",
                    elapsed=time.time() - start,
                ),
                [],
            )
        return (
            SiteResult(
                source=source,
                url=url,
                success=True,
                count=len(items),
                message="OK",
                elapsed=time.time() - start,
            ),
            items,
        )

    def crawl(
        self,
        sites: Optional[Iterable[tuple]] = None,
        keywords: Sequence[str] = (),
        limit_per_site: int = 30,
    ) -> ScrapeResult:
        """批量抓取所有监控站点，失败自动进入降级导航模式。"""
        result = ScrapeResult()
        targets = list(sites or config.MONITOR_SITES)
        for source, _home, list_url in targets:
            site_result, items = self.scrape_site(
                source, list_url, keywords, limit=limit_per_site
            )
            result.sites.append(site_result)
            result.announcements.extend(items)

        if not result.announcements:
            result.used_fallback = True
        return result

    @staticmethod
    def fallback_links() -> List[Announcement]:
        """断网或改版时返回官方入口链接，保证功能可用。"""
        fetched_at = now_str()
        return [
            Announcement(
                id=None,
                source=name,
                title=f"{name}（官方入口）",
                url=url,
                matched_keyword="导航",
                fetched_at=fetched_at,
            )
            for name, url in config.FALLBACK_LINKS
        ]


def scrape_and_store(
    db: Database,
    keywords: Optional[Sequence[str]] = None,
    scraper: Optional[AnnouncementScraper] = None,
) -> ScrapeResult:
    """抓取公告并写入数据库，返回本次抓取结果。

    :param db: 数据库对象。
    :param keywords: 关注关键词，默认使用配置中的列表。
    :param scraper: 可注入的抓取器（便于测试时替换为桩对象）。
    """
    worker = scraper or AnnouncementScraper()
    result = worker.crawl(keywords=keywords or config.DEFAULT_KEYWORDS)
    if not result.announcements:
        # 全部站点失败：降级为官方入口导航，保证功能可用
        result.announcements = worker.fallback_links()
        result.used_fallback = True
    db.save_announcements(result.announcements)
    return result
