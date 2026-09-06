"""
全局配置：从 .env 加载 + 默认值
其他模块统一通过 `from config.settings import settings` 取值
"""
import os
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("AMAZON_SELECTOR_DATA_DIR") or PROJECT_ROOT / "data")
CONFIG_DIR = PROJECT_ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("AMAZON_SELECTOR_ENV_FILE") or PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 数据库 ----------
    database_url: str = Field(
        default=f"sqlite:///{DATA_DIR}/amazon_selector.db"
    )

    # ---------- 视觉/文本模型后端 ----------
    # 阿里云百炼按量付费（OpenAI 兼容）
    aliyun_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ALIYUN_API_KEY", "DASHSCOPE_API_KEY"),
    )
    aliyun_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    aliyun_vision_model: str = "qwen3-vl-plus"
    aliyun_text_model: str = "qwen-plus"

    # 阿里云 Token Plan。Key、Base URL 必须成对使用，不能和按量付费混用。
    aliyun_token_plan_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ALIYUN_TOKEN_PLAN_API_KEY",
            "DASHSCOPE_TOKEN_PLAN_API_KEY",
            "TOKEN_PLAN_API_KEY",
        ),
    )
    aliyun_token_plan_api_base: str = (
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    aliyun_token_plan_vision_model: str = "qwen3-vl-plus"
    aliyun_token_plan_text_model: str = "qwen-plus"

    # auto 优先 Token Plan，其次百炼按量付费、PPIO、Anthropic。
    model_api_provider: Literal[
        "auto", "aliyun_token_plan", "aliyun", "ppio", "anthropic"
    ] = "auto"

    # PPIO（旧配置继续兼容）— OpenAI 兼容接口
    ppio_api_key: str = ""
    ppio_api_base: str = "https://api.ppio.com/openai"
    ppio_model: str = "qwen/qwen3.5-plus"  # PPIO 上的视觉模型（需支持 image 输入）

    # PPIO OpenAI-compatible text model used for run summaries and base LLM tasks.
    ppio_text_model: str = "minimax/minimax-m3"
    llm_request_timeout_seconds: float = 30.0

    # Anthropic — Claude Vision（OpenAI 兼容供应商未配置时的备用）
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    @property
    def openai_compatible_provider(self) -> str:
        requested = self.model_api_provider
        if requested != "auto":
            return requested if requested != "anthropic" else "none"
        if self.aliyun_token_plan_api_key:
            return "aliyun_token_plan"
        if self.aliyun_api_key:
            return "aliyun"
        if self.ppio_api_key:
            return "ppio"
        return "none"

    @property
    def openai_compatible_api_key(self) -> str:
        return {
            "aliyun_token_plan": self.aliyun_token_plan_api_key,
            "aliyun": self.aliyun_api_key,
            "ppio": self.ppio_api_key,
        }.get(self.openai_compatible_provider, "")

    @property
    def openai_compatible_api_base(self) -> str:
        return {
            "aliyun_token_plan": self.aliyun_token_plan_api_base,
            "aliyun": self.aliyun_api_base,
            "ppio": self.ppio_api_base,
        }.get(self.openai_compatible_provider, "")

    @property
    def openai_compatible_vision_model(self) -> str:
        return {
            "aliyun_token_plan": self.aliyun_token_plan_vision_model,
            "aliyun": self.aliyun_vision_model,
            "ppio": self.ppio_model,
        }.get(self.openai_compatible_provider, "")

    @property
    def openai_compatible_text_model(self) -> str:
        return {
            "aliyun_token_plan": self.aliyun_token_plan_text_model,
            "aliyun": self.aliyun_text_model,
            "ppio": self.ppio_text_model,
        }.get(self.openai_compatible_provider, "")

    @property
    def vision_provider(self) -> str:
        """Resolve an OpenAI-compatible backend first, then Anthropic."""
        provider = self.openai_compatible_provider
        if provider != "none" and self.openai_compatible_api_key:
            return provider
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
    # "rest" 走按接口计费的 REST 网关；"mcp" 走打包计费的官方 MCP 网关。
    # 两者字段契约相同，切换不影响 Stage 4 的 DTO。
    mjjl_transport: str = Field(
        default="rest",
        validation_alias=AliasChoices("MJJL_TRANSPORT", "SELLERSPRITE_TRANSPORT"),
    )
    mjjl_mcp_url: str = Field(
        default="https://mcp.sellersprite.com/mcp",
        validation_alias=AliasChoices("MJJL_MCP_URL", "SELLERSPRITE_MCP_URL"),
    )
    mjjl_mcp_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=300.0,
        validation_alias=AliasChoices("MJJL_MCP_TIMEOUT_SECONDS", "SELLERSPRITE_MCP_TIMEOUT_SECONDS"),
    )
    mjjl_max_products_per_run: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "MJJL_MAX_PRODUCTS_PER_RUN",
            "SELLERSPRITE_MAX_PRODUCTS_PER_RUN",
        ),
    )
    # The local browser capability is on by default. Actual exports remain
    # blocked until a reviewed locator profile, writable download directory,
    # and reachable user-authorized Chrome session are all present.
    sellersprite_browser_enabled: bool = True
    sellersprite_browser_locator_profile_path: str = ""
    sellersprite_browser_download_dir: str = ""
    sellersprite_browser_host_download_dir: str = ""
    sellersprite_browser_page_timeout_seconds: int = Field(default=45, ge=1, le=120)
    sellersprite_browser_export_timeout_seconds: int = Field(default=120, ge=1, le=300)
    sellersprite_browser_min_interval_seconds: int = Field(default=5, ge=1, le=60)
    sellersprite_browser_max_retries: int = Field(default=1, ge=0, le=1)

    # Chrome DevTools connection. Declaring these fields makes pydantic-settings
    # load them from the project .env for host-side CLI runs as well as Docker.
    bu_cdp_http: str = ""
    bu_cdp_ws: str = ""

    # ---------- 行为开关 ----------
    enable_api_cache: bool = True
    enable_llm_verification: bool = False  # 启用 LLM 视觉验证（对比 Amazon 和 1688 图片）
    llm_verification_top_k: int = 2
    llm_verification_min_match_quality: float = 0.65
    llm_verification_min_spec_score: float = 0.50
    target_category_llm_top_k: int = Field(default=5, ge=0, le=20)
    target_category_detail_enrich_limit: int = Field(default=10, ge=0, le=50)
    target_category_exhaustive_queries: bool = True
    # 1688 Scrapling 匹配器（patchright HTTP 路径）。被 1688 TMD 反爬拦截、0 结果，
    # 默认禁用、直接降级 Playwright；待该路径修好后置 True 启用。
    enable_scrapling_matcher: bool = False
    # 1688 拍立淘图搜（imageAddress 路径不稳定）。暂时禁用，全部走关键词搜索；
    # 需要恢复时置 True。
    enable_image_search: bool = False
    alibaba_real_result_cache_ttl_seconds: int = 604800
    alibaba_detail_enrich_limit: int = 2
    alibaba_detail_cache_ttl_seconds: int = 604800
    alibaba_block_cooldown_seconds: int = 900
    # Browser/plugin sourcing is the production path.  Keep the legacy Open
    # Platform clients available for explicit diagnostics only.
    enable_alibaba_open_api_matcher: bool = False
    # 卖家精灵插件「1688找货」匹配源。默认开启，实际运行需要 locator profile
    # 中配置 sourcing_1688_* 定位符且 Chrome 9222 可达。
    enable_sellersprite_1688_sourcing: bool = True
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
