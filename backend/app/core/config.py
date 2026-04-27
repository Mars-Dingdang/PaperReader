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
