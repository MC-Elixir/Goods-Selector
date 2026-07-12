"""
全局配置：从 .env 加载 + 默认值
其他模块统一通过 `from config.settings import settings` 取值
"""
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 数据库 ----------
    database_url: str = Field(
        default=f"sqlite:///{DATA_DIR}/amazon_selector.db"
    )

    # ---------- 视觉分析后端（二选一，PPIO 优先）----------
    # PPIO（派噢）— OpenAI 兼容接口，国内访问快，支持 Qwen-VL 等模型
    ppio_api_key: str = ""
    ppio_api_base: str = "https://api.ppio.com/openai"
    ppio_model: str = "qwen/qwen3.5-plus"  # PPIO 上的视觉模型（需支持 image 输入）

    # PPIO OpenAI-compatible text model used for run summaries and base LLM tasks.
    ppio_text_model: str = "minimax/minimax-m3"
    llm_request_timeout_seconds: float = 30.0

    # Anthropic — Claude Vision（PPIO 未配置时的备用）
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    @property
    def vision_provider(self) -> str:
        """自动选择视觉分析后端：PPIO 优先，其次 Anthropic。"""
        if self.ppio_api_key:
            return "ppio"
        if self.anthropic_api_key:
            return "anthropic"
        return "none"

    # ---------- Amazon ----------
    keepa_api_key: str = ""
    rainforest_api_key: str = ""
    amazon_marketplace: Literal["US", "UK", "DE", "JP"] = "US"

    # ---------- 1688 拍立淘 ----------
    alibaba_app_key: str = ""
    alibaba_app_secret: str = ""
    alibaba_access_token: str = ""
    alibaba_api_gateway: str = "https://gw.open.1688.com/openapi/"
    alibaba_supplier_search_namespace: str = Field(
        default="com.alibaba.pifatuan",
        validation_alias=AliasChoices(
            "ALIBABA_SUPPLIER_SEARCH_NAMESPACE",
            "ALIBABA_PIFATUAN_NAMESPACE",
        ),
    )
    alibaba_supplier_search_method: str = Field(
        default="alibaba.pifatuan.product.list",
        validation_alias=AliasChoices(
            "ALIBABA_SUPPLIER_SEARCH_METHOD",
            "ALIBABA_PIFATUAN_METHOD",
        ),
    )
    alibaba_supplier_search_keyword_param: str = Field(
        default="keywords",
        validation_alias=AliasChoices(
            "ALIBABA_SUPPLIER_SEARCH_KEYWORD_PARAM",
            "ALIBABA_PIFATUAN_KEYWORD_PARAM",
        ),
    )
    alibaba_supplier_search_candidates: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ALIBABA_SUPPLIER_SEARCH_CANDIDATES",
            "ALIBABA_PIFATUAN_CANDIDATES",
        ),
    )

    # ---------- 卖家精灵 ----------
    mjjl_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "MJJL_API_KEY",
            "SELLERSPRITE_API_KEY",
            "SELLER_SPRITE_API_KEY",
            "SELLERSPRITE_KEY",
        ),
    )
    mjjl_api_base: str = Field(
        default="https://api.sellersprite.com/v1",
        validation_alias=AliasChoices("MJJL_API_BASE", "SELLERSPRITE_API_BASE"),
    )
    mjjl_max_products_per_run: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "MJJL_MAX_PRODUCTS_PER_RUN",
            "SELLERSPRITE_MAX_PRODUCTS_PER_RUN",
        ),
    )
    sellersprite_browser_enabled: bool = False
    sellersprite_browser_locator_profile_path: str = ""
    sellersprite_browser_download_dir: str = ""
    sellersprite_browser_host_download_dir: str = ""
    sellersprite_browser_page_timeout_seconds: int = 45
    sellersprite_browser_export_timeout_seconds: int = 120
    sellersprite_browser_min_interval_seconds: int = 5
    sellersprite_browser_max_retries: int = 1

    # ---------- 行为开关 ----------
    enable_api_cache: bool = True
    enable_llm_verification: bool = False  # 启用 LLM 视觉验证（对比 Amazon 和 1688 图片）
    llm_verification_top_k: int = 2
    llm_verification_min_match_quality: float = 0.65
    llm_verification_min_spec_score: float = 0.50
    # 1688 Scrapling 匹配器（patchright HTTP 路径）。被 1688 TMD 反爬拦截、0 结果，
    # 默认禁用、直接降级 Playwright；待该路径修好后置 True 启用。
    enable_scrapling_matcher: bool = False
    alibaba_real_result_cache_ttl_seconds: int = 604800
    alibaba_detail_enrich_limit: int = 2
    alibaba_detail_cache_ttl_seconds: int = 604800
    alibaba_block_cooldown_seconds: int = 900
    alibaba_allow_mock_suppliers: bool = False  # formal runs: mock off by default; smoke-run --allow-mock opts in
    pipeline_crawl_timeout_seconds: float = 300.0
    pipeline_match_timeout_seconds: float = 900.0
    pipeline_profit_timeout_seconds: float = 300.0
    pipeline_market_timeout_seconds: float = 300.0
    pipeline_score_timeout_seconds: float = 300.0
    pipeline_export_timeout_seconds: float = 120.0
    browser_agent_allowed_domains: str = "amazon.com,www.amazon.com,1688.com,detail.1688.com,s.1688.com,127.0.0.1,localhost"
    cache_ttl_seconds: int = 86400
    log_level: str = "INFO"
    log_dir_override: str = Field(
        default="",
        validation_alias=AliasChoices("LOG_DIR"),
    )

    # ---------- 路径 ----------
    @property
    def cache_dir(self) -> Path:
        p = DATA_DIR / "cache"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def image_dir(self) -> Path:
        p = DATA_DIR / "images"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def export_dir(self) -> Path:
        p = DATA_DIR / "exports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def sellersprite_import_dir(self) -> Path:
        p = DATA_DIR / "imports" / "sellersprite"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def log_dir(self) -> Path:
        p = Path(self.log_dir_override) if self.log_dir_override else DATA_DIR / "logs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_runtime_dirs(self) -> dict[str, Path]:
        dirs = {
            "cache": self.cache_dir,
            "exports": self.export_dir,
            "images": self.image_dir,
            "logs": self.log_dir,
        }
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return dirs


settings = Settings()
