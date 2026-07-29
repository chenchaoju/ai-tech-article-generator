from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "文章工坊"
    app_env: str = "development"
    app_base_path: str = ""

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "123456"
    postgres_db: str = "ai_tech_articles"
    database_url: str

    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-4.6"
    glm_title_model: str = "glm-4-flash-250414"
    glm_expert_model: str = "glm-4.6"
    glm_writer_model: str = "glm-4.6"
    glm_reviewer_model: str = "glm-4-flash-250414"
    glm_director_model: str = "glm-4.6"
    glm_temperature: float = 0.5
    glm_max_tokens: int = 50000
    glm_enable_thinking: bool = False
    glm_timeout_seconds: int = 180
    glm_search_engine: str = "search_std"
    glm_search_count: int = 10
    glm_proxy_url: str = ""
    glm_token_budget: int = 0
    model_profiles_json: str = ""
    active_model_profile_id: str = ""

    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    wechat_author: str = ""
    wechat_api_base_url: str = "https://api.weixin.qq.com"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
