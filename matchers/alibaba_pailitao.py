"""
1688 拍立淘官方 API 封装
========================

阿里巴巴开放平台 https://open.1688.com/
图搜接口（示例）：alibaba.icbu.image.search / alibaba.tcbs.image.search
鉴权方式：MD5 / HMAC-SHA1 签名

环境变量：
    ALIBABA_APP_KEY
    ALIBABA_APP_SECRET
    ALIBABA_ACCESS_TOKEN
    ALIBABA_API_GATEWAY

接口暴露：
    PailitaoClient.search_by_image(image_bytes_or_url) -> list[SupplierDTO]
    PailitaoClient.get_offer_detail(offer_id) -> SupplierDetailDTO
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings


# ============================================================
# DTO
# ============================================================
@dataclass
class SupplierDTO:
    alibaba_offer_id: str
    supplier_name: Optional[str] = None
    offer_url: Optional[str] = None
    offer_image_url: Optional[str] = None
    image_similarity: Optional[float] = None
    text_similarity: Optional[float] = None
    moq: Optional[int] = None
    base_price_cny: Optional[float] = None
    price_tiers: list[dict] = field(default_factory=list)
    monthly_sales: Optional[int] = None
    repeat_buyer_rate: Optional[float] = None
    is_factory: Optional[bool] = None
    raw_data: dict = field(default_factory=dict)


# ============================================================
# 签名工具
# ============================================================
def md5_sign(params: dict, app_secret: str) -> str:
    """1688 开放平台 MD5 签名算法（典型实现）。

    步骤：
        1. 参数按 key 字典序排序
        2. 拼接 secret + k1v1k2v2... + secret
        3. MD5，结果转大写
    """
    sorted_pairs = sorted(params.items())
    raw = app_secret + "".join(f"{k}{v}" for k, v in sorted_pairs) + app_secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


# ============================================================
# Client
# ============================================================
class PailitaoClient:
    """拍立淘客户端。"""

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        gateway: Optional[str] = None,
    ):
        self.app_key = app_key or settings.alibaba_app_key
        self.app_secret = app_secret or settings.alibaba_app_secret
        self.access_token = access_token or settings.alibaba_access_token
        self.gateway = gateway or settings.alibaba_api_gateway

        if not self.app_key or not self.app_secret:
            logger.warning("Alibaba app key/secret 未配置，调用会失败")

    # --------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def search_by_image(
        self,
        image_url: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        top_k: int = 20,
        min_similarity: float = 0.7,
    ) -> list[SupplierDTO]:
        """图搜：返回相似 1688 货源列表，按相似度降序。

        Args:
            image_url      Amazon 主图 URL（二选一）
            image_bytes    本地图片字节（二选一）
            top_k          返回前 N 条
            min_similarity 相似度阈值，低于此值过滤
        """
        if not (image_url or image_bytes):
            raise ValueError("image_url 和 image_bytes 至少传一个")

        # TODO: 实现签名 + 图片上传 + 调用 + 结果解析
        raise NotImplementedError(
            "拍立淘 API 接口名 / 参数请按 1688 开放平台文档实现"
        )

    # --------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    def get_offer_detail(self, offer_id: str) -> SupplierDTO:
        """拉详情：MOQ / 阶梯价 / 月销 / 回头率。"""
        raise NotImplementedError("接入开放平台详情接口")
