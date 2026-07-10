"""
1688 货源匹配验证器
===================

两层验证：
  1. 启发式验证（默认）：标题关键词 + 属性匹配 + 搜索信号
  2. LLM 视觉验证（可选）：用大模型对比 Amazon 和 1688 产品图片

使用：
    verifier = Alibaba1688Verifier()
    verified = verifier.verify(suppliers, product, analysis, keywords)

    # 启用 LLM 视觉验证（对 top K 供应商调用大模型）
    llm = LLMVisualVerifier(api_key="...", model="qwen/qwen2.5-vl-72b-instruct")
    verified = llm.verify(suppliers, product, top_k=3)
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict
from typing import Optional

from loguru import logger

from agent.cancellation import CancelCheck, CancellationRequested, raise_if_cancelled
from matchers.alibaba_pailitao import SupplierDTO
from matchers.product_spec import compare_specs, spec_from_product, spec_from_supplier

# ── 阈值常量 ──────────────────────────────────────────────────
THRESHOLD_PASS = 0.40
THRESHOLD_DEMOTE = 0.40
SCORE_DEFAULT = 0.45


class Alibaba1688Verifier:
    """启发式匹配验证器。"""

    def __init__(
        self,
        threshold_pass: float = THRESHOLD_PASS,
        threshold_demote: float = THRESHOLD_DEMOTE,
    ):
        self.threshold_pass = threshold_pass
        self.threshold_demote = threshold_demote

    def verify(
        self,
        suppliers: list[SupplierDTO],
        product,
        analysis=None,
        search_keywords: list[str] = None,
    ) -> list[SupplierDTO]:
        if not suppliers:
            return []

        kw = search_keywords or []
        results: list[SupplierDTO] = []
        rejected: list[SupplierDTO] = []
        target_spec = spec_from_product(product, analysis)
        target_spec_payload = _spec_payload(target_spec)

        for sup in suppliers:
            original_method = (sup.match_verification_method or "").lower()
            if original_method != "mock" and not _title_is_relevant(sup, analysis, kw):
                sup.match_quality_score = 0.0
                sup.match_verification_method = "heuristic"
                sup.raw_data["target_spec"] = target_spec_payload
                sup.raw_data["spec_match"] = {
                    "score": 0.0,
                    "matched": [],
                    "missing": [],
                    "conflicts": ["title_relevance"],
                }
                _update_supplier_rank_scores(sup)
                rejected.append(sup)
                continue
            heuristic_score = self._compute_match_quality(sup, product, analysis, kw)
            spec_match = compare_specs(target_spec, spec_from_supplier(sup))
            sup.raw_data["target_spec"] = target_spec_payload
            sup.raw_data["spec_match"] = {
                "score": spec_match.score,
                "matched": spec_match.matched,
                "missing": spec_match.missing,
                "conflicts": spec_match.conflicts,
            }
            visual_score = self._visual_score(sup, product)
            sup.raw_data["visual_match"] = {
                "score": visual_score,
                "source": "image_similarity" if sup.image_similarity is not None else "availability",
            }
            score = 0.55 * heuristic_score + 0.30 * spec_match.score + 0.15 * visual_score
            if spec_match.conflicts:
                score *= max(0.45, 1 - 0.15 * len(spec_match.conflicts))
            sup.match_quality_score = round(score, 4)
            _update_supplier_rank_scores(sup)
            sup.match_verification_method = "heuristic"
            results.append(sup)

        results.sort(key=_supplier_sort_key, reverse=True)

        before = len(results)
        filtered = [s for s in results if (s.match_quality_score or 0) > self.threshold_demote]
        if len(filtered) < before + len(rejected):
            logger.info(f"[verifier] 过滤 {before + len(rejected) - len(filtered)} 条不匹配供应商 (threshold={self.threshold_demote})")

        if filtered:
            return filtered

        fallback = sorted([*results, *rejected], key=_supplier_sort_key, reverse=True)[:3]
        for sup in fallback:
            sup.match_verification_method = "heuristic_rejected"
        if fallback:
            logger.warning("[verifier] 全部供应商低于阈值，保留 top rejected 供人工复核")
        return fallback

    def _compute_match_quality(self, supplier, product, analysis, keywords):
        attr_score = self._attribute_score(supplier, analysis)
        title_score = self._title_score(supplier, analysis, keywords)
        search_score = self._search_relevance(supplier, keywords)
        return 0.35 * attr_score + 0.45 * title_score + 0.20 * search_score

    def _attribute_score(self, supplier, analysis):
        if analysis is None:
            return SCORE_DEFAULT
        checks = 0; passed = 0
        if analysis.material:
            checks += 1
            if supplier.material and _material_match(analysis.material, supplier.material):
                passed += 1
        if analysis.color:
            checks += 1
            if supplier.color and _color_match(analysis.color, supplier.color):
                passed += 1
        if supplier.product_dimensions_cm:
            checks += 1; passed += 0.5
        return (passed / checks) if checks else SCORE_DEFAULT

    def _title_score(self, supplier, analysis, keywords):
        offer_title = supplier.title_cn or supplier.raw_data.get("title_cn", "")
        if not offer_title:
            return SCORE_DEFAULT
        score = 0.0; checks = 0
        if analysis:
            if analysis.category_zh:
                checks += 1
                if analysis.category_zh in offer_title: score += 1.0
            if analysis.key_features:
                checks += 1
                hits = sum(1 for f in analysis.key_features if f and f in offer_title)
                if hits: score += min(hits / len(analysis.key_features), 1.0)
            if analysis.material:
                checks += 1
                if any(a in offer_title for a in _material_aliases(analysis.material)):
                    score += 1.0
        if keywords:
            checks += 1
            score += _keyword_title_score(offer_title, keywords)
        return (score / checks) if checks else SCORE_DEFAULT

    def _search_relevance(self, supplier, keywords):
        ms = supplier.monthly_sales
        if ms is None: return 0.6
        if ms >= 10000: return 1.0
        if ms >= 1000: return 0.8
        if ms >= 100: return 0.7
        return 0.6

    def _visual_score(self, supplier, product) -> float:
        if supplier.image_similarity is not None:
            return _clamp(float(supplier.image_similarity))
        product_has_image = bool(getattr(product, "main_image_url", None))
        supplier_has_image = bool(getattr(supplier, "offer_image_url", None))
        if product_has_image and supplier_has_image:
            return 0.55
        if product_has_image or supplier_has_image:
            return 0.35
        return SCORE_DEFAULT


def _spec_payload(spec) -> dict:
    data = asdict(spec)
    data.pop("raw_text", None)
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


class LLMVisualVerifier:
    """用大模型对比 Amazon 产品图片和 1688 供应商图片，判断是否为同类产品。

    仅对 top K 供应商调用（控制成本），返回每个供应商的视觉匹配分数。

    用法：
        llm = LLMVisualVerifier()
        results = llm.verify(suppliers, product, top_k=3)
        # results[i].match_quality_score 会被更新为 LLM 判断的分数
    """

    _PROMPT = """你是一个跨境电商选品专家。请对比以下两张产品图片：

