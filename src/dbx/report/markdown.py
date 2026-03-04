"""Markdown report builder and common formatting utilities.

All section markdown is assembled here by the ReportBuilder class.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def md_table(rows: list[dict], columns: list[str]) -> str:
    """Render a list of dicts as a GitHub-flavored Markdown table.

    Only columns listed in *columns* are included. Missing keys render as
    an empty cell. All values are stringified and stripped of inner pipes.
    """
    if not rows:
        return "*No data.*"

    def cell(val: Any) -> str:
        return str(val).replace("|", "\\|").replace("\n", " ") if val is not None else ""

    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body_lines = [
        "| " + " | ".join(cell(row.get(col, "")) for col in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body_lines])


def err_block(title: str, detail: str) -> str:
    """Render a standardised error callout in Markdown."""
    return (
        f"> **⚠ {title}**\n"
        f">\n"
        f"> ```\n"
        f"> {detail}\n"
        f"> ```"
    )


def section(title: str, level: int, body: str) -> str:
    """Wrap *body* with an ATX heading at the given *level* (2–4)."""
    hashes = "#" * level
    return f"{hashes} {title}\n\n{body}\n"


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


class ReportBuilder:
    """Accumulate report sections and produce a final Markdown document."""

    def __init__(self, title: str = "Inherited Postgres Report") -> None:
        self._title = title
        self._sections: list[tuple[str, str]] = []  # (heading, body)

    def add(self, heading: str, body: str, level: int = 2) -> "ReportBuilder":
        """Append a section. *body* may itself contain sub-headings."""
        self._sections.append((heading, body, level))  # type: ignore[assignment]
        return self

    def build(self) -> str:
        parts = [f"# {self._title}\n"]
        # TOC
        toc_lines: list[str] = []
        for heading, _, level in self._sections:  # type: ignore[assignment]
            slug = heading.lower().replace(" ", "-").replace("/", "").replace("(", "").replace(")", "")
            indent = "  " * (level - 2)
            toc_lines.append(f"{indent}- [{heading}](#{slug})")
        parts.append("## Table of Contents\n\n" + "\n".join(toc_lines) + "\n")

        for heading, body, level in self._sections:  # type: ignore[assignment]
            hashes = "#" * level
            parts.append(f"{hashes} {heading}\n\n{body}\n")

        return "\n".join(parts)
