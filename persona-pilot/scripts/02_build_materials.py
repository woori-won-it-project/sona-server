"""4-4. 조항별 정보 경로 글(약관 정독 / 해당 조항만 / 설명서만)을 만든다. [C3]

설계사 화법(agent_talk)은 AI 생성이라 여기서는 비워 두고, 05 전에 따로 생성해 고정한다.
실행: python scripts/02_build_materials.py   (persona-pilot 폴더에서, 01 실행 후)
결과: data/path_texts.json
  {clause_id: {path_id: {"text": str, "sources": [str]}}}
"""

import json
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MAIN_PAGES = range(25, 54)  # 주계약 약관 본문 (PDF 쪽 번호)
HEADER = "무배당엔젤New 독특한암치료보험(갱신형) 약관"
FOOTER = re.compile(r"^\d+\s+TONGYANG LIFE INSURANCE$")
ARTICLE = re.compile(r"제\s*(\d+)\s*조\s*【([^】]+)】")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
# 이 표시로 시작하는 줄은 앞줄에 붙이지 않고 새 줄로 둔다
NEW_LINE = re.compile(r"^(제\s*\d+\s*조\s*【|[①-⑮]|\d+\.\s|[가-하]\.\s|\(|-\s|※|제\d+관)")


# ---------- 약관 ----------
def load_main_terms() -> str:
    pages = json.loads((DATA / "extracted" / "terms.json").read_text(encoding="utf-8"))
    lines = []
    for p in pages:
        if p["page"] not in MAIN_PAGES:
            continue
        for raw in p["text"].splitlines():
            line = raw.strip()
            if not line or line.startswith(HEADER) or FOOTER.match(line):
                continue
            lines.append(line)
    # PDF 의 줄바꿈을 없애고 문단 단위로 이어 붙인다
    merged: list[str] = []
    for line in lines:
        # '(' 로 시작해도 앞 문장이 끝나지 않았으면 줄바꿈으로 잘린 것이므로 이어 붙인다
        # 단, 한 줄 전체가 "(제목)" 이면 설명 상자의 제목이므로 새 줄로 둔다
        is_box_title = re.fullmatch(r"\([^()]*\)", line) is not None
        cut_mid_sentence = (line.startswith("(") and not is_box_title and merged
                            and not merged[-1].endswith((".", ")", "】")))
        if merged and (cut_mid_sentence or not NEW_LINE.match(line)):
            merged[-1] += " " + line
        else:
            merged.append(line)
    return "\n".join(merged)


def split_articles(text: str) -> dict[int, str]:
    matches = list(ARTICLE.finditer(text))
    articles = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        num = int(m.group(1))
        if num not in articles:  # 본문에서 처음 나온 것만
            articles[num] = text[m.start() : end].strip()
    return articles


def heading(article: str) -> str:
    return article.splitlines()[0]


# 약관 안 '지급 예시' 표의 줄 (① 보험금 지급 : ...). 항으로 보지 않는다
EXAMPLE_ROW = re.compile(rf"^[{CIRCLED}]\s*보험금\s*(미)?지급\s*:|[{CIRCLED}].*[{CIRCLED}]")
EXAMPLE_TITLE = re.compile(r"\s*보험금\s*\(.*?\)\s*지급\s*예시.*$")


def paragraphs(article: str, nums: list[int]) -> str:
    """조에서 지정한 항(①②...)만 뽑는다. 조 제목은 맨 앞에 붙인다.

    항은 ①부터 차례로 나온다고 보고 순서대로 찾는다. 항 뒤의 '지급 예시' 표는 버린다.
    """
    paras: dict[int, list[str]] = {}
    expected, current, in_example = 1, None, False
    for line in article.splitlines()[1:]:
        if expected <= len(CIRCLED) and line.startswith(CIRCLED[expected - 1]) and not EXAMPLE_ROW.search(line):
            current, in_example = expected, False
            paras[current] = []
            expected += 1
        elif current is None or in_example or line.startswith("- ") or EXAMPLE_ROW.search(line):
            in_example = current is not None
            continue
        if EXAMPLE_TITLE.search(line):
            line, in_example = EXAMPLE_TITLE.sub("", line), True
        paras[current].append(line)
    missing = [n for n in nums if n not in paras]
    if missing:
        raise ValueError(f"항을 찾지 못함: {heading(article)} {missing}")
    return "\n".join([heading(article)] + ["\n".join(paras[n]) for n in nums])


def lines_starting(article: str, prefixes: tuple[str, ...]) -> list[str]:
    found = [l for l in article.splitlines() if l.startswith(prefixes)]
    if len(found) != len(prefixes):
        raise ValueError(f"줄을 찾지 못함: {heading(article)} {prefixes}")
    return found


