"""AJS Evidence Selector: picks the CV bullets that best support each must_have (no LLM).

Bullets are embedded with bge-m3 (cached by content hash) and ranked by cosine similarity to each
requirement. Every bullet keeps its role heading (`### Employer - Title`) and dates, so a writer
can cite it without guessing. The agent model is warmed up first, because Ollama evicts a
resident bge-m3 when Gemma loads second (plan 04).
"""

import asyncio
import hashlib
import math
import re
import sys
import types

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, IntInput, Output, StrInput
from lfx.schema.data import Data

_cache_module = sys.modules.setdefault("ajs_evidence_cache", types.ModuleType("ajs_evidence_cache"))
CACHE: dict[str, list[float]] = _cache_module.__dict__.setdefault("cache", {})
NOT_SCORED = re.compile(r"\b(danish|dansk|english|engelsk|fluent|spoken|work permit|relocat\w*|on-?site)\b", re.I)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def parse_bullets(cv_markdown: str) -> list[dict]:
    """Every `- ` bullet with the nearest `###` role heading and the italic date line under it."""
    bullets: list[dict] = []
    section = role = dates = ""
    for line in cv_markdown.splitlines():
        if line.startswith("## "):
            section, role, dates = line[3:].strip(), "", ""
        elif line.startswith("### "):
            role, dates = line[4:].strip(), ""
        elif re.fullmatch(r"\*[^*]+\*", line.strip()) and role and not dates:
            dates = line.strip().strip("*")
        elif line.lstrip().startswith("- ") and section.lower() != "overview":
            text = line.lstrip()[2:].strip()
            if text:
                bullets.append({"section": section, "role": role, "dates": dates, "text": text})
    return bullets


def pick(similarities: dict[str, list[float]], count: int, per_requirement: int) -> list[int]:
    """Indexes of the chosen bullets: the top `per_requirement` for each requirement, no duplicates."""
    chosen: list[int] = []
    for sims in similarities.values():
        ranked = sorted(range(count), key=lambda i: sims[i], reverse=True)
        for index in ranked[:per_requirement]:
            if index not in chosen:
                chosen.append(index)
    return chosen


class AjsEvidenceSelector(Component):
    display_name = "AJS Evidence Selector"
    description = "Choose the CV bullets that best match each must_have (bge-m3 cosine, no LLM)."
    name = "AjsEvidenceSelector"
    icon = "search-check"

    inputs = [
        DataInput(name="posting", display_name="Posting", input_types=["Data"]),
        IntInput(name="per_requirement", display_name="Bullets per requirement", value=3, advanced=True),
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
    ]

    outputs = [Output(display_name="Posting", name="posting_out", method="select")]

    async def _embed(self, client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
        body = {"model": self.embed_model, "input": texts, "keep_alive": self.keep_alive}
        for attempt in range(3):
            response = await client.post(f"{self.ollama_base_url.rstrip('/')}/api/embed", json=body)
            if response.status_code == 200:
                return response.json()["embeddings"]
            if attempt == 2:
                response.raise_for_status()
            await asyncio.sleep(2)
        return []

    async def select(self) -> Data:
        data = dict(self.posting.data)
        brief = data["job_brief"]
        bullets = parse_bullets(data["cv_markdown"])
        if not bullets:
            msg = "cv.md has no bullet items to use as evidence"
            raise ValueError(msg)
        requirements = [r for r in (brief.get("must_have") or []) if not NOT_SCORED.search(r)]
        requirements += [r for r in (brief.get("nice_to_have") or []) if not NOT_SCORED.search(r)][:3]
        if not requirements:
            requirements = [brief.get("title") or data["title"]]

        base = self.ollama_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            warm = await client.post(
                f"{base}/api/generate",
                json={"model": self.warm_model, "prompt": "", "stream": False, "keep_alive": self.keep_alive},
            )
            warm.raise_for_status()
            keys = [hashlib.sha256(f"{self.embed_model}\n{b['text']}".encode()).hexdigest() for b in bullets]
            missing = list({k: b["text"] for k, b in zip(keys, bullets, strict=True) if k not in CACHE}.items())
            if missing:
                vectors = await self._embed(client, [text for _, text in missing])
                for (key, _), vector in zip(missing, vectors, strict=True):
                    CACHE[key] = vector
            req_vectors = await self._embed(client, requirements)

        similarities = {
            req: [cosine(vector, CACHE[key]) for key in keys]
            for req, vector in zip(requirements, req_vectors, strict=True)
        }
        chosen = pick(similarities, len(bullets), max(1, int(self.per_requirement)))
        evidence = []
        for index in chosen:
            best = max(requirements, key=lambda r: similarities[r][index])
            evidence.append({**bullets[index], "for": best, "similarity": round(similarities[best][index], 4)})
        evidence.sort(key=lambda e: e["similarity"], reverse=True)  # the guard trims from the end
        data["evidence"] = evidence
        self.status = f"{len(evidence)} evidence bullets for {len(requirements)} requirements"
        return Data(data=data)
