from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

T = TypeVar("T")


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    STALE = "stale"
    MISSING = "missing"
    MOCK = "mock"
    CONFLICTING = "conflicting"


class FieldEvidence(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")
    value: T | None = None
    status: EvidenceStatus
    source_provider: str
    source_type: str | None = None
    source_ref: str | None = None
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    extraction_method: str | None = None
    schema_version: str = "1.0"
    conflict_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.status in {EvidenceStatus.MISSING, EvidenceStatus.MOCK} and self.value is not None:
            raise ValueError(f"{self.status.value} evidence cannot carry a value")
        if self.status in {EvidenceStatus.EXTRACTED, EvidenceStatus.VERIFIED}:
            if not self.source_type or not self.source_ref or self.observed_at is None:
                raise ValueError("extracted or verified evidence requires source metadata")
        for field_name in ("observed_at", "expires_at"):
            timestamp = getattr(self, field_name)
            if timestamp is not None and timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        return self

    def effective_status(self, now: datetime | None = None) -> EvidenceStatus:
        current = now or datetime.now(timezone.utc)
        if self.expires_at is not None and self.expires_at <= current:
            return EvidenceStatus.STALE
        return self.status


class AmazonProductUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asin: str
    original_title_en: str
    translated_title_cn: str | None = None
    generic_product_name: str
    supply_chain_name_cn: str
    category: str | None = None
    subcategory: str | None = None
    function: list[str] = Field(default_factory=list)
    material: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    package_quantity: int | None = Field(default=None, ge=1)
    dimensions_visible: list[str] = Field(default_factory=list)
    target_user: list[str] = Field(default_factory=list)
    use_case: list[str] = Field(default_factory=list)
    replaceable_part_or_full_product: Literal["replacement", "consumable", "full_product", "unknown"]
    distinguishing_features: list[str] = Field(default_factory=list)
    likely_supplier_keywords_cn: list[str] = Field(default_factory=list)
    excluded_brand_tokens: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    model_provider: str
    model_name: str
    prompt_version: str


class VisionMatchResult(BaseModel):
    """Strict, provider-attributed evidence for an Amazon/1688 visual match."""

    model_config = ConfigDict(extra="forbid", strict=True)
    same_product_type: bool
    same_core_function: bool
    same_accessory_full_product_relation: bool | None
    same_structure: bool | None
    same_material: bool | None
    same_package_quantity: bool | None
    major_visual_differences: list[str]
    potential_mismatch: list[str]
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(min_length=1)
    provider: str
    model: str
    prompt_version: str

    @computed_field
    @property
    def is_match(self) -> bool:
        """Hard semantic contradictions always win over confidence."""
        return (
            self.same_product_type
            and self.same_core_function
            and self.same_accessory_full_product_relation is not False
            and self.same_package_quantity is not False
        )

    @computed_field
    @property
    def classification_confidence(self) -> float:
        """Task 9 compatibility: confidence describes classification, not similarity."""
        return self.confidence


QueryType = Literal[
    "generic_name", "supply_chain_name", "function", "material", "structure",
    "use_case", "specification", "package_quantity", "replacement_consumable",
    "debranded_description", "factory_synonym", "alibaba_category",
]


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str
    asin: str
    query_type: QueryType
    text: str = Field(min_length=2, max_length=120)
    reason: str
    excluded_brand_tokens: list[str] = Field(default_factory=list)
    source_evidence_refs: list[str] = Field(default_factory=list)
    retry_of: str | None = None


class MatchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amazon_ref: str
    supplier_ref: str
    category_match: float | None = Field(default=None, ge=0, le=1)
    function_match: float | None = Field(default=None, ge=0, le=1)
    material_match: float | None = Field(default=None, ge=0, le=1)
    shape_match: float | None = Field(default=None, ge=0, le=1)
    dimension_match: float | None = Field(default=None, ge=0, le=1)
    weight_match: float | None = Field(default=None, ge=0, le=1)
    package_quantity_match: float | None = Field(default=None, ge=0, le=1)
    color_variant_match: float | None = Field(default=None, ge=0, le=1)
    accessory_vs_full_product_match: float | None = Field(default=None, ge=0, le=1)
    target_user_match: float | None = Field(default=None, ge=0, le=1)
    use_case_match: float | None = Field(default=None, ge=0, le=1)
    customization_feasibility: float | None = Field(default=None, ge=0, le=1)
    packaging_feasibility: float | None = Field(default=None, ge=0, le=1)
    image_similarity: float | None = Field(default=None, ge=0, le=1)
    title_semantic_similarity: float | None = Field(default=None, ge=0, le=1)
    specification_similarity: float | None = Field(default=None, ge=0, le=1)
    brand_dependency_risk: float | None = Field(default=None, ge=0, le=1)
    patent_risk: float | None = Field(default=None, ge=0, le=1)
    compliance_risk: float | None = Field(default=None, ge=0, le=1)
    visual_is_match: bool | None = None
    visual_confidence: float | None = Field(default=None, ge=0, le=1)
    overall_confidence: float = Field(ge=0, le=1)
    mismatch_reasons: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    passed_reasons: list[str] = Field(default_factory=list)
    decision: Literal["keep", "reject", "retry", "manual_review"]

    @model_validator(mode="after")
    def validate_visual_decision(self):
        if self.visual_is_match is False and self.decision != "reject":
            raise ValueError("negative visual classification requires reject decision")
        return self


class RecommendationStatus(str, Enum):
    RECOMMEND = "recommend"
    WATCHLIST = "watchlist"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    REJECT = "reject"
    INSUFFICIENT_DATA = "insufficient_data"


class RecommendationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asin: str
    supplier_offer_id: str | None = None
    status: RecommendationStatus
    discovery_reason: str
    amazon_completeness: float = Field(ge=0, le=1)
    demand_evidence_refs: list[str] = Field(default_factory=list)
    competition_evidence_refs: list[str] = Field(default_factory=list)
    supplier_match_ref: str | None = None
    confirmed_specs: list[str] = Field(default_factory=list)
    unconfirmed_specs: list[str] = Field(default_factory=list)
    purchase_cost_ref: str | None = None
    logistics_basis: list[str] = Field(default_factory=list)
    profit_basis: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    recommendation_reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    manual_verification_tasks: list[str] = Field(default_factory=list)
