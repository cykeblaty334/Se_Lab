# -*- coding: utf-8 -*-
"""CEATS 公考量化分析系统 - 源码包。

CEATS (Civil Service Exam Analysis & Tracking System) 采用
"轻界面、重逻辑、数据驱动" 的分层设计：

    config      全局配置与常量
    models      领域数据模型
    database    数据访问层（SQLite 持久化）
    recorder    业务层：成绩录入与指标计算
    analyzer    业务层：弱项诊断与统计分析
    scraper     业务层：招考公告抓取
    knowledge   业务层：专家规则知识库
    visualizer  展示层：Matplotlib 可视化
    main        展示层：命令行交互入口
"""

__version__ = "1.0.0"
__all__ = [
    "config",
    "models",
    "database",
    "recorder",
    "analyzer",
    "scraper",
    "knowledge",
    "visualizer",
]
