from dataclasses import dataclass
from io import BytesIO
import re


@dataclass
class Section:
    heading: str
    text: str
    page: int | None = None


def parse_file(name: str, payload: bytes) -> list[Section]:
    suffix = name.rsplit(".", 1)[-1].lower()
    if suffix in {"md", "markdown", "txt"}:
        return split_markdown(payload.decode("utf-8-sig"))
    if suffix == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(payload))
        sections = []
        for page_number, page in enumerate(reader.pages, 1):
            for section in split_markdown(page.extract_text() or ""):
                section.page = page_number
                sections.append(section)
        if not sections:
            raise ValueError("PDF 无可提取文本；扫描件需先 OCR，本项目不内置 OCR")
        return sections
    if suffix == "docx":
        from docx import Document

        doc = Document(BytesIO(payload))
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        lines = []
        for block in doc.iter_inner_content():
            if isinstance(block, Paragraph):
                prefix = "## " if block.style.name.startswith("Heading") else ""
                lines.append(prefix + block.text)
            elif isinstance(block, Table):
                lines.append(
                    "\n"
                    + "\n".join(
                        "| " + " | ".join(cell.text for cell in row.cells) + " |"
                        for row in block.rows
                    )
                    + "\n"
                )
        return split_markdown("\n\n".join(lines))
    raise ValueError("支持 .pdf、.md、.txt、.docx；不支持旧版 .doc")


def split_markdown(text: str, limit=700) -> list[Section]:
    """Pack structural blocks. Never split inside fenced code or a table.

    An oversized atomic block stays oversized; API upload limits bound memory.
    PDF layout reconstruction is intentionally not claimed.
    """
    heading, buffer, atomic, fenced = "正文", [], [], False
    output = []

    def flush():
        nonlocal buffer
        if buffer:
            output.append(Section(heading, "\n\n".join(buffer).strip()))
            buffer = []

    def append(block):
        if not block.strip():
            return
        if sum(len(x) for x in buffer) + len(block) > limit:
            flush()
        buffer.append(block)

    for line in text.splitlines() + [""]:
        if line.lstrip().startswith("```"):
            atomic.append(line)
            fenced = not fenced
            if not fenced:
                append("\n".join(atomic))
                atomic = []
            continue
        if fenced:
            atomic.append(line)
            continue
        if atomic and not line.lstrip().startswith("|"):
            append("\n".join(atomic))
            atomic = []
        if line.lstrip().startswith("|"):
            atomic.append(line)
            continue
        match = re.match(r"^#{1,6}\s+(.+)$", line)
        if match:
            flush()
            heading = match.group(1)
        elif line.strip():
            append(line)
    if atomic:
        append("\n".join(atomic))
    flush()
    return output
