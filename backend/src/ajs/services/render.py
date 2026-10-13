"""Markdown -> PDF. Interface only; WeasyPrint rendering arrives in plan 09."""


def markdown_to_pdf(markdown: str, css: str | None = None) -> bytes:
    raise NotImplementedError("PDF rendering is implemented in plan 09")
