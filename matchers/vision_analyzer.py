"""
视觉分析器
==========
输入 Amazon 产品图片（URL 或字节），输出结构化产品信息和 1688 中文搜索关键词。

支持两个后端（自动选择，PPIO 优先）：

  PPIO（推荐）
      OpenAI 兼容接口，国内访问稳定，支持 Qwen-VL 等多种视觉模型
      环境变量：PPIO_API_KEY, PPIO_API_BASE, PPIO_MODEL

  Anthropic
      Claude Vision，备用方案
      环境变量：ANTHROPIC_API_KEY, ANTHROPIC_MODEL

流程：
    图片 URL / bytes → 下载 → base64 → 调 API → 解析 JSON → ProductAnalysis
    → keywords_zh → alibaba_text_search
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

import httpx
from loguru import logger

from config.settings import settings

# 可选依赖，运行时按需导入
try:
    import openai as _openai
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

try:
    import anthropic as _anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


# ============================================================
# DTO
# ============================================================
@dataclass
class ProductAnalysis:
    category_zh: str                          # 中文品类（如：折叠桌）
    keywords_zh: list[str]                    # 1688 搜索关键词，从精准到宽泛
    title_zh: str                             # 建议搜索标题（≤20字）
    material: Optional[str] = None
    color: Optional[str] = None
    key_features: list[str] = field(default_factory=list)
    has_dangerous_attr: bool = False          # 带电/液体/强磁等
    description_en: str = ""


# ============================================================
# Prompt（与后端无关，通用）
# ============================================================
_PROMPT = """\
你是一个跨境电商选品专家，专注于在1688寻找Amazon产品的对应货源。
分析这张Amazon产品主图，提取用于1688搜索的关键信息。

请严格输出JSON，不要包含任何其他文字：
{
  "category_zh": "产品中文品类名（简洁，如：折叠桌、USB充电器、瑜伽垫）",
  "material": "主要材质（如：铝合金、ABS塑料、棉麻，无法判断则填null）",
  "color": "主要颜色（如：黑色、银色，多色填'多色'，无法判断填null）",
  "key_features": ["功能特点1", "功能特点2"],
  "keywords_zh": [
    "最精准关键词（含材质/功能，如：铝合金折叠野餐桌）",
    "精准关键词2",
    "宽泛关键词（仅品类，如：折叠桌）",
    "替代叫法或长尾词"
  ],
  "title_zh": "建议的1688搜索标题，不超过20字",
  "has_dangerous_attr": false,
  "description_en": "One sentence English description"
}

