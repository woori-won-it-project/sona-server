"""분쟁조정결정례(DECISION, 보험) 파싱. collector.py --kind decision 이 상세 HTML·첨부를 받은 뒤 fill() 을 부른다.

사이트 구조 (2026-11-24 확인):
- 목록 /fss/bbs/B0000390/list.do?menuNo=201193 (게시판형), 보험 탭 cl1Cd=B. 상세 view.do?nttId=...
- 상세 HTML 본문(div.n-dbdata)은 "…조정안을 첨부와 같이 등록합니다" 한두 줄뿐, 결정문 전문은 첨부(HWP, 일부 PDF)에만 있다.
- 결정서 구성: [머리 표: 조정일자/결정일자/의결 년월일, 조정번호/의안번호] 안건명, 당사자(신청인·피신청인), 주문, 신청취지,
  이유(기초 사실/사실관계, 당사자 주장, 위원회 판단, 결론), <붙임>(관련 약관).
- 한 게시물에 결정서가 여러 개일 수 있다 (예: nttId 218695 = 제2026-3·4·5호) → 결정서마다 한 행:
  source_url = 게시물 URL + '#' + 조정번호, source_key = nttId + '-' + 순번 (결정서 하나면 그대로).
- PDF·TIF 첨부는 이번 단계에서 텍스트를 뽑지 않고 meta.skipped_attachments 에 목록만 남긴다.

텍스트 추출: HWP BodyText 문단 레코드를 직접 읽는다 (표 셀·각주 포함, 문서 순서) → 실패하면 hwp5html.
  - hwp5txt 는 표를 <표> 로 버려 머리 표 안의 결정일·조정번호를 잃는다.
  - hwp5html 은 일부 본문 문단을 빠뜨리고 (샘플 64799: 위원회 판단 10문단 누락), 잘못된 문자가 든 파일(64816)에서 실패한다.
  - 각주는 본문 문장 중간이 아니라 해당 문단 뒤에 별도 문단으로 나온다.

dispute_case 컬럼 대응 (스키마 변경 없음):
    dispute_issue    안건명
    summary          주문
    complaint        기초 사실 (사실관계)
    decision_reason  위원회 판단 + 결론
    consumer_warning NULL
    raw_text         결정서 전문
    meta             decision_no, decision_date(+source), agenda, applicant/respondent(익명 표시), body_file,
                     extract_method, missing_sections, skipped_attachments, site_type,
                     sections [{name, key, chars, column | text}] — 컬럼에 안 들어간 섹션(당사자 주장·신청취지 등)은 text 보관
"""
import re
import struct
import zlib
from pathlib import Path

from list_scan import RAW_DIR

# 사이트 '유형' 값 보정: 보험 탭의 cl2Cd=B1 이 화면에 '금융투자기타'로 표시되지만 실제 글은 생명보험 사례다
SITE_TYPE_FIX = {"금융투자기타": "생명보험"}

# 정규화(숫자·가나다 번호, 공백, 괄호, 콜론 제거)한 제목 → 섹션 키
HEADINGS = {
    "안건명": "agenda",
    "당사자": "parties",
    "주문": "order",
    "신청취지": "claim",
    "이유": "reason",
    "기초사실": "facts", "사실관계": "facts", "사건개요": "facts", "기초사실관계": "facts",
    "당사자주장": "arguments", "당사자의주장": "arguments",
    "위원회판단": "judgment", "위원회의판단": "judgment", "판단": "judgment",
    "결론": "conclusion",
    "붙임": "appendix",
}
SECTION_NAMES = {
    "header": "머리말(결정일·조정번호)", "agenda": "안건명", "parties": "당사자", "order": "주문", "claim": "신청취지",
    "reason": "이유(소제목 전)", "facts": "기초 사실", "arguments": "당사자 주장", "judgment": "위원회 판단",
    "conclusion": "결론", "appendix": "붙임(약관 등)",
}
BEFORE_ORDER = {"agenda", "parties"}               # 주문 앞에서만 인정하는 제목
UNDER_REASON = {"facts", "arguments", "judgment", "conclusion"}
NUMBERING = re.compile(r"^\s*(?:\(?\d+\)|\d+\.|[가-하][.)]|\([가-하]\)|[ⅠⅡⅢⅣⅤ]\.?)\s*")
HEADING_MAX = 20                                   # 정규화 후 이보다 길면 제목 아님
DATE = r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})"
DATE_PATTERNS = [
    ("조정일자/결정일자", re.compile(rf"(?:조정|결정)\s*일\s*자\s*[:：]?\s*{DATE}")),
    ("의결 년월일", re.compile(rf"의\s*결\s*년\s*월\s*일\s*{DATE}")),
]
# 2007년 무렵 서식: 안건명 아래 '(2007. 4. 24. 결정 제2007-22호)'. 위원회 판단에서 옛 결정을 같은 꼴로 인용하므로
# 주문 앞(머리말·안건명·당사자)에서 처음 나온 것만 인정하고, 그 줄은 안건명에서 지운다.
# 괄호 안 순서는 서식마다 다르다: '(2007. 4. 24. 결정 제2007-22호)', '(제2004-53호, 2004.9.21. 결정)', '(2005. 7. 26.결정, 2005-50호)'
INLINE_DECISION = re.compile(r"\(([^()]*결정[^()]*)\)")
INLINE_NUMBER = re.compile(r"(제?\s*\d{4}\s*-\s*\d+\s*호)")
HTML_DATE = re.compile(rf"{DATE}\s*\.?\s*자?\s*금융분쟁조정위원회")
NUMBER = re.compile(r"(?:조정번호|의안번호|조정결정서|의결안건)\s*[:：]?\s*(제?\s*\d{4}\s*-\s*\d+\s*호)")
HWP3_SIGNATURE = b"HWP Document File V3"           # 2002년 이전 HWP 3.0 (pyhwp·olefile 로 못 읽음)
FILE_NUMBER = re.compile(r"(\d{4})\s*-\s*(\d+)\s*호")


