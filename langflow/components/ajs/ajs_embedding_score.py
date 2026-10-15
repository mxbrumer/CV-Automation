"""AJS Embedding Score: bge-m3 cosine similarity of the job brief against each CV section.

score = mean of the top-3 cosine similarities x 100 (clipped to 0-100). CV section embeddings
are cached by content hash for the lifetime of the LangFlow process. The agent model is warmed
up first, because Ollama evicts a resident bge-m3 when Gemma loads second (plan 04).
"""

import asyncio
import hashlib
import math
import sys
import types

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, IntInput, Output, SecretStrInput, StrInput
from lfx.schema.data import Data

# Components are exec'd from source on every build, so a module-level dict would not survive.
_cache_module = sys.modules.setdefault("ajs_embedding_cache", types.ModuleType("ajs_embedding_cache"))
CACHE: dict[str, list[float]] = _cache_module.__dict__.setdefault("cache", {})


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def brief_text(brief: dict) -> str:
    parts = [brief.get("title") or "", "Requirements: " + "; ".join(brief.get("must_have") or [])]
    if brief.get("nice_to_have"):
        parts.append("Nice to have: " + "; ".join(brief["nice_to_have"]))
    if brief.get("keywords"):
        parts.append("Keywords: " + ", ".join(brief["keywords"]))
    return "\n".join(p for p in parts if p)


class AjsEmbeddingScore(Component):
    display_name = "AJS Embedding Score"
    description = "bge-m3 similarity between the job brief and the CV sections (mean of top 3, 0-100)."
    name = "AjsEmbeddingScore"
    icon = "ruler"

    inputs = [
        DataInput(name="posting", display_name="Posting", input_types=["Data"]),
        IntInput(name="top_k", display_name="Top-k sections", value=3, advanced=True),
        StrInput(
            name="ollama_base_url",
            display_name="Ollama base URL",
            info="Global variable OLLAMA_BASE_URL.",
            value="OLLAMA_BASE_URL",
            load_from_db=True,
        ),
        StrInput(
            name="embed_model",
            display_name="Embedding model",
            info="Global variable EMBED_MODEL.",
            value="EMBED_MODEL",
            load_from_db=True,
        ),
        StrInput(
            name="warm_model",
            display_name="Model to warm up first",
            info="Global variable LLM_AGENT_MODEL.",
            value="LLM_AGENT_MODEL",
            load_from_db=True,
            advanced=True,
        ),
        StrInput(
            name="keep_alive",
            display_name="Keep alive",
            info="Global variable LLM_KEEP_ALIVE.",
            value="LLM_KEEP_ALIVE",
            load_from_db=True,
            advanced=True,
        ),
        StrInput(
            name="backend_url",
            display_name="Backend URL",
            info="Global variable BACKEND_URL (FastAPI base including /api/v1).",
            value="http://backend:8000/api/v1",
        ),
        SecretStrInput(
            name="backend_api_key",
            display_name="Backend API key",
            info="Global variable BACKEND_API_KEY.",
            value="BACKEND_API_KEY",
            load_from_db=True,
        ),
    ]

    outputs = [Output(display_name="Posting", name="posting_out", method="score")]

    async def _embed(self, client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
        url = f"{self.ollama_base_url.rstrip('/')}/api/embed"
        body = {"model": self.embed_model, "input": texts, "keep_alive": self.keep_alive}
        for attempt in range(3):  # a fresh runner can fail CUDA init when VRAM is tight
            response = await client.post(url, json=body)
            if response.status_code == 200:
                return response.json()["embeddings"]
            if attempt == 2:
                response.raise_for_status()
            await asyncio.sleep(2)
        return []

    async def score(self) -> Data:
        data = dict(self.posting.data)
        base = self.ollama_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            # Load the agent model first so bge-m3 is not evicted by a later Gemma load.
            warm = await client.post(
                f"{base}/api/generate",
                json={"model": self.warm_model, "prompt": "", "stream": False, "keep_alive": self.keep_alive},
            )
            warm.raise_for_status()

            async with httpx.AsyncClient(headers={"X-API-Key": self.backend_api_key}, timeout=30) as backend:
                response = await backend.get(f"{self.backend_url.rstrip('/')}/tools/profile/cv-sections")
                response.raise_for_status()
            sections = response.json()
            if not sections:
                msg = "cv.md has no sections"
                raise ValueError(msg)

            keys = {
                s["id"]: hashlib.sha256(f"{self.embed_model}\n{s['markdown']}".encode()).hexdigest() for s in sections
            }
            missing = [s for s in sections if keys[s["id"]] not in CACHE]
            if missing:
                vectors = await self._embed(client, [s["markdown"] for s in missing])
                for section, vector in zip(missing, vectors, strict=True):
                    CACHE[keys[section["id"]]] = vector
            brief_vector = (await self._embed(client, [brief_text(data["job_brief"])]))[0]

        sims = {s["id"]: cosine(brief_vector, CACHE[keys[s["id"]]]) for s in sections}
        top = sorted(sims.values(), reverse=True)[: max(1, int(self.top_k))]
        value = round(max(0.0, min(100.0, 100 * sum(top) / len(top))), 2)
        data["embedding_score"] = value
        data["section_similarities"] = {k: round(v, 4) for k, v in sims.items()}
        self.status = (
            f"embedding score {value} ({len(missing)} sections embedded, {len(sections) - len(missing)} cached)"
        )
        return Data(data=data)
