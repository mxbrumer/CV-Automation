"""AJS Detect Language: cheap language pre-check (da / en / other) before any LLM call.

Uses `lingua` when it is installed in the LangFlow image, otherwise a stop-word count that is
reliable for da vs en and for text in other languages (A2: only da and en are supported).
Norwegian is close to Danish and may be reported as `da`; that is accepted.
"""

import re

from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output
from lfx.schema.data import Data

DA_WORDS = frozenset(
    "og i at er det en til på for med som af de den har vi du kan et ikke om vil skal man sig "
    "fra eller også vores dig os være hos ved dit dine jeres jer søger arbejde stillingen "
    "opgaver kompetencer erfaring virksomhed ansøgning ansøg mere hvor bliver blive både have "
    "får giver samt din der denne disse hvis".split()
)
EN_WORDS = frozenset(
    "the and of to in a is for with you we our are will on as be this that or your an have by "
    "from at can us who about team work role experience skills job join looking apply their what "
    "more which not all it has been into also".split()
)
SUPPORTED = ("da", "en")


def heuristic(text: str) -> tuple[str, float]:
    lowered = text.lower()
    words = re.findall(r"[a-zæøåäöüéèß]+", lowered)
    if len(words) < 20:
        return "other", 0.0
    da = sum(w in DA_WORDS for w in words)
    en = sum(w in EN_WORDS for w in words)
    # Danish letters are a strong hint; English text almost never has them.
    da += len(re.findall(r"[æøå]", lowered))
    if max(da, en) / len(words) < 0.12 or da == en:
        return "other", 0.0
    top, rest = max(da, en), min(da, en)
    return ("da" if da > en else "en"), round(top / (top + rest), 3)


def with_lingua(text: str) -> tuple[str, float] | None:
    try:
        from lingua import LanguageDetectorBuilder
    except ImportError:
        return None
    detector = LanguageDetectorBuilder.from_all_languages().build()
    lang = detector.detect_language_of(text)
    if lang is None:
        return "other", 0.0
    confidence = detector.compute_language_confidence(text, lang)
    code = lang.iso_code_639_1.name.lower()
    return (code if code in SUPPORTED else "other"), round(float(confidence), 3)


class AjsDetectLanguage(Component):
    display_name = "AJS Detect Language"
    description = "Detect posting language (da/en/other) with lingua or a stop-word fallback."
    name = "AjsDetectLanguage"
    icon = "languages"

    inputs = [DataInput(name="posting", display_name="Posting", input_types=["Data"])]

    outputs = [
        Output(display_name="Supported", name="supported", method="supported"),
        Output(display_name="Unsupported", name="unsupported", method="unsupported"),
    ]

    def _detect(self) -> dict:
        cached = getattr(self, "_ajs_result", None)
        if cached is not None:
            return cached
        data = dict(self.posting.data)
        if data.get("language") in SUPPORTED:
            lang, confidence, method = data["language"], 1.0, "stored"
        else:
            found = with_lingua(data["posting_text"])
            method = "lingua" if found else "stopwords"
            lang, confidence = found or heuristic(data["posting_text"])
        data.update(language=lang, language_confidence=confidence, language_method=method)
        self._ajs_result = data
        return data

    def supported(self) -> Data:
        data = self._detect()
        if data["language"] not in SUPPORTED:
            self.stop("supported")
            return Data(data=data)
        self.stop("unsupported")
        self.status = f"{data['language']} ({data['language_method']}, {data['language_confidence']})"
        return Data(data=data)

    def unsupported(self) -> Data:
        data = self._detect()
        if data["language"] in SUPPORTED:
            self.stop("unsupported")
            return Data(data=data)
        self.stop("supported")
        return Data(data=data)
