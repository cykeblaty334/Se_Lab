# -*- coding: utf-8 -*-
"""数据访问层模块。

封装 SQLite 的连接管理、表结构定义与全部 CRUD 操作，向上层提供
"以对象为单位" 的读写接口，业务层无需关心 SQL 细节。

表结构遵循第三范式：
    modules         模块字典表（主键 id）
    topics          考点字典表（外键 module_id -> modules.id）
    practice_records 练习记录表（外键 module_id / topic_id）
    announcements   招考公告表（url 唯一约束，天然去重）
    knowledge_items 知识库表（keyword 唯一约束）
    exam_plans      备考目标表（含申论预期分 essay_score）
    quiz_log        闪卡抽测记录表
"""

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import config
from .models import (
    Announcement,
    KnowledgeItem,
    Module,
    PracticeRecord,
    Topic,
)

#: 建表语句集合（顺序即依赖顺序）
SCHEMA_STATEMENTS: Sequence[str] = (
    """
    CREATE TABLE IF NOT EXISTS modules (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        code    TEXT    NOT NULL UNIQUE,
        name    TEXT    NOT NULL UNIQUE,
        weight  REAL    NOT NULL DEFAULT 0 CHECK (weight >= 0 AND weight <= 1)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS topics (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id  INTEGER NOT NULL,
        name       TEXT    NOT NULL,
        difficulty REAL    NOT NULL DEFAULT 0.5,
        FOREIGN KEY (module_id) REFERENCES modules (id) ON DELETE CASCADE,
        UNIQUE (module_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS practice_records (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        record_date       TEXT    NOT NULL,
        module_id         INTEGER NOT NULL,
        topic_id          INTEGER,
        total_questions   INTEGER NOT NULL CHECK (total_questions > 0),
        correct_questions INTEGER NOT NULL CHECK (correct_questions >= 0),
        duration_seconds  INTEGER NOT NULL CHECK (duration_seconds > 0),
        note              TEXT    DEFAULT '',
        is_wrong          INTEGER NOT NULL DEFAULT 0 CHECK (is_wrong IN (0, 1)),
        created_at        TEXT    NOT NULL,
        FOREIGN KEY (module_id) REFERENCES modules (id),
        FOREIGN KEY (topic_id) REFERENCES topics (id),
        CHECK (correct_questions <= total_questions)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS announcements (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        source          TEXT NOT NULL,
        title           TEXT NOT NULL,
        url             TEXT NOT NULL UNIQUE,
        publish_date    TEXT,
        matched_keyword TEXT DEFAULT '',
        fetched_at      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_items (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword  TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL,
        content  TEXT NOT NULL,
        example  TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exam_plans (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_name    TEXT NOT NULL,
        exam_date    TEXT NOT NULL,
        target_score REAL NOT NULL,
        essay_score  REAL NOT NULL DEFAULT 65,
        created_at   TEXT NOT NULL,
        UNIQUE (exam_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quiz_log (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_date        TEXT    NOT NULL,
        keyword          TEXT    NOT NULL,
        category         TEXT    DEFAULT '',
        user_answer      TEXT    DEFAULT '',
        score            REAL    NOT NULL DEFAULT 0,
        passed           INTEGER NOT NULL DEFAULT 0 CHECK (passed IN (0, 1)),
        elapsed_seconds  REAL    NOT NULL DEFAULT 0,
        created_at       TEXT    NOT NULL
    )
    """,
    # 索引：按时间 / 模块检索练习记录，保证 NFR-PERF-01（查询 < 0.5s）
    "CREATE INDEX IF NOT EXISTS idx_record_date ON practice_records (record_date)",
    "CREATE INDEX IF NOT EXISTS idx_record_module ON practice_records (module_id, record_date)",
    "CREATE INDEX IF NOT EXISTS idx_record_topic ON practice_records (topic_id)",
    "CREATE INDEX IF NOT EXISTS idx_ann_fetched ON announcements (fetched_at)",
    "CREATE INDEX IF NOT EXISTS idx_quiz_date ON quiz_log (quiz_date)",
)