# ---------- 상품설명서 ----------
def guide_blocks() -> dict[int, list[str]]:
    blocks = {}
    with pymupdf.open(DATA / "raw" / "guide.pdf") as doc:
        for i, page in enumerate(doc, start=1):
            blocks[i] = [b[4].replace("\x07", "").strip() for b in page.get_text("blocks")]
    return blocks


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def guide_pick(blocks: dict[int, list[str]], page: int, starts: list[str], joiner: str = "\n") -> str:
    """해당 쪽에서 지정한 글로 시작하는 블록을 순서대로 이어 붙인다 (2단 편집이라 블록 단위로 뽑음).

    joiner: 블록 사이 연결. 한 문장이 두 블록에 걸쳐 잘린 경우는 " " 로 잇는다.
    """
    out = []
    for s in starts:
        found = [b for b in blocks[page] if b.startswith(s)]
        if not found:
            raise ValueError(f"설명서 {page}쪽에서 찾지 못함: {s}")
        block = found[0]
        # "※ 청약철회 청구제도\n본문..." 처럼 ※ 로 시작하는 블록은 첫 줄이 제목이므로 줄을 나눠 둔다.
        # 그 밖의 블록 안 줄바꿈은 PDF 편집 때문에 생긴 것이므로 없앤다
        if block.startswith("※") and "\n" in block:
            title, body = block.split("\n", 1)
            out.append(clean(title) + "\n" + clean(body))
        else:
            out.append(clean(block))
    return joiner.join(out)


# 설명서 3쪽 보장내용 표(암주요치료비 칸). 표라서 칸 순서대로 이어 적는다 (문구는 원문 그대로)
GUIDE_D1_TABLE = (
    "[보장내용 - 암주요치료비, 기준: 보험가입금액 1,000만원] "
    "지급사유: 피보험자가 보험기간 중 암보장개시일 이후에 암, 기타피부암 또는 갑상선암으로 "
    "최초 진단확정 되고 “보험금 지급기간” 이내에 암, 기타피부암 또는 갑상선암의 치료를 직접적인 "
    "목적으로 “암 주요치료”를 받은 경우 [다만, 최초 암진단확정일부터 최대 10년간, 연간 1회에 한함 "
    "(최대 10회 지급)] "
    "지급금액: 최초계약의 경우 계약일로부터 1년 경과시점 이후에 최초 진단확정 시 또는 갱신계약의 "
    "경우 보험금 지급기간동안 1,000만원. "
    "최초계약의 경우 계약일로부터 1년 경과시점 전일 이전에 최초 진단확정 시 보험금 지급기간동안 500만원."
)


def build() -> dict:
    arts = split_articles(load_main_terms())
    a = arts.__getitem__
    g = guide_blocks()

    d1_defs = "\n".join(
        [heading(a(2))]
        + lines_starting(a(2), ("2. 지급사유 관련 용어",))
        + lines_starting(a(2), ("가. 최초 암진단확정일", "나. 보험금 지급기간", "다. 연간"))
    )
    art11 = a(11)
    art11_item1 = "\n".join(art11.splitlines()[:1] + lines_starting(art11, ("1. 피보험자가",)))

    return {
        "D1": {
            "full_terms": {
                "text": "\n".join([d1_defs, art11, paragraphs(a(12), [3, 4, 9, 10]), paragraphs(a(31), [5])]),
                "sources": ["제2조 제2호 가~다목", "제11조", "제12조 제3·4·9·10항", "제31조 제5항"],
            },
            "clause_only": {"text": art11, "sources": ["제11조"]},
            "guide_only": {
                "text": "\n".join([GUIDE_D1_TABLE, guide_pick(g, 3, ["❶ 피보험자가", "차년도별 지급금액은"], joiner=" ")]),
                "sources": ["설명서 3쪽 보장내용 표(암주요치료비 칸)", "설명서 3쪽 ❶~⓮ 안내문"],
            },
            "agent_talk": None,
        },
        "D2": {
            "full_terms": {
                "text": "\n".join([a(6), a(7), art11_item1]),
                "sources": ["제6조", "제7조", "제11조 제1호"],
            },
            "clause_only": {"text": a(7), "sources": ["제7조"]},
            "guide_only": {
                "text": "\n".join([
                    guide_pick(g, 2, ["암주요치료비란 무엇인가요?", "\"암 주요치료\"는"]),
                    guide_pick(g, 2, ["암주요치료에 포함되지 않는 항목은"]),
                    guide_pick(g, 2, ["❶ 식이요법", "갑상선암의 증식 억제를"], joiner=" "),
                ]),
                "sources": ["설명서 2쪽 Q&A '암주요치료비란 무엇인가요?'", "설명서 2쪽 Q&A '포함되지 않는 항목'"],
            },
            "agent_talk": None,
        },
        "C1": {
            "full_terms": {"text": a(24), "sources": ["제24조 전체"]},
            "clause_only": {"text": paragraphs(a(24), [1, 2]), "sources": ["제24조 제1·2항"]},
            "guide_only": {
                "text": guide_pick(g, 4, ["※ 청약철회 청구제도"]),
                "sources": ["설명서 4쪽 '청약철회 청구제도'"],
            },
            "agent_talk": None,
        },
        "C2": {
            "full_terms": {"text": "\n".join([a(32), a(34)]), "sources": ["제32조", "제34조 전체"]},
            "clause_only": {"text": paragraphs(a(34), [1]), "sources": ["제34조 제1항"]},
            "guide_only": {
                "text": guide_pick(g, 4, ["※ 보험계약 해지에 관한 안내"]),
                "sources": ["설명서 4쪽 '보험계약 해지에 관한 안내'"],
            },
            "agent_talk": None,
        },
    }


