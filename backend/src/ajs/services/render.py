"""Markdown -> PDF: markdown-it-py to HTML, a small A4 stylesheet, WeasyPrint."""

from functools import cache
from html import escape
from importlib import resources

from markdown_it import MarkdownIt

FALLBACK_CSS = "cv"


@cache
def _stylesheet(name: str) -> str:
    return resources.files("ajs.templates.pdf").joinpath(f"{name}.css").read_text(encoding="utf-8")


def markdown_to_html(markdown: str, css: str | None = None) -> str:
    body = MarkdownIt("commonmark", {"html": False}).render(markdown)
    style = css if css is not None else _stylesheet(FALLBACK_CSS)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{escape(style, quote=False)}</style></head><body>{body}</body></html>"
    )


def markdown_to_pdf(markdown: str, css: str | None = None) -> bytes:
    """Render to a PDF. `css` is a full stylesheet; the default is the CV style."""
    from weasyprint import HTML  # imported late: needs the Pango system libraries

    pdf: bytes = HTML(string=markdown_to_html(markdown, css)).write_pdf()
    return pdf


def stylesheet_for(kind: str) -> str:
    return _stylesheet("letter" if kind == "cover_letter" else "cv")
