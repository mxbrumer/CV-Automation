from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch"

    # Blob storage (D6). In the container DATA_ROOT is /data; host_data_root is the Windows
    # path of the same folder, used only to show paths in the UI.
    data_root: Path = Path("C:/dev/JobSearchData")
    host_data_root: str | None = None

    # Shared secret between UI, LangFlow and this API (A1). Empty means every request is refused.
    backend_api_key: str = ""

    langflow_url: str = "http://127.0.0.1:7860"
    langflow_api_key: str = ""
    langflow_analysis_flow_id: str = ""
    langflow_generation_flow_id: str = ""
    ollama_base_url: str = "http://host.docker.internal:11434"

    # Hybrid match score (D8): weights and threshold.
    match_threshold: int = 55
    match_weight_embedding: float = 0.4
    match_weight_rubric: float = 0.6

    # Duplicate detection (A5).
    dedup_similarity: float = 0.85
    dedup_window_days: int = 120

    @property
    def applications_root(self) -> Path:
        return self.data_root / "applications"

    @property
    def profile_root(self) -> Path:
        return self.data_root / "profile"


@lru_cache
def get_settings() -> Settings:
    return Settings()
