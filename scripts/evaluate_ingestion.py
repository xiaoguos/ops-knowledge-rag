"""Generate synthetic image-only PDF fixtures and measure real OCR/review gates.

Requires .[ocr] and a Chinese TrueType font supplied with --font.
These fixtures test behavior, not an independent document-quality benchmark.
"""
import argparse
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path

from app.ingestion import process_document, reviewed_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", required=True)
    parser.add_argument("--output", default="docs/complex-ingestion-evaluation.json")
    args = parser.parse_args()
    from PIL import Image, ImageDraw, ImageFont
    from pypdf import PdfReader, PdfWriter

    root = Path(__file__).resolve().parents[1]
    destination = root / "data/fixtures/complex"
    destination.mkdir(parents=True, exist_ok=True)
    title = ImageFont.truetype(args.font, 42)
    body = ImageFont.truetype(args.font, 30)

    def canvas(name):
        image = Image.new("RGB", (1400, 1400), "white")
        draw = ImageDraw.Draw(image)
        draw.text((70, 60), name, fill="black", font=title)
        draw.text((70, 125), "合成文档，仅用于解析回归，不含真实业务数据。", fill="black", font=body)
        return image, draw

    two, draw = canvas("双栏排障说明")
    left = ["支付超时处理", "等待上限3000毫秒。", "先查询订单状态。", "PENDING不得重复扣款。", "重试复用原幂等键。"]
    right = ["退款超时处理", "等待上限5000毫秒。", "先核对退款申请。", "处理中不得重复退款。", "重试复用refund_id。"]
    for x, lines in [(70, left), (740, right)]:
        for i, line in enumerate(lines):
            draw.text((x, 260 + i * 110), line, fill="black", font=body)
    merged, draw = canvas("合并表头配置表")
    draw.rectangle((70, 240, 1300, 760), outline="black", width=3)
    draw.line((70, 340, 1300, 340), fill="black", width=3)
    draw.text((100, 265), "生产环境参数（合并表头）", fill="black", font=body)
    table = [("项目", "单位", "配置值"), ("请求等待", "毫秒", "3000"), ("连接池上限", "个", "30")]
    for i, row in enumerate(table):
        y = 340 + i * 140
        draw.line((70, y + 140, 1300, y + 140), fill="black", width=3)
        for x, word in zip([100, 630, 980], row):
            draw.text((x, y + 40), word, fill="black", font=body)
    for x in [590, 940]:
        draw.line((x, 340, x, 760), fill="black", width=3)
    multi, draw = canvas("故障说明与空白附页")
    for i, line in enumerate(["P1故障5分钟内响应。", "恢复后24小时内完成复盘。", "附页为空白，不得静默丢失。"]):
        draw.text((70, 270 + i * 90), line, fill="black", font=body)
    fixtures = [("two-column", two, ["3000", "5000", "PENDING", "refund_id"], 1),
                ("merged-header", merged, ["3000", "30", "毫秒", "连接池"], 1),
                ("blank-appendix", multi, ["P1", "5", "24"], 2)]
    rows = []
    for name, image, fields, expected_pages in fixtures:
        stream = BytesIO()
        image.save(stream, "PDF", resolution=120)
        payload = stream.getvalue()
        if expected_pages == 2:
            writer = PdfWriter()
            writer.append(PdfReader(BytesIO(payload)))
            writer.add_blank_page(width=840, height=840)
            stream = BytesIO()
            writer.write(stream)
            payload = stream.getvalue()
        path = destination / (name + ".pdf")
        path.write_bytes(payload)
        reader = PdfReader(BytesIO(payload))
        assert all(not page.extract_text().strip() for page in reader.pages), "Must be image-only"
        # Explicitly keep this OCR test offline even if a vision endpoint exists.
        def no_vision(_):
            raise RuntimeError("Vision disabled for OCR-only benchmark")
        report = process_document(path.name, payload, vision=no_vision)
        extracted = "\n".join(p["text"] for p in report["pages"])
        blank_rejected = None
        if expected_pages == 2:
            edits = [{"page": p["page"], "text": p["text"], "blank": False} for p in report["pages"]]
            try:
                reviewed_report(report, edits)
                blank_rejected = False
            except ValueError:
                blank_rejected = True
        row = {"fixture": name, "expected_pages": expected_pages, "actual_pages": len(report["pages"]),
               "field_presence": {word: word in extracted for word in fields},
               "review_required": report["review_required"], "unconfirmed_blank_rejected": blank_rejected,
               "report": report}
        rows.append(row)
        print(json.dumps({k: row[k] for k in row if k != "report"}, ensure_ascii=True), flush=True)
    result = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "scope": "3 synthetic image-only PDFs; real CPU OCR; field presence is not semantic/table accuracy",
              "independent_human_quality_labels": None, "details": rows}
    (root / args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