def box(article: str, title: str) -> str:
    """조 안의 (제목) 설명 상자 하나를 뽑는다. 예: (호르몬 관련 치료제) ..."""
    found = [l for l in article.splitlines() if l.startswith(f"({title})")]
    if not found:
        raise ValueError(f"설명 상자를 찾지 못함: {heading(article)} ({title})")
    return found[0][len(title) + 2 :].strip()


def build_glossary() -> dict:
    """4-5. 용어 사전 [C4]. '상'은 약관 문구 그대로. '중'·'하'는 AI 생성 후 사람 검토라 비워 둔다."""
    arts = split_articles(load_main_terms())
    a = arts.__getitem__

    def after_label(line: str) -> str:  # "가. 최초 암진단확정일: ..." -> ": " 뒤
        return line.split(":", 1)[1].strip()

    a2 = a(2)
    one = lambda prefix: after_label(lines_starting(a2, (prefix,))[0])  # noqa: E731
    art7_p1 = paragraphs(a(7), [1]).split("\n", 1)[1].replace("\n", " ")
    return {
        "최초계약": {"상": one("바. 최초계약 및 갱신계약"), "source": "제2조 제1호 바목", "questions": ["Q1", "Q2"]},
        "암보장개시일": {"상": paragraphs(a(31), [5]).split("\n", 1)[1][2:], "source": "제31조 제5항", "questions": ["Q1"]},
        "최초 암진단확정일": {"상": one("가. 최초 암진단확정일"), "source": "제2조 제2호 가목", "questions": ["Q1"]},
        "보험금 지급기간": {"상": one("나. 보험금 지급기간"), "source": "제2조 제2호 나목", "questions": ["Q1"]},
        "암 주요치료": {"상": art7_p1[2:], "source": "제7조 제1항", "questions": ["Q1", "Q2"]},
        "항암약물치료": {"상": a(6).split("】", 1)[1].strip(), "source": "제6조", "questions": ["Q1", "Q2"]},
        "호르몬 관련 치료제": {"상": box(a(7), "호르몬 관련 치료제"), "source": "제7조 제2항 설명 상자", "questions": ["Q2"]},
        # '청약철회'는 뺌 (2026-11-26 사용자 결정): 약관에 정의 조항이 없어 '상'에 제24조 본문을 넣었더니
        # "15일 이내"라는 Q3 정답이 용어 칸으로 새어, 무엇을 읽었든 지식 상·중이면 정답을 받게 됨
        "보험증권": {"상": one("다. 보험증권"), "source": "제2조 제1호 다목", "questions": ["Q3"]},
        "납입최고(독촉)": {"상": box(a(34), "납입최고(독촉)"), "source": "제34조 설명 상자", "questions": ["Q4"]},
    }


def save_glossary() -> None:
    out = DATA / "glossary.json"
    terms = build_glossary()
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    for name, t in terms.items():
        # 검토를 마친 '중'·'하'는 다시 실행해도 지우지 않는다
        t["중"] = old.get(name, {}).get("중")
        t["하"] = old.get(name, {}).get("하")
    out.write_text(json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"glossary: {len(terms)}개 용어")


def main() -> int:
    save_glossary()
    result = build()
    out = DATA / "path_texts.json"
    # 이미 생성·고정된 설계사 화법이 있으면 지우지 않는다
    if out.exists():
        old = json.loads(out.read_text(encoding="utf-8"))
        for cid, paths in old.items():
            if paths.get("agent_talk"):
                result[cid]["agent_talk"] = paths["agent_talk"]
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for cid, paths in result.items():
        print(cid, {k: (len(v["text"]) if v else "-") for k, v in paths.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