要求：
- keywords_zh 至少4个，从精准到宽泛排列，符合1688买家搜索习惯
- 避免品牌词和型号词
- 产品明显含电池、液体、强磁铁则将 has_dangerous_attr 设为 true\
"""

Provider = Literal["ppio", "anthropic", "auto"]


# ============================================================
# VisionAnalyzer
# ============================================================
class VisionAnalyzer:
    """分析 Amazon 产品图片，提取 1688 搜索关键词。

    provider 选项：
        "auto"      根据已配置的 Key 自动选择（PPIO 优先）
        "ppio"      PPIO OpenAI 兼容接口（需 PPIO_API_KEY）
        "anthropic" Anthropic Claude Vision（需 ANTHROPIC_API_KEY）
    """

    def __init__(
        self,
        provider: Provider = "auto",
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
    ):
        self._provider = self._resolve_provider(provider)
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._client = self._build_client()
        self._cache = _make_cache("vision")
        logger.debug(f"[vision] provider={self._provider} model={self._model}")

    # --------------------------------------------------------
    def analyze(
        self,
        image_url: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
    ) -> ProductAnalysis:
        """分析产品图片，返回结构化产品信息。"""
        if not (image_url or image_bytes):
            raise ValueError("image_url 和 image_bytes 至少传一个")

        if image_url and not image_bytes:
            image_bytes = _download_image(image_url)

        cache_key = "va_" + hashlib.sha256(image_bytes).hexdigest()[:32]
        if self._cache is not None and cache_key in self._cache:
            logger.debug(f"[vision] cache hit {cache_key[:16]}")
            return self._cache[cache_key]

        result = self._call(image_bytes)
        logger.info(
            f"[vision] {result.category_zh} | "
            f"keywords={result.keywords_zh[:2]} | dangerous={result.has_dangerous_attr}"
        )

        if self._cache is not None:
            self._cache.set(cache_key, result, expire=settings.cache_ttl_seconds)
        return result

    # --------------------------------------------------------
    def _call(self, image_bytes: bytes) -> ProductAnalysis:
        if self._provider == "ppio":
            return self._call_openai_compatible(image_bytes)
        return self._call_anthropic(image_bytes)

    def _call_openai_compatible(self, image_bytes: bytes) -> ProductAnalysis:
        """调用 PPIO 或其他 OpenAI 兼容接口。"""
        media_type = _detect_media_type(image_bytes)
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{media_type};base64,{b64}"

        logger.debug(
            f"[vision] {self._provider} → {self._model} "
            f"image={len(image_bytes)//1024}KB"
        )
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": _PROMPT},
                ],
            }],
        )
        return _parse_json_response(resp.choices[0].message.content)

    def _call_anthropic(self, image_bytes: bytes) -> ProductAnalysis:
        """调用 Anthropic Claude Vision。"""
        media_type = _detect_media_type(image_bytes)
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        logger.debug(f"[vision] anthropic → {self._model} image={len(image_bytes)//1024}KB")
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }],
        )
        return _parse_json_response(resp.content[0].text)

    # --------------------------------------------------------
    def _resolve_provider(self, provider: Provider) -> str:
        if provider != "auto":
            return provider
        return settings.vision_provider if settings.vision_provider != "none" else "ppio"

    def _build_client(self):
        if self._provider == "ppio":
            if not _HAS_OPENAI:
                raise ImportError("请先安装：pip install openai")
            key = self._api_key or settings.ppio_api_key
            base = self._api_base or settings.ppio_api_base
            if not key:
                raise ValueError("PPIO_API_KEY 未配置，请在 .env 中设置")
            self._model = self._model or settings.ppio_model
            return _openai.OpenAI(api_key=key, base_url=base)

        if self._provider == "anthropic":
            if not _HAS_ANTHROPIC:
                raise ImportError("请先安装：pip install anthropic")
            key = self._api_key or settings.anthropic_api_key
            if not key:
                raise ValueError("ANTHROPIC_API_KEY 未配置，请在 .env 中设置")
            self._model = self._model or settings.anthropic_model
            return _anthropic.Anthropic(api_key=key)

        raise ValueError(f"未知 provider: {self._provider}，可选：ppio / anthropic")


# ============================================================
# Helpers
# ============================================================
def _parse_json_response(text: str) -> ProductAnalysis:
    """从模型响应中提取 JSON，容忍 markdown 代码块包裹。"""
    s = text.strip()
    if "```" in s:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", s)
        if m:
            s = m.group(1).strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]+\}", s)
        if not m:
            raise ValueError(f"模型返回非 JSON: {text[:300]}")
        data = json.loads(m.group(0))

    return ProductAnalysis(
        category_zh=data.get("category_zh", "未知品类"),
        keywords_zh=data.get("keywords_zh") or [data.get("category_zh", "")],
        title_zh=data.get("title_zh") or data.get("category_zh", ""),
        material=data.get("material"),
        color=data.get("color"),
        key_features=data.get("key_features") or [],
        has_dangerous_attr=bool(data.get("has_dangerous_attr", False)),
        description_en=data.get("description_en", ""),
    )


def _download_image(url: str) -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.amazon.com/",
    }
    with httpx.Client(timeout=20, follow_redirects=True) as c:
        r = c.get(url, headers=headers)
        r.raise_for_status()
        return r.content


def _detect_media_type(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _make_cache(ns: str):
    if not settings.enable_api_cache:
        return None
    try:
        import diskcache as dc
        return dc.Cache(str(settings.cache_dir / ns))
    except ImportError:
        return None
