"""Runtime egress guard (plans 10, 15): which outbound HTTP the backend may make.

The backend never reaches the public web (D4: posting text is pasted, never fetched). Allowed:
LangFlow (flow runs), Ollama (chat editing, plan 12) and Phoenix (OTLP traces from the
OpenTelemetry exporter, not an httpx client). Every httpx client is pinned to its one host with
`only_hosts`, and anything addressed to a hosted-LLM API is refused whatever the purpose.
`scripts/governance_check.py` (rule `egress`) and a backend test check that every client is pinned.
"""

from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

MODEL_API_DOMAINS = (
    "openai.com",
    "anthropic.com",
    "claude.ai",
    "cohere.com",
    "cohere.ai",
    "mistral.ai",
    "groq.com",
    "openrouter.ai",
    "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com",
    "x.ai",
    "deepseek.com",
    "perplexity.ai",
    "huggingface.co",
    "azure.com",
    "amazonaws.com",
)


class EgressBlocked(httpx.RequestError):
    """Raised before any bytes leave the process."""


def _on_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def egress_hook(purpose: str, only_hosts: set[str]) -> Callable[[httpx.Request], None]:
    """An httpx `request` event hook that pins the client to `only_hosts`."""

    def check(request: httpx.Request) -> None:
        host = (urlsplit(str(request.url)).hostname or "").lower()
        if any(_on_domain(host, d) for d in MODEL_API_DOMAINS):
            raise EgressBlocked(f"{purpose}: {host} is a hosted-LLM endpoint", request=request)
        if host not in only_hosts:
            raise EgressBlocked(f"{purpose}: {host} is not an allowed host", request=request)

    return check
