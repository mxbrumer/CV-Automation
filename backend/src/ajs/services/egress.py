"""Runtime egress guard (plan 10): which outbound HTTP the backend and worker may make.

Allowed: LangFlow (fixed host), the Jobindex feeds and posting pages (public web, via the fetcher
and RSS source, minus the denylist) and Phoenix (OpenTelemetry exporter, not an httpx client).
Ollama is the only model endpoint and is called by LangFlow, not from here. Anything addressed to
a hosted-LLM API is refused whatever the purpose.
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


def egress_hook(
    purpose: str, only_hosts: set[str] | None = None
) -> Callable[[httpx.Request], None]:
    """An httpx `request` event hook. `only_hosts` pins the client to those hosts."""

    def check(request: httpx.Request) -> None:
        host = (urlsplit(str(request.url)).hostname or "").lower()
        if any(_on_domain(host, d) for d in MODEL_API_DOMAINS):
            raise EgressBlocked(f"{purpose}: {host} is a hosted-LLM endpoint", request=request)
        if only_hosts is not None and host not in only_hosts:
            raise EgressBlocked(f"{purpose}: {host} is not an allowed host", request=request)

    return check
