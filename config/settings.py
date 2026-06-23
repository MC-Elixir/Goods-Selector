"""
全局配置：从 .env 加载 + 默认值
其他模块统一通过 `from config.settings import settings` 取值
"""
from pathlib import Path
from typing import Literal

from pydantic import Field
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

    # PPIO 长上下文文本模型（用于大文档分析、批量总结等，文本专用）
    # 2026-06 新增：GLM-5.2 (1M 上下文，¥80/¥280，性价比优于 v4-pro)
    ppio_text_model: str = "zai-org/glm-5.2"

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

    # ---------- 卖家精灵 ----------
    mjjl_api_key: str = ""
    mjjl_api_base: str = "https://api.sellersprite.com/v1"

    # ---------- 行为开关 ----------
    enable_api_cache: bool = True
    enable_llm_verification: bool = False  # 启用 LLM 视觉验证（对比 Amazon 和 1688 图片）
    cache_ttl_seconds: int = 86400
    log_level: str = "INFO"

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


settings = Settings()
