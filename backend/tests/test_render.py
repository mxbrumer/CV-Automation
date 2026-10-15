"""PDF rendering (plan 09). Skipped when WeasyPrint's system libraries (Pango) are missing."""

from collections.abc import Iterator
from typing import Any

import pytest

from ajs.services import render

try:
    from weasyprint import HTML
except OSError:  # pragma: no cover - host without Pango
    pytest.skip("WeasyPrint system libraries not available", allow_module_level=True)


def laid_out(markdown: str, kind: str) -> Any:
    return HTML(string=render.markdown_to_html(markdown, render.stylesheet_for(kind))).render()


def texts(box: Any) -> Iterator[str]:
    if hasattr(box, "text"):
        yield box.text
    for child in getattr(box, "children", ()):
        yield from texts(child)


def test_html_does_not_pass_raw_html_through() -> None:
    assert "<script>" not in render.markdown_to_html("# Hi\n\n<script>x()</script>")


def test_renders_danish_characters() -> None:
    markdown = "# Søren Åbo\n\nBlæsende ærlige øl på Ærø."
    pdf = render.markdown_to_pdf(markdown, render.stylesheet_for("cv"))
    assert pdf.startswith(b"%PDF")
    text = " ".join(texts(laid_out(markdown, "cv").pages[0]._page_box))  # noqa: SLF001
    assert "Søren Åbo" in text and "Blæsende ærlige øl på Ærø." in text


def test_letter_of_350_words_fits_one_page() -> None:
    paragraph = " ".join(["word"] * 70)
    assert len(laid_out("\n\n".join([paragraph] * 5), "cover_letter").pages) == 1


def test_long_cv_flows_onto_a_second_page() -> None:
    bullets = "\n".join(f"- bullet number {i} with some text" for i in range(120))
    assert len(laid_out("## Experience\n\n" + bullets, "cv").pages) >= 2
