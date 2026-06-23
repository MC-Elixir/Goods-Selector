"""
SQLAlchemy ORM 模型

核心实体：
- Product           Amazon 端产品
- Supplier          1688 货源（一对多）
- ProfitSnapshot    利润快照（参数会变所以做版本快照）
- Score             多维度评分
- MarketAnalysis    卖家精灵市场数据
- RunLog            一次流水线执行的元数据
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ============================================================
# 1. Product — Amazon 端
# ============================================================
class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asin: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    marketplace: Mapped[str] = mapped_column(String(8), nullable=False, default="US")

    category: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(120))

    title: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(120), index=True)

    price: Mapped[Optional[float]] = mapped_column(Float)
    bsr_rank: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    rating: Mapped[Optional[float]] = mapped_column(Float)
    review_count: Mapped[Optional[int]] = mapped_column(Integer)
    review_velocity_30d: Mapped[Optional[int]] = mapped_column(Integer)  # 30 天评论增速

    # 物理属性（影响 FBA 和头程）
    weight_kg: Mapped[Optional[float]] = mapped_column(Float)
    length_cm: Mapped[Optional[float]] = mapped_column(Float)
    width_cm: Mapped[Optional[float]] = mapped_column(Float)
    height_cm: Mapped[Optional[float]] = mapped_column(Float)

    main_image_url: Mapped[Optional[str]] = mapped_column(Text)
    listing_url: Mapped[Optional[str]] = mapped_column(Text)

    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)  # 保留原始接口返回

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    suppliers: Mapped[list["Supplier"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    profit_snapshots: Mapped[list["ProfitSnapshot"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    scores: Mapped[list["Score"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    market_analyses: Mapped[list["MarketAnalysis"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("asin", "marketplace", name="uq_product_asin_marketplace"),
        Index("ix_product_category_bsr", "category", "bsr_rank"),
    )


# ============================================================
# 2. Supplier — 1688 货源
# ============================================================
class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )

    alibaba_offer_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(200))
    supplier_url: Mapped[Optional[str]] = mapped_column(Text)
    offer_url: Mapped[Optional[str]] = mapped_column(Text)
    offer_image_url: Mapped[Optional[str]] = mapped_column(Text)

    # 拍立淘返回的相似度 0-1
    image_similarity: Mapped[Optional[float]] = mapped_column(Float, index=True)
    text_similarity: Mapped[Optional[float]] = mapped_column(Float)

    moq: Mapped[Optional[int]] = mapped_column(Integer)            # 起订量
    price_tiers: Mapped[Optional[list]] = mapped_column(JSON)      # [{qty:50,price:12.5},...]
    base_price_cny: Mapped[Optional[float]] = mapped_column(Float) # 阶梯价中位

    monthly_sales: Mapped[Optional[int]] = mapped_column(Integer)
    repeat_buyer_rate: Mapped[Optional[float]] = mapped_column(Float)
    is_factory: Mapped[Optional[bool]] = mapped_column(Boolean)    # 实力商家 / 工厂

    # ── 匹配验证相关 ──────────────────────────────────────
    title_cn: Mapped[Optional[str]] = mapped_column(String(500))           # 1688 中文标题
    product_dimensions_cm: Mapped[Optional[str]] = mapped_column(String(100))  # 规格尺寸
    product_weight_g: Mapped[Optional[float]] = mapped_column(Float)           # 重量（克）
    material: Mapped[Optional[str]] = mapped_column(String(100))               # 材质
    color: Mapped[Optional[str]] = mapped_column(String(50))                   # 颜色
    match_quality_score: Mapped[Optional[float]] = mapped_column(Float)        # 匹配质量 0-1
    match_verification_method: Mapped[Optional[str]] = mapped_column(String(20))  # "heuristic"|"llm"|"unverified"

    matched_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    product: Mapped[Product] = relationship(back_populates="suppliers")

    __table_args__ = (
        UniqueConstraint(
            "product_id", "alibaba_offer_id", name="uq_supplier_product_offer"
        ),
    )


# ============================================================
# 3. ProfitSnapshot — 利润快照
# ============================================================
class ProfitSnapshot(Base):
    __tablename__ = "profit_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )

    # 收入
    selling_price: Mapped[float] = mapped_column(Float, nullable=False)
    batch_qty: Mapped[int] = mapped_column(Integer, default=200)

    # 成本明细（USD）
    purchase_cost: Mapped[float] = mapped_column(Float, default=0.0)
    shipping_cost: Mapped[float] = mapped_column(Float, default=0.0)
    fba_fee: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    ad_cost: Mapped[float] = mapped_column(Float, default=0.0)
    return_loss: Mapped[float] = mapped_column(Float, default=0.0)
    exchange_loss: Mapped[float] = mapped_column(Float, default=0.0)
    other_costs: Mapped[float] = mapped_column(Float, default=0.0)

    # 结果
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    net_profit: Mapped[float] = mapped_column(Float, default=0.0)
    profit_margin: Mapped[float] = mapped_column(Float, default=0.0)  # 净利率

    # 用了哪一版参数（便于回溯）
    params_version: Mapped[Optional[str]] = mapped_column(String(40))
    params_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)

    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    product: Mapped[Product] = relationship(back_populates="profit_snapshots")
    supplier: Mapped[Supplier] = relationship()


# ============================================================
# 4. Score — 多维度评分
# ============================================================
class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 各维度得分（0-1 归一化）
    profit_score: Mapped[float] = mapped_column(Float, default=0.0)
    demand_score: Mapped[float] = mapped_column(Float, default=0.0)
    competition_score: Mapped[float] = mapped_column(Float, default=0.0)
    supply_score: Mapped[float] = mapped_column(Float, default=0.0)
    logistics_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)

    # 综合分（0-100）
    total_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)

    # 是否通过硬性筛选
    passed_hard_filter: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejection_reasons: Mapped[Optional[list]] = mapped_column(JSON)  # ["margin_too_low", ...]

    weights_version: Mapped[Optional[str]] = mapped_column(String(40))
    weights_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)

    scored_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    product: Mapped[Product] = relationship(back_populates="scores")


# ============================================================
# 5. MarketAnalysis — 卖家精灵市场数据
# ============================================================
class MarketAnalysis(Base):
    __tablename__ = "market_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 关键词与流量
    main_keyword: Mapped[Optional[str]] = mapped_column(String(200))
    search_volume_monthly: Mapped[Optional[int]] = mapped_column(Integer)
    keyword_difficulty: Mapped[Optional[float]] = mapped_column(Float)

    # 竞争格局
    competing_listings: Mapped[Optional[int]] = mapped_column(Integer)
    top10_revenue_share: Mapped[Optional[float]] = mapped_column(Float)  # 头部 10 集中度
    avg_review_count_top10: Mapped[Optional[int]] = mapped_column(Integer)
    avg_price_top10: Mapped[Optional[float]] = mapped_column(Float)

    # 机会度
    opportunity_score: Mapped[Optional[float]] = mapped_column(Float)
    seasonality: Mapped[Optional[dict]] = mapped_column(JSON)  # {"month_1": 0.8, ...}

    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)  # 原始返回保留

    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    product: Mapped[Product] = relationship(back_populates="market_analyses")


# ============================================================
# 6. RunLog — 流水线执行日志
# ============================================================
class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    pipeline_version: Mapped[Optional[str]] = mapped_column(String(40))
    category: Mapped[Optional[str]] = mapped_column(String(120))
    marketplace: Mapped[Optional[str]] = mapped_column(String(8))

    # 各阶段计数
    products_crawled: Mapped[int] = mapped_column(Integer, default=0)
    suppliers_matched: Mapped[int] = mapped_column(Integer, default=0)
    profits_calculated: Mapped[int] = mapped_column(Integer, default=0)
    candidates_after_filter: Mapped[int] = mapped_column(Integer, default=0)

    # API 成本（按需记录）
    api_calls: Mapped[Optional[dict]] = mapped_column(JSON)
    # {"keepa": 50, "alibaba_pailitao": 30, "mjjl": 20}

    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="running")
    # running | success | failed | aborted
    error_message: Mapped[Optional[str]] = mapped_column(Text)
