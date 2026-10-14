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
    # Flow id or endpoint name; imported flows keep the endpoint name (plan 08).
    langflow_analysis_flow_id: str = "analyze_and_match"
    langflow_generation_flow_id: str = ""
    ollama_base_url: str = "http://host.docker.internal:11434"

    # Hybrid match score (D8): weights and threshold.
    match_threshold: int = 55
    match_weight_embedding: float = 0.4
    match_weight_rubric: float = 0.6

    # Duplicate detection (A5).
    dedup_similarity: float = 0.85
    dedup_window_days: int = 120

    # Feed intake (plan 07, D3/D4).
    jobindex_feeds: str = ""  # comma-separated Jobindex RSS URLs, one per saved search
    feed_poll_interval_min: int = 1440  # never below the feed ttl (1440)
    fetch_user_agent: str = "ai-job-search/0.1 (personal, local; contact via GitHub mxbrumer)"
    fetch_denylist: str = "linkedin.com"  # comma-separated domains that are never fetched
    fetch_min_snippet_words: int = 150
    fetch_min_text_words: int = 80

    @property
    def feed_urls(self) -> list[str]:
        return [u.strip() for u in self.jobindex_feeds.split(",") if u.strip()]

    @property
    def denylist(self) -> list[str]:
        return [d.strip().lower() for d in self.fetch_denylist.split(",") if d.strip()]

    @property
    def applications_root(self) -> Path:
        return self.data_root / "applications"

    @property
    def profile_root(self) -> Path:
        return self.data_root / "profile"


@lru_cache
def get_settings() -> Settings:
    return Settings()
