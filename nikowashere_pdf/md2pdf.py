#!/usr/bin/env python3
"""Convert a small Markdown document into a clean, printable PDF.

Usage:
    python md2pdf.py
    python md2pdf.py input.md
    python md2pdf.py input.md output.pdf

The default input is NikoWasHere.md next to this script. The default output has
the same filename with a .pdf extension.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

LOGGER = logging.getLogger(__name__)

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
    )
except ImportError as exc:
    raise SystemExit(
        "ReportLab is required. Install it with: uv add reportlab"
    ) from exc


HOLO_BLUE = colors.HexColor("#33B5E5")
BACKGROUND_COLOR = colors.HexColor("#101010")
TEXT_COLOR = colors.HexColor("#F5F5F5")
MUTED_COLOR = colors.HexColor("#BEBEBE")

TOKEN_PATTERN = re.compile(
    r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^]]+\]\(https?://[^)]+\)|https?://[^\s<]+)"
)


def inline_markdown(text: str) -> str:
    """Translate the small inline-Markdown subset supported by this script."""

    output: list[str] = []
    position = 0

    for match in TOKEN_PATTERN.finditer(text):
        output.append(escape(text[position : match.start()]))
        token = match.group(0)

        if token.startswith("`"):
            output.append(f'<font name="Courier">{escape(token[1:-1])}</font>')
        elif token.startswith("**"):
            output.append(f"<b>{escape(token[2:-2])}</b>")
        elif token.startswith("*"):
            output.append(f"<i>{escape(token[1:-1])}</i>")
        elif token.startswith("["):
            label, url = token[1:].split("](", 1)
            url = url[:-1]
            output.append(
                f'<link href="{escape(url)}" color="#33B5E5">{escape(label)}</link>'
            )
        else:
            punctuation = ""
            while token and token[-1] in ".,;:!?":
                punctuation = token[-1] + punctuation
                token = token[:-1]
            output.append(
                f'<link href="{escape(token)}" color="#33B5E5">{escape(token)}</link>'
                + escape(punctuation)
            )

        position = match.end()

    output.append(escape(text[position:]))
    return "".join(output)


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocumentTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=30,
            leading=36,
            alignment=TA_CENTER,
            textColor=HOLO_BLUE,
            spaceAfter=3 * mm,
        ),
        "heading": ParagraphStyle(
            "Heading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=26,
            textColor=HOLO_BLUE,
            spaceBefore=5 * mm,
            spaceAfter=2.5 * mm,
        ),
        "subheading": ParagraphStyle(
            "Subheading",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=22,
            textColor=MUTED_COLOR,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=15,
            leading=22,
            textColor=TEXT_COLOR,
            spaceAfter=4.5 * mm,
        ),
        "bullet": ParagraphStyle(
            "BulletText",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=15,
            leading=22,
            textColor=TEXT_COLOR,
        ),
    }


def markdown_story(markdown: str) -> list[object]:
    styles = make_styles()
    story: list[object] = []
    paragraph_lines: list[str] = []
    bullet_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines)
            story.append(Paragraph(inline_markdown(text), styles["body"]))
            paragraph_lines.clear()

    def flush_bullets() -> None:
        if bullet_lines:
            items = [
                ListItem(Paragraph(inline_markdown(line), styles["bullet"]))
                for line in bullet_lines
            ]
            story.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    leftIndent=7 * mm,
                    bulletFontName="Helvetica",
                    bulletFontSize=9,
                    spaceAfter=4.5 * mm,
                )
            )
            bullet_lines.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()

        if not line.strip():
            flush_paragraph()
            flush_bullets()
            continue

        if line.strip() == "---":
            flush_paragraph()
            flush_bullets()
            story.append(PageBreak())
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_bullets()
            level = len(heading.group(1))
            style = "title" if level == 1 else "heading" if level == 2 else "subheading"
            story.append(Paragraph(inline_markdown(heading.group(2)), styles[style]))
            if level == 1:
                story.append(
                    HRFlowable(
                        width="100%",
                        thickness=1.5,
                        color=HOLO_BLUE,
                        spaceBefore=0,
                        spaceAfter=9 * mm,
                    )
                )
            continue

        bullet = re.match(r"^\s*[-*+]\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            bullet_lines.append(bullet.group(1))
            continue

        flush_bullets()
        paragraph_lines.append(line)

    flush_paragraph()
    flush_bullets()
    return story


def draw_page(canvas, document) -> None:
    canvas.saveState()
    canvas.setFillColor(BACKGROUND_COLOR)
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(MUTED_COLOR)
    canvas.drawCentredString(A4[0] / 2, 12 * mm, str(document.page))
    canvas.restoreState()


def convert(input_path: Path, output_path: Path) -> None:
    if not input_path.is_file():
        raise SystemExit(f"Markdown file not found: {input_path}")

    markdown = input_path.read_text(encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=19 * mm,
        leftMargin=19 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title=input_path.stem,
        author="Niko",
        subject="Niko Was Here",
    )
    document.build(
        markdown_story(markdown),
        onFirstPage=draw_page,
        onLaterPages=draw_page,
    )


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    default_input = script_dir / "NikoWasHere.md"

    parser = argparse.ArgumentParser(description="Convert Markdown to PDF.")
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=default_input,
        help="input Markdown file (default: NikoWasHere.md beside this script)",
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="output PDF file (default: input filename with .pdf extension)",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args()
    input_path = args.input.resolve()
    output_path = (args.output or input_path.with_suffix(".pdf")).resolve()
    convert(input_path, output_path)
    manual_path = Path(__file__).resolve().parent.parent / "server" / "assets" / "manual.pdf"
    manual_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path != manual_path:
        shutil.copy2(output_path, manual_path)
    LOGGER.info("Created: %s", output_path)
    LOGGER.info("Copied: %s", manual_path)


if __name__ == "__main__":
    main()