# ---------------------------------------------------------------- 텍스트 추출

def hwp_records_text(path: Path) -> str:
    """HWP5 BodyText 의 문단 글자 레코드(HWPTAG_PARA_TEXT)를 문서 순서대로 읽는다. 표 셀·각주 문단도 순서대로 나온다."""
    import olefile
    ole = olefile.OleFileIO(str(path))
    try:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack("<I", header[36:40])[0]
        if flags & 0x04:
            raise RuntimeError("배포용(암호화) HWP 라 본문을 읽을 수 없음")
        compressed = bool(flags & 0x01)
        sections = sorted((e for e in ole.listdir() if e[0] == "BodyText"), key=lambda e: int(e[1][len("Section"):]))
        paragraphs = []
        for entry in sections:
            data = ole.openstream(entry).read()
            if compressed:
                data = zlib.decompress(data, -15)
            pos = 0
            while pos + 4 <= len(data):
                head = struct.unpack("<I", data[pos:pos + 4])[0]
                tag, size = head & 0x3FF, (head >> 20) & 0xFFF
                pos += 4
                if size == 0xFFF:
                    size = struct.unpack("<I", data[pos:pos + 4])[0]
                    pos += 4
                if tag == 67:  # HWPTAG_PARA_TEXT
                    paragraphs.append(_para_text(data[pos:pos + size]))
                pos += size
        return "\n".join(p for p in (x.strip() for x in paragraphs) if p)
    finally:
        ole.close()


def _para_text(raw: bytes) -> str:
    out, i, n = [], 0, len(raw) // 2
    while i < n:
        code = struct.unpack("<H", raw[i * 2:i * 2 + 2])[0]
        if code >= 32:
            out.append(chr(code))
            i += 1
        elif code in (9,):              # 탭 (인라인 컨트롤, 8 WCHAR)
            out.append(" ")
            i += 8
        elif code in (10, 13):          # 줄바꿈 / 문단 끝
            out.append("\n")
            i += 1
        elif code in (0, 24, 25, 26, 27, 28, 29, 30, 31):
            i += 1                      # 1 WCHAR 문자 컨트롤
        else:
            i += 8                      # 확장·인라인 컨트롤 (표, 각주 등): 8 WCHAR
    # UTF-16 서로게이트 쌍(한자 확장·특수기호)을 한 글자로 합친다. 짝 없는 서로게이트는 U+FFFD
    return "".join(out).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


HWP5HTML_TIMEOUT_SEC = 120  # 배포용 HWP 중 hwp5html 이 끝나지 않는 파일이 있다 (예: 64766, 30분 넘게 CPU 100%)


def run_hwp5html_limited(tools, path: Path) -> str:
    """collector.run_hwp5html 과 같은 변환이지만 시간 제한을 둔다 (CASE 쪽 함수는 건드리지 않음)."""
    import subprocess
    from bs4 import BeautifulSoup
    exe = str(Path(tools.hwp5txt).with_name(Path(tools.hwp5txt).name.replace("hwp5txt", "hwp5html")))
    out_dir = path.parent / "_hwp5html" / path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run([exe, "--output", str(out_dir), str(path)], capture_output=True,
                              timeout=HWP5HTML_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"hwp5html {HWP5HTML_TIMEOUT_SEC}초 초과로 중단") from None
    index = out_dir / "index.xhtml"
    if proc.returncode != 0 or not index.exists():
        raise RuntimeError(f"hwp5html failed ({proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[-300:]}")
    soup = BeautifulSoup(index.read_text(encoding="utf-8"), "html.parser")
    return tools.block_text(soup.body or soup)


