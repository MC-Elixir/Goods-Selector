# Amazon Selector

Amazon Best Seller 选品自动化系统。从 Amazon 榜单挖掘产品 → 1688 拍立淘官方 API 找货源 → 利润预测 → 多维度评分 → 筛选 → 卖家精灵市场分析 → 输出候选选品池。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量（复制 .env.example 为 .env 并填写）
cp .env.example .env

# 3. 初始化数据库
python -m db.init_db

# 4. 跑通整条流水线（单个类目试跑）
python main.py --category "Home & Kitchen" --limit 10
```

## 目录结构

```
amazon_selector/
├── config/         # 配置（API key、阈值、评分权重）
├── crawlers/       # Amazon BSR 数据采集
├── matchers/       # 1688 拍立淘 API 封装
├── analyzers/      # 利润模型 / 评分引擎 / 卖家精灵
├── pipeline/       # 主流程编排 + 筛选规则
├── db/             # SQLAlchemy 模型 + migrations
├── reports/        # Excel / Markdown 报告导出
├── data/           # 本地缓存、图片、导出文件
├── docs/           # PRD、设计文档
├── tests/          # 单元测试
├── scripts/        # 一次性脚本（数据迁移、调试）
└── main.py         # 入口
```

## 模块依赖

| 上游模块 | 下游模块 |
|---|---|
| `crawlers/amazon_bsr.py` | `matchers/alibaba_pailitao.py` |
| `matchers/alibaba_pailitao.py` | `analyzers/profit_model.py` |
| `analyzers/maijiajingling.py` | `analyzers/scorer.py` |
| `analyzers/profit_model.py` + `analyzers/scorer.py` | `pipeline/filters.py` |
| `pipeline/filters.py` | `reports/exporter.py` |

## 文档

- [PRD](docs/PRD.md)：产品需求文档
- [Database Schema](docs/database_schema.md)：数据库表设计
- [Scoring Spec](docs/scoring_spec.md)：评分维度详解

## 开发节奏

详见 PRD 的"开发计划"章节。
