"""AJS Budget Guard: keeps every writer call inside `num_ctx` (architecture 5, plan 04 step 6).

Token counts are estimated at 1 token per 3 characters (a safe over-estimate for English and
Danish text with Gemma's tokenizer). Budgets at num_ctx 32768: instructions 2000, job brief 2000,
CV evidence 8000, template 3000, output 4000. Trim order: evidence bullets from the lowest
similarity up, then HTML comments (the examples and rules) in the templates, then the brief's
keywords and nice_to_have. If the worst-case call still does not fit, the guard raises instead
of letting Ollama truncate the prompt silently.
"""

import json
import re

from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, IntInput, Output
from lfx.schema.data import Data

CHARS_PER_TOKEN = 3.0
LETTER_TOKENS = 1200  # the letter is at most 450 words (AJS Doc Writer), about 3000 characters
HTML_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def evidence_text(evidence: list[dict]) -> str:
    return "\n".join(f"- [{e['role']} | {e['dates']}] {e['text']}" for e in evidence)


def trim(data: dict, limits: dict[str, int]) -> tuple[dict, list[str]]:
    """Return a trimmed copy of the posting data and a log of what was cut."""
    data = json.loads(json.dumps(data))
    log: list[str] = []
    evidence = data.get("evidence", [])
    while evidence and estimate_tokens(evidence_text(evidence)) > limits["evidence"]:
        evidence.pop()  # sorted best-first, so the weakest goes first
        log.append("evidence bullet dropped")
    data["evidence"] = evidence
    templates = data["templates"]
    for key, text in templates.items():
        if estimate_tokens(text) > limits["template"]:
            templates[key] = HTML_COMMENT.sub("", text)
            log.append(f"{key} template comments removed")
    brief = data["job_brief"]
    for field in ("keywords", "nice_to_have"):
        if estimate_tokens(json.dumps(brief)) > limits["brief"] and brief.get(field):
            brief[field] = []
            log.append(f"brief {field} dropped")
    # CV, brief, evidence and the larger template all go into one call; check the worst call.
    # The email call carries the finished letter instead of the CV, so count the larger of the two.
    worst = (
        limits["instructions"]
        + max(estimate_tokens(data["cv_markdown"]), LETTER_TOKENS)
        + estimate_tokens(json.dumps(brief))
        + estimate_tokens(evidence_text(evidence))
        + max(estimate_tokens(t) for t in templates.values())
    )
    if worst + limits["output"] > limits["num_ctx"]:
        msg = f"prompt of ~{worst} tokens plus {limits['output']} output does not fit num_ctx {limits['num_ctx']}"
        raise ValueError(msg)
    data["budget"] = {"prompt_tokens_worst_case": worst, "trimmed": log}
    return data, log


class AjsBudgetGuard(Component):
    display_name = "AJS Budget Guard"
    description = "Trim evidence, template text and brief so every writer call fits num_ctx."
    name = "AjsBudgetGuard"
    icon = "scissors"

    inputs = [
        DataInput(name="posting", display_name="Posting", input_types=["Data"]),
        IntInput(name="context_tokens", display_name="Context tokens (num_ctx)", info="Must equal the Modelfile's num_ctx.", value=32768),
        IntInput(name="evidence_tokens", display_name="Evidence budget", value=8000, advanced=True),
        IntInput(name="template_tokens", display_name="Template budget", value=3000, advanced=True),
        IntInput(name="brief_tokens", display_name="Brief budget", value=2000, advanced=True),
        IntInput(name="instruction_tokens", display_name="Instruction budget", value=2000, advanced=True),
        IntInput(name="output_tokens", display_name="Output budget", value=4000, advanced=True),
    ]

    outputs = [Output(display_name="Posting", name="posting_out", method="guard")]

    def guard(self) -> Data:
        limits = {
            "num_ctx": int(self.context_tokens),
            "evidence": int(self.evidence_tokens),
            "template": int(self.template_tokens),
            "brief": int(self.brief_tokens),
            "instructions": int(self.instruction_tokens),
            "output": int(self.output_tokens),
        }
        data, log = trim(dict(self.posting.data), limits)
        self.status = f"~{data['budget']['prompt_tokens_worst_case']} tokens worst case, {len(log)} trims"
        return Data(data=data)