#: 增量迁移语句：(表名, 列名, ALTER 语句)，用于兼容旧版本数据库文件
MIGRATION_STATEMENTS: Sequence[Tuple[str, str, str]] = (
    (
        "practice_records",
        "is_wrong",
        "ALTER TABLE practice_records ADD COLUMN is_wrong INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "exam_plans",
        "essay_score",
        "ALTER TABLE exam_plans ADD COLUMN essay_score REAL NOT NULL DEFAULT 65",
    ),
)


def today_str() -> str:
    """返回今天的日期字符串（YYYY-MM-DD）。"""
    return date.today().isoformat()


def now_str() -> str:
    """返回当前时间字符串（YYYY-MM-DD HH:MM:SS）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """SQLite 数据访问对象。

    支持两种使用方式::

        db = Database()                 # 显式调用 init_schema()
        with Database() as db:          # 自动建库、关连接
            ...
    """

    def __init__(self, db_path=None, auto_init: bool = True) -> None:
        self.db_path = str(db_path or config.DB_PATH)
        self._conn: Optional[sqlite3.Connection] = None
        if auto_init:
            self.init_schema()

    # ------------------------------------------------------------ 连接管理
    @property
    def conn(self) -> sqlite3.Connection:
        """惰性创建数据库连接（行工厂设为 sqlite3.Row，便于按列名取值）。"""
        if self._conn is None:
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def close(self) -> None:
        """关闭连接。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------ 建表与种子
    def init_schema(self) -> None:
        """创建全部数据表与索引，并对旧版本数据库执行增量迁移。"""
        cur = self.conn.cursor()
        for statement in SCHEMA_STATEMENTS:
            cur.execute(statement)
        self._migrate(cur)
        self.conn.commit()

    def _migrate(self, cur: sqlite3.Cursor) -> None:
        """补齐旧数据库缺失的列（幂等，重复执行无副作用）。

        旧版本的 ``practice_records`` 没有 ``is_wrong``、``exam_plans``
        没有 ``essay_score``；此处通过 PRAGMA 探测后 ALTER 补齐，
        保证老用户的成绩数据不会因为升级而丢失。
        """
        for table, column, statement in MIGRATION_STATEMENTS:
            cur.execute(f"PRAGMA table_info({table})")
            columns = {row["name"] for row in cur.fetchall()}
            if columns and column not in columns:
                cur.execute(statement)

    def seed(self) -> None:
        """写入模块字典、考点字典与知识库种子数据（幂等）。"""
        cur = self.conn.cursor()
        for name, code, weight, topics in config.MODULE_SEED:
            cur.execute(
                "INSERT OR IGNORE INTO modules (code, name, weight) VALUES (?, ?, ?)",
                (code, name, weight),
            )
            cur.execute("SELECT id FROM modules WHERE code = ?", (code,))
            module_id = cur.fetchone()["id"]
            for topic_name in topics:
                cur.execute(
                    "INSERT OR IGNORE INTO topics (module_id, name) VALUES (?, ?)",
                    (module_id, topic_name),
                )
        for keyword, category, content, example in config.KNOWLEDGE_SEED:
            cur.execute(
                "INSERT OR IGNORE INTO knowledge_items "
                "(keyword, category, content, example) VALUES (?, ?, ?, ?)",
                (keyword, category, content, example),
            )
        self.conn.commit()

    def reset(self) -> None:
        """清空所有业务数据（保留表结构），用于测试与数据重置。"""
        cur = self.conn.cursor()
        for table in (
            "practice_records",
            "announcements",
            "exam_plans",
            "knowledge_items",
            "quiz_log",
            "topics",
            "modules",
        ):
            cur.execute(f"DELETE FROM {table}")
        cur.execute("DELETE FROM sqlite_sequence")
        self.conn.commit()

    # ------------------------------------------------------------ 模块/考点
    def list_modules(self) -> List[Module]:
        """返回全部行测模块。"""
        rows = self.conn.execute("SELECT * FROM modules ORDER BY id").fetchall()
        return [Module.from_row(row) for row in rows]

    def get_module_by_name(self, name: str) -> Optional[Module]:
        """按模块名称精确查询模块。"""
        row = self.conn.execute("SELECT * FROM modules WHERE name = ?", (name,)).fetchone()
        return Module.from_row(row) if row else None

    def list_topics(self, module_id: Optional[int] = None) -> List[Topic]:
        """返回考点列表，可按模块过滤。"""
        if module_id is None:
            rows = self.conn.execute("SELECT * FROM topics ORDER BY id").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM topics WHERE module_id = ? ORDER BY id", (module_id,)
            ).fetchall()
        return [Topic.from_row(row) for row in rows]

    def get_topic_by_name(self, module_id: int, name: str) -> Optional[Topic]:
        """按模块 + 考点名称查询考点。"""
        row = self.conn.execute(
            "SELECT * FROM topics WHERE module_id = ? AND name = ?", (module_id, name)
        ).fetchone()
        return Topic.from_row(row) if row else None

    def add_topic(self, module_id: int, name: str, difficulty: float = 0.5) -> int:
        """新增自定义考点，返回考点 id。"""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO topics (module_id, name, difficulty) VALUES (?, ?, ?)",
            (module_id, name, difficulty),
        )
        self.conn.commit()
        topic = self.get_topic_by_name(module_id, name)
        return topic.id if topic else 0

    # ------------------------------------------------------------ 练习记录
    def add_record(
        self,
        record_date: str,
        module_id: int,
        total_questions: int,
        correct_questions: int,
        duration_seconds: int,
        topic_id: Optional[int] = None,
        note: str = "",
        is_wrong: bool = False,
    ) -> int:
        """插入一条练习记录，返回新记录 id。"""
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO practice_records
                (record_date, module_id, topic_id, total_questions,
                 correct_questions, duration_seconds, note, is_wrong, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_date,
                module_id,
                topic_id,
                total_questions,
                correct_questions,
                duration_seconds,
                note,
                int(bool(is_wrong)),
                now_str(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_record(self, record_id: int) -> Optional[PracticeRecord]:
        """按 id 查询单条练习记录。"""
        row = self.conn.execute(
            f"{self._record_select()} WHERE r.id = ?", (record_id,)
        ).fetchone()
        return PracticeRecord.from_row(row) if row else None

    def list_records(
        self,
        module_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[PracticeRecord]:
        """多条件查询练习记录（按日期倒序）。"""
        sql = self._record_select() + " WHERE 1 = 1"
        params: List[object] = []
        if module_id is not None:
            sql += " AND r.module_id = ?"
            params.append(module_id)
        if start_date:
            sql += " AND r.record_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND r.record_date <= ?"
            params.append(end_date)
        sql += " ORDER BY r.record_date DESC, r.id DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [PracticeRecord.from_row(row) for row in rows]

    def update_record(self, record_id: int, **fields) -> bool:
        """按字段更新练习记录，返回是否更新成功。"""
        allowed = {
            "record_date",
            "module_id",
            "topic_id",
            "total_questions",
            "correct_questions",
            "duration_seconds",
            "note",
            "is_wrong",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "is_wrong" in updates:
            updates["is_wrong"] = int(bool(updates["is_wrong"]))
        if not updates:
            return False
        assignments = ", ".join(f"{key} = ?" for key in updates)
        params = list(updates.values()) + [record_id]
        cur = self.conn.cursor()
        cur.execute(
            f"UPDATE practice_records SET {assignments} WHERE id = ?", params
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete_record(self, record_id: int) -> bool:
        """删除一条练习记录，返回是否删除成功。"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM practice_records WHERE id = ?", (record_id,))
        self.conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _record_select() -> str:
        """练习记录联表查询的公共 SELECT 片段。"""
        return (
            "SELECT r.*, m.name AS module_name, t.name AS topic_name "
            "FROM practice_records r "
            "LEFT JOIN modules m ON m.id = r.module_id "
            "LEFT JOIN topics t ON t.id = r.topic_id"
        )

    def count_records(self, module_id: Optional[int] = None) -> int:
        """统计练习记录条数。"""
        if module_id is None:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM practice_records").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM practice_records WHERE module_id = ?",
                (module_id,),
            ).fetchone()
        return int(row["c"])

    def list_wrong_records(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[PracticeRecord]:
        """查询带错题标记的练习记录（按日期倒序）。"""
        sql = self._record_select() + " WHERE r.is_wrong = 1"
        params: List[object] = []
        if start_date:
            sql += " AND r.record_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND r.record_date <= ?"
            params.append(end_date)
        sql += " ORDER BY r.record_date DESC, r.id DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [PracticeRecord.from_row(row) for row in rows]

    def count_wrong_records(self) -> int:
        """统计错题记录条数。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM practice_records WHERE is_wrong = 1"
        ).fetchone()
        return int(row["c"])

    def set_wrong_flag(self, record_id: int, is_wrong: bool = True) -> bool:
        """设置 / 取消某条记录的错题标记。"""
        return self.update_record(record_id, is_wrong=is_wrong)

    def module_aggregate(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[Dict[str, object]]:
        """按模块聚合练习数据，供诊断模块生成雷达图使用。"""
        sql = (
            "SELECT m.id AS module_id, m.name AS module_name, "
            "COUNT(r.id) AS records, "
            "COALESCE(SUM(r.total_questions), 0) AS total_questions, "
            "COALESCE(SUM(r.correct_questions), 0) AS correct_questions, "
            "COALESCE(SUM(r.duration_seconds), 0) AS duration_seconds "
            "FROM modules m LEFT JOIN practice_records r ON r.module_id = m.id"
        )
        params: List[object] = []
        if start_date:
            sql += " AND r.record_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND r.record_date <= ?"
            params.append(end_date)
        sql += " GROUP BY m.id, m.name ORDER BY m.id"
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def topic_aggregate(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[Dict[str, object]]:
        """按考点聚合练习数据，用于定位薄弱考点与生成复盘清单。"""
        sql = (
            "SELECT t.id AS topic_id, t.name AS topic_name, m.name AS module_name, "
            "COUNT(r.id) AS records, "
            "COALESCE(SUM(r.is_wrong), 0) AS wrong_records, "
            "COALESCE(SUM(r.total_questions), 0) AS total_questions, "
            "COALESCE(SUM(r.correct_questions), 0) AS correct_questions, "
            "COALESCE(SUM(r.duration_seconds), 0) AS duration_seconds "
            "FROM practice_records r "
            "JOIN topics t ON t.id = r.topic_id "
            "JOIN modules m ON m.id = r.module_id "
        )
        params: List[object] = []
        conditions = []
        if start_date:
            conditions.append("r.record_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("r.record_date <= ?")
            params.append(end_date)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " GROUP BY t.id, t.name, m.name HAVING total_questions > 0"
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def daily_aggregate(
        self, days: int = 30, module_id: Optional[int] = None
    ) -> List[Dict[str, object]]:
        """按日期聚合，返回最近 days 天的正确率趋势数据。"""
        sql = (
            "SELECT r.record_date AS record_date, "
            "SUM(r.total_questions) AS total_questions, "
            "SUM(r.correct_questions) AS correct_questions, "
            "SUM(r.duration_seconds) AS duration_seconds "
            "FROM practice_records r WHERE 1 = 1"
        )
        params: List[object] = []
        if module_id is not None:
            sql += " AND r.module_id = ?"
            params.append(module_id)
        sql += " GROUP BY r.record_date ORDER BY r.record_date DESC LIMIT ?"
        params.append(days)
        rows = self.conn.execute(sql, params).fetchall()
        return list(reversed([dict(row) for row in rows]))

    # ------------------------------------------------------------ 公告
    def save_announcements(self, items: Iterable[Announcement]) -> Tuple[int, int]:
        """批量写入公告，按 url 去重。

        :return: (新增条数, 重复跳过条数)
        """
        inserted = 0
        skipped = 0
        cur = self.conn.cursor()
        for item in items:
            cur.execute(
                """
                INSERT OR IGNORE INTO announcements
                    (source, title, url, publish_date, matched_keyword, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source,
                    item.title,
                    item.url,
                    item.publish_date,
                    item.matched_keyword,
                    item.fetched_at or now_str(),
                ),
            )
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1
        self.conn.commit()
        return inserted, skipped

    def list_announcements(
        self, keyword: Optional[str] = None, limit: int = 50
    ) -> List[Announcement]:
        """查询公告，可按关键词模糊过滤。"""
        if keyword:
            rows = self.conn.execute(
                "SELECT * FROM announcements "
                "WHERE title LIKE ? OR matched_keyword LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (f"%{keyword}%", f"%{keyword}%", limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM announcements ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Announcement.from_row(row) for row in rows]

    def count_announcements(self) -> int:
        """统计已入库公告数量。"""
        row = self.conn.execute("SELECT COUNT(*) AS c FROM announcements").fetchone()
        return int(row["c"])

    # ------------------------------------------------------------ 知识库
    def search_knowledge(self, keyword: str, limit: int = 20) -> List[KnowledgeItem]:
        """按关键词模糊检索知识库（命中关键词或正文）。"""
        rows = self.conn.execute(
            "SELECT * FROM knowledge_items "
            "WHERE keyword LIKE ? OR content LIKE ? OR category LIKE ? "
            "ORDER BY (keyword LIKE ?) DESC, id ASC LIMIT ?",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()
        return [KnowledgeItem.from_row(row) for row in rows]

    def list_knowledge(self, category: Optional[str] = None) -> List[KnowledgeItem]:
        """列出知识库条目，可按分类过滤。"""
        if category:
            rows = self.conn.execute(
                "SELECT * FROM knowledge_items WHERE category = ? ORDER BY id",
                (category,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM knowledge_items ORDER BY id").fetchall()
        return [KnowledgeItem.from_row(row) for row in rows]

    def add_knowledge(
        self, keyword: str, category: str, content: str, example: str = ""
    ) -> int:
        """新增知识库条目，返回条目 id。"""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO knowledge_items "
            "(keyword, category, content, example) VALUES (?, ?, ?, ?)",
            (keyword, category, content, example),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def list_knowledge_categories(self) -> List[str]:
        """返回知识库中已有的全部分类。"""
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM knowledge_items ORDER BY category"
        ).fetchall()
        return [row["category"] for row in rows]

    # ------------------------------------------------------------ 备考目标
    def set_exam_plan(
        self,
        exam_name: str,
        exam_date: str,
        target_score: float,
        essay_score: float = 65.0,
    ) -> None:
        """新增或更新备考目标（含申论预期分）。"""
        self.conn.execute(
            "INSERT INTO exam_plans (exam_name, exam_date, target_score, essay_score, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (exam_name) DO UPDATE SET "
            "exam_date = excluded.exam_date, target_score = excluded.target_score, "
            "essay_score = excluded.essay_score",
            (exam_name, exam_date, target_score, essay_score, now_str()),
        )
        self.conn.commit()

    def get_exam_plan(self) -> Optional[Dict[str, object]]:
        """返回最近设置的备考目标。"""
        row = self.conn.execute(
            "SELECT * FROM exam_plans ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------ 闪卡抽测记录
    def add_quiz_log(
        self,
        keyword: str,
        category: str,
        user_answer: str,
        score: float,
        passed: bool,
        quiz_date: Optional[str] = None,
        elapsed_seconds: float = 0.0,
    ) -> int:
        """记录一次闪卡作答，返回日志 id。"""
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO quiz_log
                (quiz_date, keyword, category, user_answer, score,
                 passed, elapsed_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quiz_date or today_str(),
                keyword,
                category,
                user_answer,
                float(score),
                int(bool(passed)),
                float(elapsed_seconds),
                now_str(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def quiz_stats(self, days: Optional[int] = None) -> Dict[str, object]:
        """统计闪卡作答情况：次数、平均分、通过率。"""
        sql = "SELECT COUNT(*) AS attempts, AVG(score) AS avg_score, SUM(passed) AS passed FROM quiz_log"
        params: List[object] = []
        if days:
            sql += " WHERE quiz_date >= ?"
            params.append((date.today() - timedelta(days=days)).isoformat())
        row = self.conn.execute(sql, params).fetchone()
        attempts = int(row["attempts"] or 0)
        passed = int(row["passed"] or 0)
        return {
            "attempts": attempts,
            "passed": passed,
            "avg_score": round(float(row["avg_score"] or 0.0), 1),
            "pass_rate": round(passed / attempts * 100, 1) if attempts else 0.0,
        }

    def quiz_weak_keywords(self, limit: int = 5) -> List[Dict[str, object]]:
        """返回闪卡作答中平均分最低的知识点，供复盘参考。"""
        rows = self.conn.execute(
            "SELECT keyword, COUNT(*) AS attempts, AVG(score) AS avg_score "
            "FROM quiz_log GROUP BY keyword "
            "HAVING attempts > 0 ORDER BY avg_score ASC, attempts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
