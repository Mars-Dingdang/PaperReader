from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[3] / ".env"),
        case_sensitive=False,
        extra="ignore",
    )

    def model_post_init(self, __context) -> None:
        project_root = Path(__file__).resolve().parents[3]
        if not self.data_dir.is_absolute():
            self.data_dir = (project_root / self.data_dir).resolve()

    app_env: str = Field(default="dev", alias="APP_ENV")

    data_dir: Path = Field(default=Path("../data"), alias="DATA_DIR")
    upload_dir_name: str = Field(default="uploads", alias="UPLOAD_DIR_NAME")
    output_dir_name: str = Field(default="outputs", alias="OUTPUT_DIR_NAME")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    mineru_api_key: str = Field(default="", alias="MINERU_API_KEY")
    mineru_base_url: str = Field(default="https://mineru.net/api/v4", alias="MINERU_BASE_URL")
    mineru_model_version: str = Field(default="vlm", alias="MINERU_MODEL_VERSION")
    mineru_language: str = Field(default="en", alias="MINERU_LANGUAGE")
    mineru_enable_formula: bool = Field(default=True, alias="MINERU_ENABLE_FORMULA")
    mineru_enable_table: bool = Field(default=True, alias="MINERU_ENABLE_TABLE")
    mineru_is_ocr: bool = Field(default=False, alias="MINERU_IS_OCR")
    mineru_poll_interval: float = Field(default=5.0, alias="MINERU_POLL_INTERVAL")
    mineru_timeout: float = Field(default=600.0, alias="MINERU_TIMEOUT")

    latexmk_path: str = Field(default="latexmk", alias="LATEXMK_PATH")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # Vision-model adversarial check (Phase D)
    vision_model: str = Field(default="GLM-4.5V", alias="VISION_MODEL")
    vision_check_enabled: bool = Field(default=True, alias="VISION_CHECK_ENABLED")
    vision_check_mode: str = Field(default="auto", alias="VISION_CHECK_MODE")  # auto | manual
    vision_check_max_pages: int = Field(default=8, alias="VISION_CHECK_MAX_PAGES")

    # TeX project upload limits (Phase B)
    project_max_file_mb: int = Field(default=20, alias="PROJECT_MAX_FILE_MB")
    project_max_total_mb: int = Field(default=200, alias="PROJECT_MAX_TOTAL_MB")

    # Translation concurrency (chunked LLM calls)
    translate_concurrency: int = Field(default=4, alias="TRANSLATE_CONCURRENCY")
    translate_max_retries: int = Field(default=5, alias="TRANSLATE_MAX_RETRIES")
    # Global LLM request rate limit (requests per second). 0 disables limiting.
    # Applied as a shared token bucket across all threads to avoid 429s under
    # high translate concurrency.
    llm_rate_limit_rps: float = Field(default=4.0, alias="LLM_RATE_LIMIT_RPS")
    # Max characters joined per IR batch request. Larger batches amortize RTT
    # but risk hitting per-request token limits; tune per provider.
    translate_batch_max_chars: int = Field(default=6000, alias="TRANSLATE_BATCH_MAX_CHARS")

    cors_origins_raw: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / self.upload_dir_name

    @property
    def output_dir(self) -> Path:
        return self.data_dir / self.output_dir_name


settings = Settings()

settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
