"""금감원 분쟁조정사례(CASE) / 분쟁해결기준(STANDARD) / 분쟁조정결정례(DECISION, 보험) 수집기.

원본(상세 HTML, 모든 첨부)은 data/raw/ 에 빠짐없이 저장하고, 파싱은 최소한만 해서 dispute_case 에 upsert 한다.
수집 이력은 DB 가 아니라 리포트 JSON 으로 남긴다: --report 경로, 없으면 (dry-run 이 아닐 때)
data/raw/_report/collect_{kind}_{UTC 시각}.json (시작·종료 시각, 상태, 건수, 오류, 항목별 요약).

사용 (레포 루트에서):
    python scripts/collector/collector.py --kind case --limit 3
    python scripts/collector/collector.py --kind case --keys 128,1,118
    python scripts/collector/collector.py --kind standard --dry-run
    python scripts/collector/collector.py --kind case --reparse      # 네트워크 없이 data/raw 로 재파싱
    python scripts/collector/collector.py --kind decision --keys 64799 --dry-run   # 결정례 (파싱은 decision.py)

옵션:
    --keys       caseSlno / prcdntSlno 목록 (쉼표 구분). 목록 순서 대신 이 건들만 처리
    --limit N    앞에서 N건만 처리 (시험용)
    --dry-run    DB 저장 없이 결과 출력 (--report 파일로 요약 저장 가능)
    --skip-existing  원본 파일이 이미 있으면 다시 받지 않음
    --reparse    네트워크 요청 없이 data/raw/ 의 HTML·첨부로 재파싱 (DB 갱신)

설정 (환경변수 또는 루트 .env):
    POSTGRES_HOST/PORT/DB/USER/PASSWORD
    HWP5TXT_PATH  hwp5txt 실행 파일 경로 (기본: 이 venv 의 hwp5txt)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, unquote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import decision
import list_scan
from list_scan import BASE_URL, RAW_DIR, ROOT, SOURCES, clean, fetch

CASE_SECTIONS = {
    "complaint": "민원내용",
    "dispute_issue": "쟁점",
    "decision_reason": "처리결과",
    "consumer_warning": "소비자유의사항",
}
FORM_MARKER = "[양식]"
EMPTY_MARK = re.compile(r"^[\s\-–—ㅡ]*$")          # 구간 내용이 '-' 같은 빈 표시뿐인 경우
INQUIRY_LINE = re.compile(r"^\s*※\s*문의")         # STANDARD HTML 의 '※ 문의 : 부서 전화' 줄
TABLE_PLACEHOLDER = "<표>"                          # hwp5txt 가 표 자리에 남기는 표시
TEXT_COLUMNS = ["title", "summary", "complaint", "dispute_issue", "decision_reason", "consumer_warning",
                "raw_text", "category", "product_type"]
PERSONAL_INFO_KEYS = ("작성자", "담당자", "문의 이메일")
BLOCK_TAGS = ["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"]


# ---------------------------------------------------------------- 설정

def load_env() -> dict:
    """루트 .env 를 읽고 OS 환경변수로 덮어쓴다."""
    values = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if m:
                values[m.group(1)] = m.group(2).strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith(("POSTGRES_", "HWP5TXT"))})
    return values


def hwp5txt_path(env: dict) -> str:
    if env.get("HWP5TXT_PATH"):
        return env["HWP5TXT_PATH"]
    bin_dir = Path(sys.executable).parent
    for name in ("hwp5txt.exe", "hwp5txt"):
        if (bin_dir / name).exists():
            return str(bin_dir / name)
    found = shutil.which("hwp5txt")
    if not found:
        raise RuntimeError("hwp5txt not found. pip install pyhwp 또는 HWP5TXT_PATH 설정")
    return found


# ---------------------------------------------------------------- 텍스트

def block_text(node) -> str:
    """블록 태그 단위로 줄을 나눠 텍스트화 (span 사이에서 줄이 끊기지 않도록)."""
    node = BeautifulSoup(str(node), "html.parser")
    for tag in node.find_all(["script", "style"]):
        tag.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    for tag in node.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    lines = [clean(line) for line in node.get_text().split("\n")]
    return "\n".join(line for line in lines if line)


def split_sections(text: str) -> list[tuple[str, str]]:
    """▣ 기준으로 (제목, 내용) 목록. 제목은 ▣ 바로 뒤 첫 줄."""
    sections = []
    for chunk in text.split("▣")[1:]:
        chunk = chunk.strip()
        if not chunk:
            continue
        heading, _, body = chunk.partition("\n")
        sections.append((heading.strip(), body.strip()))
    return sections


def match_heading(raw_heading: str, body: str, names: dict) -> tuple[str | None, str]:
    """공백을 무시하고 제목을 비교한다. 제목 뒤에 내용이 같은 줄에 붙은 경우 그 부분을 내용 앞에 되돌린다."""
    for col, name in names.items():
        pattern = r"\s*".join(map(re.escape, name))
        m = re.match(rf"^\s*{pattern}\s*[:：]?\s*", raw_heading)
        if m:
            rest = raw_heading[m.end():].strip()
            return col, "\n".join(x for x in (rest, body) if x)
    return None, body


# ---------------------------------------------------------------- 상세 파싱

def parse_detail(html: str, src: dict) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    view = soup.select_one(".krds-bd-view")
    if view is None:
        raise RuntimeError("detail view (.krds-bd-view) not found")

    info = {}
    for wrap in view.select("dl.bd-info .info-wrap"):
        dt, dd = wrap.find("dt"), wrap.find("dd")
        if dt and dd:
            info[clean(dt.get_text())] = clean(dd.get_text())

    # 칸마다 링크 마크업이 다르다 (상세내용: a.btn-attach-download + '다운로드' 버튼, 카드뉴스: 클래스 없는 a)
    # → 클래스와 무관하게 fileDown 링크를 모두 잡고 (atchFileId, fileSn) 으로 중복 제거
    boxes = []
    seen = set()
    for box in view.select("dl.attach-file-box"):
        label = clean(box.find("dt").get_text()) if box.find("dt") else None
        for a in box.select("a[href*='fileDown.do']"):
            href = urljoin(BASE_URL, a.get("href", ""))
            qs = parse_qs(urlparse(href).query)
            file_key = (qs.get("atchFileId", [None])[0], qs.get("fileSn", [None])[0])
            shown = clean(a.get_text())
            if file_key in seen or shown in ("", "다운로드"):
                continue
            seen.add(file_key)
            # CASE/STANDARD: '이름 [82KB]', DECISION: '이름 (파일크기: 82KB)'
            m = (re.match(r"^(.*?)\s*\[([\d.,]+\s*[KMG]?B)\]$", shown)
                 or re.match(r"^(.*?)\s*\(파일크기:\s*([\d.,]+\s*[KMG]?B)\)$", shown))
            boxes.append({
                "box": label,
                "display_name": m.group(1) if m else shown,
                "shown_size": m.group(2) if m else None,
                "url": href,
                "atch_file_id": qs.get("atchFileId", [None])[0],
                "file_sn": qs.get("fileSn", [None])[0],
            })

    adm = {}
    for dl in soup.select(".adm-info dl"):
        dt, dd = dl.find("dt"), dl.find("dd")
        if dt and dd:
            adm[clean(dt.get_text())] = clean(dd.get_text())

    body_node = view.select_one("div.n-dbdata")
    body = block_text(body_node) if body_node else ""
    subject = view.select_one("h3.subject")
    return {
        "title": clean(subject.get_text()) if subject else None,
        "info": info,
        "attachments": boxes,
        "admin": adm,
        "body_text": body,
    }


# ---------------------------------------------------------------- 첨부

def filename_from_disposition(header: str | None) -> str | None:
    if not header:
        return None
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", header)
    if m:
        return unquote(m.group(1).strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', header)
    return unquote_plus(m.group(1)) if m else None


def download(session: requests.Session, url: str) -> tuple[bytes, str | None, str | None]:
    last_error = None
    for attempt in range(1, list_scan.MAX_RETRY + 1):
        list_scan.wait_interval()
        try:
            res = session.get(url, timeout=60)
            res.raise_for_status()
            return (res.content,
                    filename_from_disposition(res.headers.get("Content-Disposition")),
                    res.headers.get("Content-Type"))
        except requests.RequestException as e:
            last_error = e
            print(f"  retry {attempt}/{list_scan.MAX_RETRY}: {e}", file=sys.stderr)
    raise RuntimeError(f"download failed: {url}") from last_error


def ext_of(name: str | None) -> str:
    suffix = Path(name).suffix.lower().lstrip(".") if name else ""
    return suffix or "bin"


def normalize_hwp_text(text: str) -> str:
    """연속 빈 줄 3줄 이상 → 1줄. 1~2줄은 그대로."""
    out, blank_run = [], []
    for line in text.splitlines():
        if line.strip():
            out.extend(blank_run if len(blank_run) < 3 else [""])
            blank_run = []
            out.append(line.rstrip())
        else:
            blank_run.append("")
    return "\n".join(out).strip()


def run_hwp5html(hwp5txt_exe: str, path: Path) -> str:
    """hwp5html 로 변환한 뒤 문서 순서대로 텍스트를 꺼낸다 (hwp5txt 가 <표> 로 버리는 표 셀 내용 포함).

    변환 결과는 attachments/_hwp5html/{파일명}/ 에 남긴다.
    """
    exe = str(Path(hwp5txt_exe).with_name(Path(hwp5txt_exe).name.replace("hwp5txt", "hwp5html")))
    out_dir = path.parent / "_hwp5html" / path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([exe, "--output", str(out_dir), str(path)], capture_output=True)
    index = out_dir / "index.xhtml"
    if proc.returncode != 0 or not index.exists():
        raise RuntimeError(f"hwp5html failed ({proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[-500:]}")
    soup = BeautifulSoup(index.read_text(encoding="utf-8"), "html.parser")
    return block_text(soup.body or soup)


def run_hwp5txt(exe: str, path: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.txt"
        proc = subprocess.run([exe, "--output", str(out), str(path)], capture_output=True)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"hwp5txt failed ({proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[-500:]}")
        return out.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 한 건 처리

class Collector:
    def __init__(self, kind: str, args, env: dict):
        self.kind = kind
        self.src = SOURCES[kind]
        self.args = args
        self.env = env
        self.raw_dir = RAW_DIR / kind
        self.att_dir = self.raw_dir / "attachments"
        self.session = list_scan.new_session()
        self.hwp5txt = hwp5txt_path(env)
        # decision.py 가 collector 를 import 하지 않고 쓰도록 넘기는 도구
        self.run_hwp5txt, self.run_hwp5html, self.normalize_hwp_text = run_hwp5txt, run_hwp5html, normalize_hwp_text
        self.block_text = block_text

    def html_path(self, key: str) -> Path:
        return self.raw_dir / f"{self.src['doc_kind']}_{key}.html"

    def collect(self, item: dict) -> dict:
        key = item["source_key"]
        doc_kind = self.src["doc_kind"]
        html_path = self.html_path(key)
        offline = self.args.reparse

        if offline or (self.args.skip_existing and html_path.exists()):
            html = html_path.read_text(encoding="utf-8")
        else:
            html = fetch(self.session, item["source_url"], {})
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html, encoding="utf-8")

        detail = parse_detail(html, self.src)
        notes = []

        # 첨부: 전부 저장
        attachments = []
        manifest_path = self.att_dir / f"{doc_kind}_{key}.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        for att in detail["attachments"]:
            sn = att["file_sn"]
            cached = manifest.get(sn)
            entry = {
                "name": att["display_name"],
                "display_name": att["display_name"],
                "box": att["box"],
                "url": att["url"],
                "local_path": None,
                "size": None,
                "shown_size": att["shown_size"],
                "content_type": None,
                "atch_file_id": att["atch_file_id"],
                "file_sn": sn,
            }
            # 첨부 하나가 실패해도 글은 저장한다 (download_error 로 기록, 다음 --skip-existing 실행 때 다시 시도)
            try:
                if (offline or self.args.skip_existing) and cached and (RAW_DIR / cached["local_path"]).exists():
                    original_name, content_type = cached["name"], cached.get("content_type")
                    local = RAW_DIR / cached["local_path"]
                elif offline:
                    raise RuntimeError("--reparse: 로컬에 첨부 파일 없음")
                else:
                    data, original_name, content_type = download(self.session, att["url"])
                    if not original_name:
                        notes.append(f"fileSn={sn}: Content-Disposition 파일명 없음 → 화면 이름 사용")
                        original_name = att["display_name"]
                    local = self.att_dir / f"{doc_kind}_{key}_{sn}.{ext_of(original_name)}"
                    self.att_dir.mkdir(parents=True, exist_ok=True)
                    local.write_bytes(data)
            except Exception as e:
                entry["download_error"] = str(e)
                notes.append(f"fileSn={sn}: 첨부 다운로드 실패 ({e})")
                attachments.append(entry)
                continue
            if ext_of(original_name) != ext_of(att["display_name"]):
                notes.append(f"fileSn={sn}: 화면 확장자({ext_of(att['display_name'])})와 실제 파일명 확장자({ext_of(original_name)}) 다름")
            entry.update({
                "name": original_name,
                "local_path": local.relative_to(RAW_DIR).as_posix(),
                "size": local.stat().st_size,
                "content_type": content_type,
            })
            attachments.append(entry)
        saved = [a for a in attachments if a["local_path"]]
        if saved and not offline:
            manifest_path.write_text(json.dumps(
                {a["file_sn"]: {"name": a["name"], "local_path": a["local_path"], "content_type": a["content_type"]}
                 for a in saved}, ensure_ascii=False, indent=2), encoding="utf-8")

        info = dict(detail["info"])
        if doc_kind == "DECISION":  # 결정례 화면의 작성자·담당자 이름·이메일(개인정보)은 저장하지 않는다
            for k in PERSONAL_INFO_KEYS:
                info.pop(k, None)
        category = info.pop("권역", None) or item.get("category")
        registered_at = info.pop("등록일", None) or item.get("registered_at")
        summary = info.pop("요지", None)
        product_type = info.pop("유형", None) or item.get("type") or None
        meta = {
            "list_no": item.get("list_no"),
            "views": int(info.pop("조회수")) if info.get("조회수", "").isdigit() else info.pop("조회수", None),
            "department": detail["admin"].get("담당부서"),
            "department_phone": detail["admin"].get("전화번호"),
        }
        meta.update({k: v for k, v in info.items()})  # 화면에 있는 나머지 dt/dd
        if detail["title"] != item.get("title") and item.get("title"):
            meta["list_title"] = item["title"]

        row = {
            "doc_kind": doc_kind,
            "source_url": item["source_url"],
            "source_key": key,
            "category": category,
            "product_type": product_type,
            "title": detail["title"] or item.get("title"),
            "summary": summary,
            "complaint": None,
            "dispute_issue": None,
            "decision_reason": None,
            "consumer_warning": None,
            "raw_text": None,
            "raw_file_path": html_path.relative_to(RAW_DIR).as_posix(),
            "attachments": attachments,
            "meta": meta,
            "registered_at": registered_at,
        }

        if doc_kind == "DECISION":
            decision.fill(row, detail, attachments, item, notes, self)
        elif doc_kind == "CASE":
            row["raw_text"] = detail["body_text"] or None
            case_text = detail["body_text"]
            # HTML 본문에 ▣ 구간이 하나도 없으면 상세내용 첨부 hwp 로 다시 나눈다 (예: CASE 38, 145)
            if not split_sections(case_text):
                detail_hwp = [a for a in attachments
                              if a["box"] and "상세내용" in a["box"] and a["local_path"] and ext_of(a["local_path"]) == "hwp"]
                if len(detail_hwp) == 1:
                    hwp_path = RAW_DIR / detail_hwp[0]["local_path"]
                    meta["html_body_text"] = detail["body_text"] or None
                    meta["raw_text_file"] = detail_hwp[0]["local_path"]
                    hwp_text = normalize_hwp_text(run_hwp5txt(self.hwp5txt, hwp_path))
                    if split_sections(hwp_text):
                        meta["raw_text_source"] = detail_hwp[0]["local_path"]
                        meta["table_placeholders"] = hwp_text.count(TABLE_PLACEHOLDER)
                        case_text = hwp_text
                        notes.append("HTML 본문에 ▣ 구간 없음 → 상세내용 hwp(hwp5txt) 로 재파싱")
                    else:
                        # 본문이 전부 표 안에 있으면 hwp5txt 는 <표> 만 남긴다 → hwp5html 로 표 셀까지 꺼낸다
                        case_text = run_hwp5html(self.hwp5txt, hwp_path)
                        meta["raw_text_source"] = "hwp5html(표)"
                        notes.append("HTML 본문·hwp5txt 에 ▣ 구간 없음 → 상세내용 hwp(hwp5html) 로 재파싱")
                    row["raw_text"] = case_text or None
                else:
                    notes.append(f"HTML 본문에 ▣ 구간 없음, 상세내용 hwp {len(detail_hwp)}개라 재파싱 안 함")
            found, unmatched = set(), []
            for heading, body in split_sections(case_text):
                col, content = match_heading(heading, body, CASE_SECTIONS)
                if col is None:
                    unmatched.append(heading)
                    continue
                found.add(col)
                if EMPTY_MARK.match(content):
                    notes.append(f"구간 내용 없음(-): {CASE_SECTIONS[col]}")
                    continue
                if row[col] is not None:
                    notes.append(f"구간 중복: {heading}")
                    row[col] += "\n" + content
                else:
                    row[col] = content
            if unmatched:
                meta["unmatched_sections"] = unmatched
            missing = [CASE_SECTIONS[c] for c in CASE_SECTIONS if c not in found]
            if missing:
                notes.append(f"구간 못 찾음: {missing}")
            meta["cardnews"] = [a["name"] for a in attachments if a["box"] and "카드뉴스" in a["box"]]
        else:
            html_body = "\n".join(line for line in detail["body_text"].splitlines() if not INQUIRY_LINE.match(line))
            sections = split_sections(html_body)
            meta["html_sections"] = [{"heading": h, "text": b} for h, b in sections]
            if html_body and not sections:
                meta["html_body_text"] = html_body
            body_candidates = [a for a in attachments if FORM_MARKER not in (a["name"] or "")]
            for a in attachments:
                a["is_body"] = a in body_candidates and len(body_candidates) == 1
            if len(body_candidates) != 1:
                meta["raw_text_reason"] = f"본문 후보 {len(body_candidates)}개: {[a['name'] for a in body_candidates]}"
            elif not body_candidates[0]["local_path"]:
                meta["raw_text_reason"] = f"본문 첨부 다운로드 실패: {body_candidates[0]['name']}"
            elif ext_of(body_candidates[0]["name"]) != "hwp":
                meta["raw_text_reason"] = f"본문 후보가 hwp 아님: {body_candidates[0]['name']}"
            else:
                text = normalize_hwp_text(run_hwp5txt(self.hwp5txt, RAW_DIR / body_candidates[0]["local_path"]))
                row["raw_text"] = text or None
                meta["raw_text_source"] = body_candidates[0]["local_path"]
                meta["table_placeholders"] = text.count(TABLE_PLACEHOLDER)
                if not row["raw_text"]:
                    meta["raw_text_reason"] = "hwp5txt 결과가 비어 있음"
            if "raw_text_reason" in meta:
                notes.append(meta["raw_text_reason"])

        for col in TEXT_COLUMNS:  # 빈 문자열(공백뿐 포함) → NULL
            if isinstance(row[col], str) and not row[col].strip():
                row[col] = None
        if notes:
            meta["parse_notes"] = notes
        return row


# ---------------------------------------------------------------- DB

UPSERT_SQL = """
INSERT INTO dispute_case (doc_kind, source_url, source_key, category, product_type, title, summary,
    complaint, dispute_issue, decision_reason, consumer_warning, raw_text, raw_file_path,
    attachments, meta, registered_at)
