"""4-1. 약관·상품설명서 PDF 를 페이지별 텍스트로 추출한다.

실행: python scripts/01_extract.py   (persona-pilot 폴더에서)
결과: data/extracted/terms.json, data/extracted/guide.json
      [{"page": 1, "text": "..."}, ...]
글자가 거의 없는 페이지(스캔 이미지로 의심)는 목록으로 알려준다.
"""

import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "extracted"
MIN_CHARS = 30  # 이보다 글자가 적으면 추출 실패로 본다

FILES = {"terms": "terms.pdf", "guide": "guide.pdf"}


def extract(pdf_path: Path) -> tuple[list[dict], list[int]]:
    pages, empty = [], []
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text", sort=True).strip()
            pages.append({"page": i, "text": text})
            if len(text) < MIN_CHARS:
                empty.append(i)
    return pages, empty


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for key, name in FILES.items():
        pages, empty = extract(RAW / name)
        (OUT / f"{key}.json").write_text(
            json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        chars = sum(len(p["text"]) for p in pages)
        print(f"{name}: {len(pages)}쪽, {chars:,}자")
        if empty:
            print(f"  ! 글자가 거의 없는 페이지 (붙여넣기 필요할 수 있음): {empty}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
