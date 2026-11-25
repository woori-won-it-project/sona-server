"""금감원 분쟁조정 목록 페이지만 훑어서 data/raw/list_{case|standard|decision}.json 으로 저장한다.

상세페이지·첨부는 열지 않는다. 샘플 선정과 전체 수집의 목록 단계에서 쓴다.

사용 (레포 루트에서):
    python scripts/collector/list_scan.py --kind all        # case + standard
    python scripts/collector/list_scan.py --kind decision   # 분쟁조정결정례 (보험 탭만)
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.fss.or.kr"
USER_AGENT = "Mozilla/5.0 (compatible; sona-collector/0.1; +https://github.com/woori-won-it-project/sona-server)"
REQUEST_INTERVAL_SEC = 1.1
MAX_RETRY = 3

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"

SOURCES = {
    "case": {
        "doc_kind": "CASE",
        "list_path": "/fss/job/fncCnflCase/list.do",
        "menu_no": "201195",
        "key_param": "caseSlno",
    },
    "standard": {
        "doc_kind": "STANDARD",
        "list_path": "/fss/job/fncCnflPrcdnt/list.do",
        "menu_no": "201194",
        "key_param": "prcdntSlno",
    },
    # 분쟁조정결정례: 게시판형(bbs). 상세 키는 nttId, 권역 탭 cl1Cd (A=은행ㆍ중소서민 B=보험 C=금융투자)
    "decision": {
        "doc_kind": "DECISION",
        "list_path": "/fss/bbs/B0000390/list.do",
        "menu_no": "201193",
        "key_param": "nttId",
        "list_params": {"cl1Cd": "B"},
    },
}

_last_request_at = 0.0


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def wait_interval() -> None:
    """모든 요청 사이 REQUEST_INTERVAL_SEC 이상 대기."""
    global _last_request_at
    wait = REQUEST_INTERVAL_SEC - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def fetch(session: requests.Session, url: str, params: dict) -> str:
    """요청 간격 유지 + 최대 3회 재시도."""
    last_error = None
    for attempt in range(1, MAX_RETRY + 1):
        wait_interval()
        try:
            res = session.get(url, params=params, timeout=30)
            res.raise_for_status()
            res.encoding = "utf-8"
            return res.text
        except requests.RequestException as e:
            last_error = e
            print(f"  retry {attempt}/{MAX_RETRY}: {e}", file=sys.stderr)
    raise RuntimeError(f"request failed after {MAX_RETRY} attempts: {url} {params}") from last_error


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def parse_attachments(cell) -> list[dict]:
    files = []
    for a in cell.select("ul.list-board-attach-file li a"):
        icon = a.select_one("i[class*='ico-small-']")
        icon_type = None
        if icon:
            m = re.search(r"ico-small-(\w+)", " ".join(icon.get("class", [])))
            icon_type = m.group(1) if m else None
        name = a.select_one("span.name")
        href = urljoin(BASE_URL, a.get("href", ""))
        qs = parse_qs(urlparse(href).query)
        files.append({
            "name": clean(name.get_text()) if name else None,
            "url": href,
            "atch_file_id": qs.get("atchFileId", [None])[0],
            "file_sn": qs.get("fileSn", [None])[0],
            "icon": icon_type,
        })
    return files


def parse_page(html: str, src: dict) -> tuple[list[dict], int | None, int | None]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.list-data")
    if table is None:
        raise RuntimeError("list table (table.list-data) not found")

    headers = [clean(th.get_text()) for th in table.select("thead th")]
    items = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != len(headers):
            continue  # '게시물이 없습니다' 등
        cell = dict(zip(headers, tds))
        link = cell["제목"].find("a")
        href = urljoin(BASE_URL + src["list_path"], link.get("href", ""))
        key = parse_qs(urlparse(href).query).get(src["key_param"], [None])[0]

        item = {
            "list_no": int(clean(cell["번호"].get_text())),
            "source_key": key,
            "title": clean(link.get_text()),
            "category": clean(cell["권역"].get_text()),
            "type": clean(cell["유형"].get_text()) or None,
            "registered_at": clean(cell["등록일"].get_text()),
            "views": int(clean(cell["조회수"].get_text()) or 0),
            "source_url": f"{BASE_URL}{src['list_path'].replace('list.do', 'view.do')}"
                          f"?{src['key_param']}={key}&menuNo={src['menu_no']}",
        }
        if src["doc_kind"] == "CASE":
            item["attachments_detail"] = parse_attachments(cell["상세내용"])
            item["attachments_cardnews"] = parse_attachments(cell["카드뉴스"])
        elif src["doc_kind"] == "DECISION":
            item["department"] = clean(cell["담당부서"].get_text()) or None
            item["attachments"] = parse_attachments(cell["첨부파일"])
        else:
            item["summary"] = clean(cell["요지"].get_text()) or None
            item["attachments"] = parse_attachments(cell["첨부"])
        items.append(item)

    text = clean(soup.get_text(" "))
    total = re.search(r"전체\s*([\d,]+)\s*건", text)
    pages = re.search(r"페이지\s*\d+\s*/\s*(\d+)", text)
    return (items,
            int(total.group(1).replace(",", "")) if total else None,
            int(pages.group(1)) if pages else None)


def scan(kind: str, session: requests.Session) -> Path:
    src = SOURCES[kind]
    url = BASE_URL + src["list_path"]
    items, total, last_page = [], None, None
    page = 1
    while True:
        html = fetch(session, url, {"menuNo": src["menu_no"], "pageIndex": page, **src.get("list_params", {})})
        rows, page_total, page_last = parse_page(html, src)
        total = total or page_total
        last_page = last_page or page_last
        print(f"[{kind}] page {page}/{last_page}: {len(rows)} rows")
        if not rows:
            break
        items.extend(rows)
        if last_page and page >= last_page:
            break
        page += 1

    keys = [i["source_key"] for i in items]
    result = {
        "doc_kind": src["doc_kind"],
        "list_url": f"{url}?menuNo={src['menu_no']}" + "".join(f"&{k}={v}" for k, v in src.get("list_params", {}).items()),
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site_total": total,
        "page_count": last_page,
        "item_count": len(items),
        "duplicate_keys": sorted({k for k in keys if keys.count(k) > 1}),
        "items": items,
    }
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"list_{kind}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{kind}] saved {len(items)} items (site total {total}) -> {out}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="금감원 분쟁조정 목록 스캔 (상세·첨부 미요청)")
    parser.add_argument("--kind", choices=["case", "standard", "decision", "all"], default="all")
    args = parser.parse_args()

    session = new_session()
    kinds =["case", "standard"] if args.kind == "all" else [args.kind]
    for kind in kinds:
        scan(kind, session)


if __name__ == "__main__":
    main()