def extract_text(tools, path: Path) -> tuple[str, str, str | None]:
    """반환: (텍스트, 추출 방식, 앞 방식 실패 사유)."""
    try:
        return hwp_records_text(path), "hwp_records", None
    except Exception as e:  # noqa: BLE001 - 어떤 오류든 다음 방식으로
        reason = str(e).strip().splitlines()[-1][:200]
    return run_hwp5html_limited(tools, path), "hwp5html", f"HWP 문단 레코드 읽기 실패: {reason}"


# ---------------------------------------------------------------- 섹션

AGENDA_LINE = re.compile(r"^\s*(?:\d+\.\s*)?안\s*건\s*명\s*[:：]?\s*(.*)$")
PARTY_LINE = re.compile(r"^\s*(?:피\s*)?신\s*청\s*인(?!\s*의)\s*[:：]?\s*\S")


# 번호가 붙거나 띄어 쓴 붙임 제목: '< 붙임 1 >', '<붙임2>', '<참고>', '<참 고>' — 정규화하면 '붙임1' 이라 HEADINGS 에 안 걸린다.
# 본문 속 '참고:' 같은 문장과 헷갈리지 않게 괄호로 감싼 한 줄만 인정
APPENDIX_BRACKET_LINE = re.compile(r"^\s*[<〈＜【\[]\s*(?:붙\s*임|참\s*고)\s*\d*\s*[>〉＞】\]]\s*$")


def heading_key(line: str) -> tuple[str | None, str]:
    """제목 줄이면 (섹션 키, 같은 줄에 붙은 내용). 아니면 (None, '')."""
    m = AGENDA_LINE.match(line)  # '안 건 명     자동차보험에서 …' (콜론 없이 내용이 붙는 서식 포함)
    if m:
        return "agenda", m.group(1).strip()
    if APPENDIX_BRACKET_LINE.match(line):  # '< 붙임 1 >', '<붙임2>', '<참 고>' (괄호로 감싼 한 줄만)
        return "appendix", ""
    if PARTY_LINE.match(line) and len(line.strip()) <= 40:  # '신 청 인  X', '피 신 청 인  Y생명보험㈜' (당사자 제목 없는 서식)
        return "parties", line.strip()
    body = NUMBERING.sub("", line).strip().strip("<>[]【】")
    m = re.match(r"^([^:：]{1,30})[:：]\s*(.*)$", body)
    title, rest = (m.group(1), m.group(2)) if m else (body, "")
    norm = re.sub(r"[\s<>\[\]【】]", "", title)
    if len(norm) > HEADING_MAX:
        return None, ""
    if norm in HEADINGS:
        return HEADINGS[norm], rest.strip()
    return None, ""


TOP_NUMBER = re.compile(r"^\s*(\d+)\.\s*\S")
PROMOTE_HEADING_MAX = 60  # 위원회 판단으로 올리는 번호 제목 줄의 최대 길이