图1是Amazon在售产品（主图），图2是1688供应商的产品图片。

请判断这两个产品是否为同类产品（功能、外观、形态相似），并给出匹配度评分。

严格输出JSON，不要包含其他文字：
{
  "is_match": true/false,
  "confidence": 0.0-1.0,
  "reason": "简短中文说明",
  "differences": ["差异1", "差异2"]
}

判断标准：
- 外观形态是否相似（形状、结构）
- 功能用途是否相同
- 尺寸规格是否接近（通过图片比例判断）
- 材质质感是否一致

注意：颜色差异可以接受（同款不同色），但形状/结构/功能不同则为不匹配。"""

    def __init__(self, api_key: str = None, api_base: str = None, model: str = None):
        from config.settings import settings
        self._api_key = api_key or settings.ppio_api_key
        self._api_base = api_base or settings.ppio_api_base
        self._model = model or settings.ppio_model or "qwen/qwen2.5-vl-72b-instruct"
        if not self._api_key:
            raise ValueError("PPIO_API_KEY 未配置，无法使用 LLM 视觉验证")

    def verify(
        self,
        suppliers: list[SupplierDTO],
        product,
        top_k: int = 3,
        threshold: float = 0.3,
        eligible_suppliers: list[SupplierDTO] | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> list[SupplierDTO]:
        """对 top K 供应商进行 LLM 视觉验证，更新 match_quality_score。

        Args:
            suppliers: 已经过启发式验证的供应商列表
            product: ProductDTO（需要 main_image_url）
            top_k: 验证前 K 个供应商（控制 API 成本）
            threshold: 低于此分数的供应商被过滤
        """
        raise_if_cancelled(cancel_check, "LLM visual verification")
        amazon_img = getattr(product, 'main_image_url', None)
        if not amazon_img:
            logger.warning("[llm-verifier] Amazon 产品无主图，跳过 LLM 验证")
            return suppliers

        # 取 top K 有图片的供应商
        eligible_ids = {id(supplier) for supplier in eligible_suppliers} if eligible_suppliers is not None else None
        to_verify = [
            supplier for supplier in suppliers
            if supplier.offer_image_url and (eligible_ids is None or id(supplier) in eligible_ids)
        ][:top_k]
        if not to_verify:
            logger.info("[llm-verifier] 无供应商图片，跳过 LLM 验证")
            return suppliers

        import httpx
        client = httpx.Client(timeout=30, follow_redirects=True)

        for sup in to_verify:
            raise_if_cancelled(cancel_check, "LLM visual verification")
            try:
                result = self._compare_images(client, amazon_img, sup.offer_image_url)
                raise_if_cancelled(cancel_check, "LLM visual verification")
                llm_score = result.get("confidence", 0.5)
                is_match = result.get("is_match", True)

                # 混合分数：LLM 权重 60%，启发式 40%
                old_score = sup.match_quality_score or 0.5
                new_score = 0.6 * llm_score + 0.4 * old_score
                sup.match_quality_score = round(new_score, 4)
                sup.match_verification_method = "llm"
                sup.raw_data["visual_match"] = {
                    "score": round(float(llm_score), 4),
                    "source": "llm",
                    "is_match": bool(is_match),
                    "reason": result.get("reason"),
                    "differences": result.get("differences") or [],
                }
                _update_supplier_rank_scores(sup)

                logger.info(
                    f"[llm-verifier] {sup.supplier_name[:20]} | "
                    f"match={is_match} conf={llm_score:.2f} "
                    f"reason={result.get('reason','')[:30]}"
                )
            except CancellationRequested:
                raise
            except Exception as e:
                logger.warning(f"[llm-verifier] {sup.supplier_name[:20]} 验证失败: {e}")

        client.close()

        # 重新排序和过滤
        suppliers.sort(key=_supplier_sort_key, reverse=True)
        ranked = list(suppliers)
        before = len(suppliers)
        suppliers = [s for s in suppliers if (s.match_quality_score or 0) > threshold]
        if len(suppliers) < before:
            logger.info(f"[llm-verifier] 过滤 {before - len(suppliers)} 条不匹配供应商")

        if not suppliers:
            logger.warning("[llm-verifier] 全部被过滤，保留 top 3 兜底")
            suppliers = ranked[:3]

        return suppliers

    def _compare_images(self, client, amazon_url: str, supplier_url: str) -> dict:
        """下载两张图片并调用 LLM 对比。"""
        amazon_b64 = self._download_image(client, amazon_url)
        supplier_b64 = self._download_image(client, supplier_url)

        if not amazon_b64 or not supplier_b64:
            return {"is_match": False, "confidence": 0.3, "reason": "图片下载失败"}

        return self._call_llm(amazon_b64, supplier_b64)

    def _download_image(self, client, url: str) -> Optional[str]:
        """下载图片并转为 base64。"""
        try:
            r = client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                "Referer": "https://www.amazon.com/",
            })
            r.raise_for_status()
            return base64.b64encode(r.content).decode()
        except Exception as e:
            logger.debug(f"[llm-verifier] 图片下载失败 {url[:50]}: {e}")
            return None

    def _call_llm(self, amazon_b64: str, supplier_b64: str) -> dict:
        """调用 LLM 对比两张图片。"""
        import openai
        client = openai.OpenAI(api_key=self._api_key, base_url=self._api_base)

        resp = client.chat.completions.create(
            model=self._model,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "图1（Amazon产品）："},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{amazon_b64}"}},
                    {"type": "text", "text": "\n图2（1688供应商产品）："},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{supplier_b64}"}},
                    {"type": "text", "text": f"\n{self._PROMPT}"},
                ],
            }],
        )

        text = resp.choices[0].message.content
        return self._parse_response(text)

    def _parse_response(self, text: str) -> dict:
        """解析 LLM 返回的 JSON。"""
        s = text.strip()
        if "```" in s:
            m = re.search(r"```(?:json)?\s*([\s\S]+?)```", s)
            if m: s = m.group(1).strip()
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]+\}", s)
            if m:
                try: return json.loads(m.group(0))
                except: pass
        return {"is_match": False, "confidence": 0.3, "reason": "解析失败"}


# ============================================================
# 辅助函数
# ============================================================

def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _material_match(expected: str, actual: str) -> bool:
    return any(a in actual for a in _material_aliases(expected))

def _material_aliases(material: str) -> list[str]:
    m = material.strip().lower()
    _MAP = {
        "不锈钢": ["不锈钢", "stainless", "304", "316"],
        "铝合金": ["铝合金", "铝", "aluminum", "aluminium"],
        "塑料": ["塑料", "plastic", "pp", "abs", "pe", "pvc"],
        "硅胶": ["硅胶", "silicone", "食品级硅胶"],
        "玻璃": ["玻璃", "glass", "钢化玻璃"],
        "棉": ["棉", "cotton", "纯棉", "棉麻"],
        "涤纶": ["涤纶", "polyester", "聚酯"],
        "皮革": ["皮革", "leather", "皮", "pu皮"],
        "竹": ["竹", "bamboo", "竹木"],
        "陶瓷": ["陶瓷", "ceramic", "瓷器"],
        "木": ["木", "wood", "实木", "木质"],
        "铁": ["铁", "iron", "铸铁"],
        "铜": ["铜", "copper", "黄铜"],
    }
    for key, variants in _MAP.items():
        if m in variants or any(v in m for v in variants):
            return variants
    return [m]


def _title_is_relevant(supplier, analysis, keywords: list[str]) -> bool:
    offer_title = supplier.title_cn or supplier.raw_data.get("title_cn", "")
    if not offer_title:
        return False
    if analysis and analysis.category_zh and analysis.category_zh in offer_title:
        return True
    return _keyword_title_score(offer_title, keywords) > 0


def llm_eligible_suppliers(
    suppliers: list[SupplierDTO],
    *,
    min_match_quality: float,
    min_spec_score: float,
) -> list[SupplierDTO]:
    """Return suppliers worth the cost of a visual LLM comparison."""
    eligible: list[SupplierDTO] = []
    for supplier in suppliers:
        spec_match = (supplier.raw_data or {}).get("spec_match") or {}
        if not supplier.offer_image_url:
            continue
        if float(supplier.match_quality_score or 0.0) < min_match_quality:
            continue
        if float(spec_match.get("score") or 0.0) < min_spec_score:
            continue
        if spec_match.get("conflicts"):
            continue
        eligible.append(supplier)
    return eligible


def _keyword_title_score(offer_title: str, keywords: list[str]) -> float:
    if not offer_title or not keywords:
        return 0.0
    best = 0.0
    for kw in keywords:
        kw = (kw or "").strip()
        if not kw:
            continue
        if kw in offer_title:
            best = max(best, 1.0)
            continue
        grams = _bigrams(kw)
        if not grams:
            continue
        hits = sum(1 for gram in grams if gram in offer_title)
        if hits >= 2:
            best = max(best, min(hits / len(grams), 1.0))
    return best


def _update_supplier_rank_scores(supplier: SupplierDTO) -> None:
    quality_score = _supplier_quality_score(supplier)
    business_score = _supplier_business_score(supplier)
    supplier.raw_data["supplier_quality_score"] = quality_score
    supplier.raw_data["supplier_business_score"] = business_score
    supplier.raw_data["supplier_candidate_score"] = _candidate_score(
        match_score=supplier.match_quality_score,
        supplier_quality_score=quality_score,
        business_score=business_score,
    )


def _supplier_sort_key(supplier: SupplierDTO) -> tuple[float, float, float]:
    raw = supplier.raw_data or {}
    return (
        float(raw.get("supplier_candidate_score") or 0.0),
        float(supplier.match_quality_score or 0.0),
        float(raw.get("supplier_quality_score") or 0.0),
    )


def _candidate_score(
    *,
    match_score: float | None,
    supplier_quality_score: float,
    business_score: float,
) -> float:
    match = _clamp(float(match_score or 0.0))
    return round(0.65 * match + 0.25 * supplier_quality_score + 0.10 * business_score, 4)


def _supplier_quality_score(supplier: SupplierDTO) -> float:
    sales_score = _sales_score(supplier.monthly_sales)
    repeat_score = _repeat_score(supplier.repeat_buyer_rate)
    factory_score = 1.0 if supplier.is_factory is True else 0.45 if supplier.is_factory is False else 0.65
    delivery_score = _delivery_score(supplier.delivery_days)
    return round(
        _clamp(0.35 * sales_score + 0.30 * repeat_score + 0.25 * factory_score + 0.10 * delivery_score),
        4,
    )


def _supplier_business_score(supplier: SupplierDTO) -> float:
    moq_score = _moq_score(supplier.moq)
    price_score = _price_score(supplier.base_price_cny)
    return round(_clamp(0.65 * moq_score + 0.35 * price_score), 4)


def _sales_score(value: int | None) -> float:
    if value is None:
        return 0.5
    if value >= 5000:
        return 1.0
    if value >= 1000:
        return 0.85
    if value >= 300:
        return 0.7
    if value >= 50:
        return 0.55
    return 0.35


def _repeat_score(value: float | None) -> float:
    if value is None:
        return 0.5
    value = float(value)
    if value > 1:
        value = value / 100
    return _clamp(value)


def _delivery_score(value: int | None) -> float:
    if value is None:
        return 0.5
    if value <= 7:
        return 1.0
    if value <= 15:
        return 0.85
    if value <= 30:
        return 0.65
    return 0.35


def _moq_score(value: int | None) -> float:
    if value is None:
        return 0.5
    if value <= 50:
        return 1.0
    if value <= 100:
        return 0.85
    if value <= 300:
        return 0.65
    if value <= 500:
        return 0.45
    return 0.25


def _price_score(value: float | None) -> float:
    if value is None:
        return 0.5
    if value <= 20:
        return 1.0
    if value <= 50:
        return 0.8
    if value <= 100:
        return 0.6
    return 0.4


def _bigrams(text: str) -> list[str]:
    text = re.sub(r"[\s,，、/|｜()\[\]（）【】]+", "", text or "")
    if len(text) < 2:
        return []
    return [text[i:i + 2] for i in range(len(text) - 1)]

def _color_match(expected: str, actual: str) -> bool:
    e, a = expected.strip(), actual.strip()
    if e == "多色" or a == "多色": return True
    _MAP = {
        "黑色": ["黑色", "黑", "black"], "白色": ["白色", "白", "white"],
        "银色": ["银色", "银", "silver"], "金色": ["金色", "金", "gold", "香槟金"],
        "红色": ["红色", "红", "red", "酒红"], "蓝色": ["蓝色", "蓝", "blue", "深蓝", "浅蓝"],
        "绿色": ["绿色", "绿", "green"], "灰色": ["灰色", "灰", "grey", "gray"],
        "粉色": ["粉色", "粉", "pink"], "棕色": ["棕色", "棕", "brown", "咖啡色"],
    }
    el, al = e.lower(), a.lower()
    for variants in _MAP.values():
        em = el in variants or any(v in el for v in variants)
        am = al in variants or any(v in al for v in variants)
        if em and am: return True
    return e in a or a in e