VALUES (%(doc_kind)s, %(source_url)s, %(source_key)s, %(category)s, %(product_type)s, %(title)s,
    %(summary)s, %(complaint)s, %(dispute_issue)s, %(decision_reason)s, %(consumer_warning)s, %(raw_text)s,
    %(raw_file_path)s, %(attachments)s, %(meta)s, %(registered_at)s)
ON CONFLICT (source_url) DO UPDATE SET
    doc_kind = EXCLUDED.doc_kind, source_key = EXCLUDED.source_key,
    category = EXCLUDED.category, product_type = EXCLUDED.product_type, title = EXCLUDED.title,
    summary = EXCLUDED.summary,
    complaint = EXCLUDED.complaint, dispute_issue = EXCLUDED.dispute_issue,
    decision_reason = EXCLUDED.decision_reason, consumer_warning = EXCLUDED.consumer_warning,
    raw_text = EXCLUDED.raw_text, raw_file_path = EXCLUDED.raw_file_path,
    attachments = EXCLUDED.attachments, meta = EXCLUDED.meta, registered_at = EXCLUDED.registered_at,
    updated_at = now()
"""


def connect(env: dict):
    import psycopg
    return psycopg.connect(
        host=env.get("POSTGRES_HOST", "localhost"),
        port=env.get("POSTGRES_PORT", "5432"),
        dbname=env.get("POSTGRES_DB", "sona"),
        user=env.get("POSTGRES_USER", "sona"),
        password=env.get("POSTGRES_PASSWORD", ""),
        autocommit=True,
    )


# ---------------------------------------------------------------- main

def load_items(kind: str, args) -> list[dict]:
    list_file = RAW_DIR / f"list_{kind}.json"
    if not list_file.exists():
        if args.reparse:
            raise RuntimeError(f"--reparse 에는 {list_file} 가 필요합니다")
        list_scan.scan(kind, list_scan.new_session())
    items = json.loads(list_file.read_text(encoding="utf-8"))["items"]
    if args.keys:
        wanted = [k.strip() for k in args.keys.split(",") if k.strip()]
        by_key = {i["source_key"]: i for i in items}
        missing = [k for k in wanted if k not in by_key]
        if missing:
            raise RuntimeError(f"목록에 없는 key: {missing}")
        items = [by_key[k] for k in wanted]
    if args.limit:
        items = items[: args.limit]
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="금감원 분쟁조정 자료 수집기")
    parser.add_argument("--kind", choices=["case", "standard", "decision"], required=True)
    parser.add_argument("--keys", help="caseSlno / prcdntSlno / nttId 목록 (쉼표 구분)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--reparse", action="store_true")
    parser.add_argument("--report", help="처리 결과 요약 JSON 저장 경로 (DECISION 은 섹션·글자 수 요약)")
    args = parser.parse_args()

    env = load_env()
    collector = Collector(args.kind, args, env)
    items = load_items(args.kind, args)
    doc_kind = SOURCES[args.kind]["doc_kind"]

    started_at = datetime.now(timezone.utc)
    report_path = args.report or (None if args.dry_run else str(
        RAW_DIR / "_report" / f"collect_{args.kind}_{started_at.strftime('%Y%m%dT%H%M%SZ')}.json"))
    full_rows = bool(args.report)  # --report 를 직접 준 경우만 CASE/STANDARD 행 전체를 넣고, 기본 리포트는 요약만
    conn = None if args.dry_run else connect(env)

    from psycopg.types.json import Jsonb
    ok, failed, errors, reported, row_count, skipped = 0, 0, [], [], 0, 0
    for item in items:
        key = item["source_key"]
        try:
            row = collector.collect(item)
            # DECISION 은 결정서마다 한 행 (한 게시물에 여러 개일 수 있음)
            rows = decision.split_rows(row) if doc_kind == "DECISION" else [row]
            if doc_kind == "DECISION" and not rows:  # 본문을 뽑은 결정서 없음 (HWP 3.0·PDF·TIF 뿐) → 저장 안 함
                skipped += 1
                if report_path:
                    reported.append(decision.skipped_view(row))
                print(f"[{doc_kind} {key}] skipped  {row['meta'].get('parse_notes', [])}")
                continue
            if args.dry_run:
                if doc_kind != "DECISION":  # DECISION 은 --report 로 본다
                    print(json.dumps(row, ensure_ascii=False, indent=2)[:3000])
            else:
                with conn.transaction():
                    for r in rows:
                        params = dict(r, attachments=Jsonb(r["attachments"]), meta=Jsonb(r["meta"]))
                        conn.execute(UPSERT_SQL, params)
            ok += 1
            row_count += len(rows)
            if report_path:
                reported.extend(decision.report_view(r) if doc_kind == "DECISION"
                                else r if full_rows
                                else {"source_key": r["source_key"], "source_url": r["source_url"], "title": r["title"],
                                      "parse_notes": r["meta"].get("parse_notes", [])}
                                for r in rows)
            for r in rows:
                print(f"[{doc_kind} {r['source_key']}] ok  notes={r['meta'].get('parse_notes', [])}")
        except Exception as e:  # 한 건 실패가 전체를 멈추지 않도록
            failed += 1
            errors.append(f"{key}: {e}")
            if report_path:
                reported.append({"source_key": key, "source_url": item["source_url"], "failed": True,
                                 "title": item.get("title"), "registered_at": item.get("registered_at"),
                                 "error": str(e)[:500]})
            print(f"[{doc_kind} {key}] FAILED {e}", file=sys.stderr)
            traceback.print_exc()

    if conn:
        conn.close()
    if report_path:
        out = Path(report_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        summary = {"doc_kind": doc_kind, "dry_run": args.dry_run, "status": "SUCCESS" if failed == 0 else "FAILED",
                   "started_at": started_at.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
                   "options": {"keys": args.keys, "limit": args.limit, "skip_existing": args.skip_existing,
                               "reparse": args.reparse},
                   "total": len(items), "ok": ok, "rows": row_count,
                   "skipped": skipped, "failed": failed, "errors": errors}
        if doc_kind == "DECISION":
            summary["site"] = decision.site_summary()
        out.write_text(json.dumps({**summary, "items": reported},
                                  ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"report: {out}")
    print(f"done: total={len(items)} ok={ok} skipped={skipped} failed={failed} rows={row_count}")


if __name__ == "__main__":
    main()