def split_sections(text: str, promote_judgment: bool = False) -> list[dict]:
    """줄 단위로 제목을 찾아 [{key, name, text}] (문서 순서, 같은 키가 두 번 나오면 두 번째에 '_2').

    promote_judgment: '이유' 아래에서 당사자 주장 다음, 결론 앞에 오는 번호 제목('3. 약관상 수술의 정의 …')을
    위원회 판단의 시작으로 본다 (판단 제목 없이 주제별 제목을 쓰는 서식, 예: 64814). 그 제목 줄은 판단 본문에 남긴다.
    """
    sections, current, buf = [], "header", []
    seen_order = in_reason = False
    args_number = None  # 당사자 주장 제목의 번호 ('2. 당사자 주장' → 2)
    sections_promoted: list[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body or current != "header":
            sections.append({"key": current, "text": body})

    for line in text.splitlines():
        key, rest = heading_key(line)
        if key in BEFORE_ORDER and seen_order:
            key = None
        if key in UNDER_REASON and not in_reason:
            key = None if key != "judgment" else key  # 이유 제목 없이 바로 '판단' 이 오는 서식 허용
        if key == "parties" and current == "parties":  # 신청인 다음 줄의 피신청인 → 같은 섹션
            buf.append(rest)
            continue
        promoted = False
        if key is None and promote_judgment and current == "arguments" and args_number is not None:
            m = TOP_NUMBER.match(line)
            if m and int(m.group(1)) == args_number + 1 and len(line.strip()) <= PROMOTE_HEADING_MAX:
                key, rest, promoted = "judgment", line.strip(), True
        if key is None:
            buf.append(line)
            continue
        flush()
        current, buf = key, []
        if rest:
            buf.append(rest)
        if key == "arguments":
            m = TOP_NUMBER.match(line)
            args_number = int(m.group(1)) if m else None
        if promoted:
            sections_promoted.append(line.strip())
        if key == "order":
            seen_order = True
        if key == "reason":
            in_reason = True
        if key == "appendix":
            in_reason = False
    flush()

    counts: dict[str, int] = {}
    for s in sections:
        counts[s["key"]] = counts.get(s["key"], 0) + 1
        s["name"] = SECTION_NAMES[s["key"]] + (f" ({counts[s['key']]})" if counts[s["key"]] > 1 else "")
    result = [s for s in sections if s["text"] or s["key"] not in ("header", "reason")]
    if sections_promoted:
        for s in result:
            if s["key"] == "judgment":
                s["promoted_from"] = sections_promoted[0]
                break
    return result


def iso_date(m: re.Match) -> str:
    return iso_date_groups(m.groups()[-3:])


def iso_date_groups(groups) -> str:
    y, mo, d = (int(x) for x in groups)
    return f"{y:04d}-{mo:02d}-{d:02d}"


def parse_document(text: str, file_name: str | None) -> dict:
    flat = re.sub(r"\s+", " ", text[:3000])  # 결정일·번호는 문서 머리에 있다
    decision_date = date_source = None
    for label, pat in DATE_PATTERNS:
        m = pat.search(flat)
        if m:
            decision_date, date_source = iso_date(m), label
            break
    m = NUMBER.search(flat)
    number = re.sub(r"\s+", "", m.group(1)) if m else None
    if number and not number.startswith("제"):
        number = "제" + number
    if not number and file_name:
        fm = FILE_NUMBER.search(file_name)
        number = f"제{fm.group(1)}-{fm.group(2)}호" if fm else None

    sections = split_sections(text)
    judgment_promoted = None
    if not any(s["key"] == "judgment" for s in sections) and any(s["key"] == "arguments" for s in sections):
        retry = split_sections(text, promote_judgment=True)
        judgment_promoted = next((s.get("promoted_from") for s in retry if s.get("promoted_from")), None)
        if judgment_promoted:
            sections = retry
    order_at = next((i for i, s in enumerate(sections) if s["key"] == "order"), len(sections))
    for s in sections[:order_at]:  # 주문 앞에서만
        found = [m for m in INLINE_DECISION.finditer(s["text"]) if re.search(DATE, m.group(1))]
        if found and not decision_date:
            inner = found[0].group(1)
            decision_date = iso_date(re.search(DATE, inner))
            date_source = "안건명 아래 '(… 결정 …호)'"
            nm = INLINE_NUMBER.search(re.sub(DATE, "", inner))
            if not number and nm:
                number = re.sub(r"\s+", "", nm.group(1))
                number = number if number.startswith("제") else "제" + number
        if s["key"] == "agenda" and found:
            for m in found:
                s["text"] = s["text"].replace(m.group(0), "")
            s["text"] = "\n".join(x for x in s["text"].splitlines() if x.strip()).strip()
    by_key: dict[str, str] = {}
    for s in sections:
        by_key[s["key"]] = "\n".join(x for x in (by_key.get(s["key"]), s["text"]) if x)
    parties = by_key.get("parties", "")
    applicant = re.search(r"(?m)^\s*신\s*청\s*인\s*[:：]?\s*(.+)$", parties)
    respondent = re.search(r"(?m)^\s*피\s*신\s*청\s*인\s*[:：]?\s*(.+)$", parties)
    return {
        "decision_date": decision_date,
        "decision_date_source": date_source,
        "decision_no": number,
        "agenda": (by_key.get("agenda") or "").splitlines()[0].strip() if by_key.get("agenda") else None,
        "applicant": applicant.group(1).strip() if applicant else None,
        "respondent": respondent.group(1).strip() if respondent else None,
        "claim": by_key.get("claim") or None,
        "sections": sections,
        "by_key": by_key,
        "judgment_promoted_from": judgment_promoted,
    }


# ---------------------------------------------------------------- 주문 → 처분

# 주문 문장 기준. '각하' > '일부인용'(기각 + 인용 지시가 함께, 또는 '나머지/부분 … 기각') > '기각' > '인용'
POSITIVE = re.compile(r"지급하[라고여]|지급하도록|보상하라|인용한다|확인한다|원상회복|부활|취소하|환급하라|승인하라|반환하|"
                      r"면제하라|배상할\s*책임|소멸한다")
PARTIAL_DISMISS = re.compile(r"(?:나머지|부분)[^.]{0,20}기각")


def disposition(order: str | None) -> str | None:
    """주문 → '각하' / '기각' / '일부인용' / '인용' / '미분류'. 주문이 없으면 None."""
    if not order or not order.strip():
        return None
    text = re.sub(r"\s+", " ", order)
    if "각하" in text and not POSITIVE.search(text):
        return "각하"
    dismiss = "기각" in text
    if dismiss and (POSITIVE.search(text) or PARTIAL_DISMISS.search(text)):
        return "일부인용"
    if dismiss:
        return "기각"
    if POSITIVE.search(text):
        return "인용"
    return "미분류"


TITLE_NUMBER = re.compile(r"\(\s*(\d{4})\s*-\s*(\d+)\s*\)\s*$")  # 게시물 제목 끝 '(2004-79)'


def number_from_title(title: str | None) -> str | None:
    m = TITLE_NUMBER.search(title or "")
    return f"제{m.group(1)}-{m.group(2)}호" if m else None


# ---------------------------------------------------------------- 한 건

# 컬럼에 들어가는 섹션. 나머지(머리말·당사자·신청취지·당사자 주장·붙임 등)는 meta.sections 에 본문까지 보관
COLUMN_SECTIONS = {"agenda": "dispute_issue", "order": "summary", "facts": "complaint",
                   "judgment": "decision_reason", "conclusion": "decision_reason"}
CHECK_SECTIONS = ("agenda", "order", "claim", "facts", "arguments", "judgment", "conclusion")  # 누락 점검 대상


def fill(row: dict, detail: dict, attachments: list[dict], item: dict, notes: list[str], tools) -> None:
    """게시물 단위 처리: 유형 보정, 첨부별 결정서 추출·파싱. 행 나누기는 split_rows() 가 한다."""
    meta = row["meta"]
    site_type = item.get("type")
    meta["site_type"] = site_type
    row["product_type"] = SITE_TYPE_FIX.get(site_type, site_type) if site_type else None
    if site_type in SITE_TYPE_FIX:
        notes.append(f"사이트 유형 '{site_type}' → product_type '{row['product_type']}' (보험 탭 B1 표시 오류 보정)")
    meta["html_body_text"] = detail["body_text"] or None
    html_date = HTML_DATE.search(re.sub(r"\s+", " ", detail["body_text"] or ""))

    docs, skipped = [], []
    for a in attachments:
        if not a["local_path"]:
            skipped.append({"name": a["name"], "ext": None, "reason": a.get("download_error") or "다운로드 안 됨"})
            continue
        ext = a["local_path"].rsplit(".", 1)[-1].lower()
        if ext != "hwp":
            skipped.append({"name": a["name"], "ext": ext, "reason": f"{ext.upper()} (이번 단계에서 건너뜀)"})
            continue
        with open(RAW_DIR / a["local_path"], "rb") as f:
            if f.read(len(HWP3_SIGNATURE)) == HWP3_SIGNATURE:
                skipped.append({"name": a["name"], "ext": ext, "reason": "HWP 3.0 (이번 단계에서 건너뜀)"})
                continue
        try:
            text, method, fallback_reason = extract_text(tools, RAW_DIR / a["local_path"])
        except Exception as e:  # noqa: BLE001
            skipped.append({"name": a["name"], "ext": ext, "reason": f"추출 실패: {str(e)[:200]}"})
            continue
        if fallback_reason:
            notes.append(f"{a['name']}: {fallback_reason} → hwp5html 사용")
        doc = parse_document(text, a["name"])
        doc.update(file=a["local_path"], file_name=a["name"], extract_method=method, text=text)
        if not doc["decision_date"] and html_date:
            doc["decision_date"], doc["decision_date_source"] = iso_date(html_date), "HTML 본문 문장"
        docs.append(doc)
    if skipped:
        meta["skipped_attachments"] = skipped
        notes.append(f"본문 추출 안 한 첨부 {len(skipped)}개: {[s['name'] for s in skipped]}")
    if not docs:
        notes.append("결정서 본문 없음")
    row["_docs"] = docs  # split_rows() 전용 (DB 컬럼 아님)


def split_rows(row: dict) -> list[dict]:
    """결정서마다 한 행. 결정서가 여럿이면 source_url 에 '#조정번호', source_key 에 '-순번' 을 붙인다.

    본문을 뽑은 결정서가 하나도 없으면 (HWP 3.0·PDF·TIF 뿐이거나 첨부 없음) 빈 목록 → DB 에 저장하지 않는다
    (본문 없는 행이 검색 대상에 섞이지 않게). 보고는 skipped_view() 로.
    """
    docs = row.pop("_docs", [])
    if not docs:
        return []
    multi = len(docs) > 1
    post_notes = row["meta"].pop("parse_notes", [])
    rows = []
    for i, d in enumerate(docs, 1):
        r = dict(row)
        meta = dict(row["meta"])
        if multi:
            r["source_url"] = f"{row['source_url']}#{d['decision_no']}"
            r["source_key"] = f"{row['source_key']}-{i}"
            meta.update(post_source_url=row["source_url"], post_source_key=row["source_key"],
                        doc_index=i, doc_count=len(docs))
        by_key = d["by_key"]
        r["dispute_issue"] = by_key.get("agenda") or None
        r["summary"] = by_key.get("order") or None
        r["complaint"] = by_key.get("facts") or None
        r["decision_reason"] = "\n\n".join(by_key[k] for k in ("judgment", "conclusion") if by_key.get(k)) or None
        r["consumer_warning"] = None
        r["raw_text"] = d["text"] or None

        notes = list(post_notes)
        missing = [SECTION_NAMES[k] for k in CHECK_SECTIONS if not by_key.get(k)]
        if missing:
            notes.append(f"섹션 못 찾음: {missing}")
        if not d["decision_date"]:
            notes.append("결정일 못 찾음")
        decision_no, decision_no_source = d["decision_no"], ("결정서 파일" if d["decision_no"] else None)
        if not decision_no and not multi:  # 파일에 조정번호가 없으면 게시물 제목 끝 '(2004-79)' 에서
            decision_no = number_from_title(row.get("title"))
            if decision_no:
                decision_no_source = "게시물 제목"
                notes.append(f"조정번호 파일에 없음 → 게시물 제목에서 {decision_no}")
        if d.get("judgment_promoted_from"):
            notes.append(f"위원회 판단 제목 없음 → 당사자 주장 다음 번호 제목 "
                         f"'{d['judgment_promoted_from']}' 부터 결론 앞까지를 위원회 판단으로 분류")
        meta.update({
            "decision_no": decision_no,
            "decision_no_source": decision_no_source,
            "disposition": disposition(r["summary"]),
            "decision_date": d["decision_date"],
            "decision_date_source": d["decision_date_source"],
            "agenda": d["agenda"],
            "applicant": d["applicant"],
            "respondent": d["respondent"],
            "body_file": d["file"],
            "body_file_name": d["file_name"],
            "extract_method": d["extract_method"],
            "missing_sections": missing,
            "judgment_promoted_from": d.get("judgment_promoted_from"),
            "sections": [{"name": s["name"], "key": s["key"], "chars": len(s["text"]),
                          **({"column": COLUMN_SECTIONS[s["key"]]} if s["key"] in COLUMN_SECTIONS
                             else {"text": s["text"]})}
                         for s in d["sections"]],
        })
        if notes:
            meta["parse_notes"] = notes
        r["meta"] = meta
        rows.append(r)
    return rows




def site_summary() -> dict:
    """list_decision.json(보험 탭 목록) 기준 건수 요약 + 확인한 페이지 구조."""
    import json
    from collections import Counter
    listing = json.loads((RAW_DIR / "list_decision.json").read_text(encoding="utf-8"))
    items = listing["items"]
    exts = Counter(a["name"].rsplit(".", 1)[-1].lower() for i in items for a in i["attachments"] if a["name"])
    return {
        "list_url_all": "https://www.fss.or.kr/fss/bbs/B0000390/list.do?menuNo=201193",
        "list_url_insurance": listing["list_url"],
        "detail_url_format": "https://www.fss.or.kr/fss/bbs/B0000390/view.do?nttId={nttId}&menuNo=201193",
        "filters": {"cl1Cd (권역 탭)": {"A": "은행ㆍ중소서민", "B": "보험", "C": "금융투자"},
                    "cl2Cd (유형 탭, 보험)": {"B1": "생명보험 (화면 표시는 '금융투자기타')", "B2": "손해보험",
                                          "B3": "자동차보험", "B4": "보험기타"}},
        "total_all_categories": 817,  # 2026-11-24 전체 탭 '전체 817 건'
        "total_insurance": listing["site_total"],
        "insurance_scanned_at": listing["scanned_at"],
        "insurance_by_site_type": dict(Counter(i["type"] or "(빈칸)" for i in items)),
        "insurance_by_year": dict(sorted(Counter(i["registered_at"][:4] for i in items).items())),
        "insurance_attachments_per_post": dict(Counter(len(i["attachments"]) for i in items)),
        "insurance_attachment_ext": dict(exts),
        "detail_page": {
            "html_body": "div.n-dbdata 는 '…조정안을 첨부와 같이 등록합니다' 한두 줄 (일부는 결정일 포함). 결정문 전문은 첨부에만 있음",
            "info": "dl.bd-info: 작성자·등록일·조회수·담당부서·담당팀·문의·담당자·문의 이메일 (유형 없음 → 목록의 유형 사용)",
            "decision_date": "결정서 머리 표의 '조정일자'/'결정일자' (2026 서식은 회의안건 표지 '의결 년월일'도 있음). 등록일과 다름",
        },
    }


def skipped_view(row: dict) -> dict:
    """저장하지 않은 게시물 (본문을 뽑은 결정서 없음) 보고용."""
    skipped = row["meta"].get("skipped_attachments", [])
    reasons = sorted({s["reason"].split(" (")[0] for s in skipped}) or ["첨부 없음"]
    return {
        "source_key": row["source_key"], "source_url": row["source_url"], "skipped": True, "failed": False,
        "skip_reason": ", ".join(reasons), "title": row["title"], "registered_at": row["registered_at"],
        "product_type": row["product_type"], "files": [s["name"] for s in skipped],
        "skipped_attachments": skipped,
    }


def report_view(row: dict) -> dict:
    """보고용 요약 (본문 대신 섹션 이름·글자 수, 컬럼 앞부분 미리보기). split_rows() 뒤의 행 하나."""
    meta = row["meta"]
    judgment_chars = sum(s["chars"] for s in meta.get("sections", []) if s["key"] == "judgment")
    agenda_has_date = bool(row["dispute_issue"] and re.search(DATE, row["dispute_issue"]))
    problems = []
    if not judgment_chars:
        problems.append("위원회 판단 없음")
    if agenda_has_date:
        problems.append("안건명에 날짜 남음")
    if not meta.get("decision_date"):
        problems.append("결정일 못 찾음")
    return {
        "source_key": row["source_key"],
        "source_url": row["source_url"],
        "skipped": False,
        "failed": False,
        "problems": problems,
        "judgment_chars": judgment_chars,
        "agenda_has_date": agenda_has_date,
        "title": row["title"],
        "registered_at": row["registered_at"],
        "product_type": row["product_type"],
        "site_type": meta.get("site_type"),
        "decision_date": meta.get("decision_date"),
        "decision_date_source": meta.get("decision_date_source"),
        "decision_no": meta.get("decision_no"),
        "agenda": meta.get("agenda"),
        "extract_method": meta.get("extract_method"),
        "body_file_name": meta.get("body_file_name"),
        "sections": [{"name": s["name"], "key": s["key"], "chars": s["chars"]} for s in meta.get("sections", [])],
        "missing_sections": meta.get("missing_sections"),
        "skipped_attachments": meta.get("skipped_attachments", []),
        "columns": {c: {"chars": len(row[c]) if row[c] else 0, "preview": (row[c] or "")[:120] or None}
                    for c in ("dispute_issue", "summary", "complaint", "decision_reason", "raw_text")},
        "parse_notes": meta.get("parse_notes", []),
    }


# ---------------------------------------------------------------- 전체 수집 보고

FALLBACK_WARN_RATIO = 0.10


def full_report(run_file: Path, out_file: Path) -> dict:
    """collector.py --kind decision --report 결과(run_file) + DB 확인 → decision_full_report.json."""
    import json
    import statistics
    from collections import Counter

    run = json.loads(run_file.read_text(encoding="utf-8"))
    items = run["items"]
    rows = [i for i in items if not i.get("skipped") and not i.get("failed")]
    skipped = [i for i in items if i.get("skipped")]
    failed = [i for i in items if i.get("failed")]
    saved_posts = {i["source_key"].split("-")[0] for i in rows}

    methods = Counter(r["extract_method"] for r in rows)
    fallback = [r for r in rows if r["extract_method"] != "hwp_records"]
    fallback_ratio = len(fallback) / len(rows) if rows else 0.0
    judgment = sorted(r["judgment_chars"] for r in rows)

    skip_reasons = Counter()
    for s in skipped:
        for a in s["skipped_attachments"] or [{"reason": "첨부 없음"}]:
            skip_reasons[a["reason"].split(" (")[0]] += 1

    from collector import connect, load_env  # 순환 import 피하려고 여기서
    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")
    db_counts = dict(conn.execute("SELECT doc_kind, count(*) FROM dispute_case GROUP BY 1 ORDER BY 1").fetchall())
    db_categories = dict(conn.execute(
        "SELECT category, count(*) FROM dispute_case WHERE doc_kind = 'DECISION' GROUP BY 1").fetchall())
    conn.close()

    report = {}
    if fallback_ratio > FALLBACK_WARN_RATIO:
        report["WARNING"] = (f"hwp5html fallback 문서가 저장 행의 {fallback_ratio:.1%} ({len(fallback)}/{len(rows)}) "
                             f"— {FALLBACK_WARN_RATIO:.0%} 초과. hwp5html 은 본문 문단을 빠뜨릴 수 있음")
    report.update({
        "generated_from": run_file.name,
        "dry_run": run["dry_run"],
        "totals": {
            "posts": run["total"],
            "posts_saved": len(saved_posts),
            "rows_saved": len(rows),
            "posts_skipped": len(skipped),
            "posts_failed": len(failed),
            "skipped_by_reason (첨부 수)": dict(skip_reasons),
        },
        "db_check": {"dispute_case_by_doc_kind": db_counts, "decision_by_category": db_categories},
        "extract_method": {
            "counts": dict(methods),
            "fallback_ratio": round(fallback_ratio, 4),
            "fallback_documents": [{"source_key": r["source_key"], "decision_no": r["decision_no"],
                                    "file": r["body_file_name"], "judgment_chars": r["judgment_chars"],
                                    "reason": next((n for n in r["parse_notes"] if "hwp5html 사용" in n), None)}
                                   for r in fallback],
        },
        "rows_by_decision_year": dict(sorted(Counter(
            (r["decision_date"] or "")[:4] or "(결정일 없음)" for r in rows).items())),
        "rows_by_registered_year": dict(sorted(Counter(r["registered_at"][:4] for r in rows).items())),
        "rows_by_product_type": dict(Counter(r["product_type"] or "(빈칸)" for r in rows).most_common()),
        "judgment_chars": {
            "min": judgment[0] if judgment else None,
            "median": statistics.median(judgment) if judgment else None,
            "max": judgment[-1] if judgment else None,
            "p10": judgment[len(judgment) // 10] if judgment else None,
            "p90": judgment[len(judgment) * 9 // 10] if judgment else None,
            "under_300": [{"source_key": r["source_key"], "chars": r["judgment_chars"], "title": r["title"]}
                          for r in rows if r["judgment_chars"] < 300],
        },
        "no_decision_date": [{"source_key": r["source_key"], "decision_no": r["decision_no"],
                              "registered_at": r["registered_at"], "title": r["title"]}
                             for r in rows if not r["decision_date"]],
        "missing_sections": [{"source_key": r["source_key"], "decision_no": r["decision_no"],
                              "missing": r["missing_sections"], "title": r["title"]}
                             for r in rows if r["missing_sections"]],
        "missing_sections_count": dict(Counter(m for r in rows for m in r["missing_sections"] or [])),
        "agenda_has_date": [r["source_key"] for r in rows if r["agenda_has_date"]],
        "skipped_posts": [{"nttId": s["source_key"], "registered_at": s["registered_at"], "reason": s["skip_reason"],
                           "files": s["files"]} for s in skipped],
        "skipped_attachments_in_saved_posts": [{"source_key": r["source_key"], "skipped": r["skipped_attachments"]}
                                               for r in rows if r["skipped_attachments"]],
        "failed_posts": failed,
    })
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


def update_dispositions() -> dict:
    """DB 의 모든 DECISION 행에 meta.disposition 을 주문(summary) 기준으로 다시 쓴다 (다른 컬럼은 건드리지 않음)."""
    from collections import Counter
    from psycopg.types.json import Jsonb
    from collector import connect, load_env
    conn = connect(load_env())
    counts, changed = Counter(), 0
    with conn.transaction():
        for case_id, order, old in conn.execute(
                "SELECT id, summary, meta->>'disposition' FROM dispute_case WHERE doc_kind = 'DECISION'").fetchall():
            value = disposition(order)
            counts[value or "(주문 없음)"] += 1
            if value != old:
                changed += conn.execute("UPDATE dispute_case SET meta = coalesce(meta, '{}'::jsonb) || "
                                        "jsonb_build_object('disposition', %s::jsonb) WHERE id = %s",
                                        (Jsonb(value), case_id)).rowcount
    conn.close()
    return {"counts": dict(counts.most_common()), "changed": changed}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="결정례 전체 수집 보고서 (collector.py --report 결과로 작성)")
    parser.add_argument("--run", default=str(RAW_DIR / "_report" / "decision_run.json"))
    parser.add_argument("--out", default=str(RAW_DIR / "_report" / "decision_full_report.json"))
    parser.add_argument("--disposition", action="store_true",
                        help="보고서 대신 모든 DECISION 행의 meta.disposition 을 주문 기준으로 갱신")
    a = parser.parse_args()
    if a.disposition:
        print(update_dispositions())
        raise SystemExit(0)
    r = full_report(Path(a.run), Path(a.out))
    print({k: r[k] for k in ("totals", "extract_method") if k in r} | ({"WARNING": r["WARNING"]} if "WARNING" in r else {}))
