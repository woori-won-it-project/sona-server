"""AI 로 만드는 자료를 생성해 파일에 고정한다. 한 번 만들고 사람이 검토한 뒤에는 다시 만들지 않는다.

실행 (persona-pilot 폴더에서, ANTHROPIC_API_KEY 환경 변수 필요):
  python scripts/02b_generate_ai.py agent_talk   # 설계사 화법 4개   → data/path_texts.json [C3]
  python scripts/02b_generate_ai.py glossary     # 용어 '중'·'하' 20개 → data/glossary.json  [C4]
  python scripts/02b_generate_ai.py backstory    # 배경 이야기 48개   → data/personas.csv   [C5]
이미 채워진 항목은 건너뛴다. 다시 만들려면 --force.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_llm import call_with_retry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PROMPTS = yaml.safe_load((ROOT / "config" / "gen_prompts.yaml").read_text(encoding="utf-8"))
MAX_TRIES = 3


def generate_checked(prompt: str, purpose: str, banned: list[str]) -> tuple[str, list[str]]:
    """생성 후 금지 표현이 있으면 그 표현을 알려주고 다시 생성한다. (결과, 걸렸던 표현 목록)"""
    hits_all: list[str] = []
    p = prompt
    for _ in range(MAX_TRIES):
        r = call_with_retry(p, purpose)
        if r["stop_reason"] != "end_turn":
            raise RuntimeError(f"{purpose}: 응답이 끝나지 않음 (stop_reason={r['stop_reason']})")
        text = r["text"].strip().strip('"“”').strip()  # 문장 전체를 감싼 따옴표는 뗀다
        hits = [w for w in banned if w in text]
        if not hits:
            return text, hits_all
        hits_all += hits
        p = prompt + f"\n\n(주의: 이전 답에 쓰면 안 되는 표현 {hits} 이 들어갔습니다. 빼고 다시 쓰세요.)"
    raise RuntimeError(f"{purpose}: {MAX_TRIES}회 모두 금지 표현 포함 {hits_all}")


def agent_talk(force: bool) -> None:
    path = DATA / "path_texts.json"
    texts = json.loads(path.read_text(encoding="utf-8"))
    clauses = {c["clause_id"]: c for c in json.loads((DATA / "clauses.json").read_text(encoding="utf-8"))}
    for cid, paths in texts.items():
        if paths.get("agent_talk") and not force:
            continue
        prompt = PROMPTS["agent_talk"].format(topic=clauses[cid]["topic"], clause_text=paths["clause_only"]["text"])
        text, hits = generate_checked(prompt, f"agent_talk:{cid}", PROMPTS["agent_talk_banned"])
        paths["agent_talk"] = {"text": text, "sources": ["AI 생성 (gen_prompts.yaml agent_talk)"],
                               "generated": True, "banned_hits": hits}
        path.write_text(json.dumps(texts, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{cid}] {text}")


def glossary(force: bool) -> None:
    path = DATA / "glossary.json"
    terms = json.loads(path.read_text(encoding="utf-8"))
    for name, t in terms.items():
        if not t.get("중") or force:
            t["중"], _ = generate_checked(PROMPTS["glossary_mid"].format(term=name, exact=t["상"]),
                                          f"glossary_mid:{name}", [])
        if not t.get("하") or force:
            t["하"], t["하_banned_hits"] = generate_checked(PROMPTS["glossary_low"].format(term=name, exact=t["상"]),
                                                          f"glossary_low:{name}", PROMPTS["glossary_low_banned"])
        path.write_text(json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"- {name}\n  중: {t['중']}\n  하: {t['하']}")


def backstory(force: bool) -> None:
    path = DATA / "personas.csv"
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())
    if "backstory_banned_hits" not in fields:
        fields.append("backstory_banned_hits")
    for r in rows:
        if r.get("backstory") and not force:
            continue
        prompt = PROMPTS["backstory"].format(age=r["age"], person_id=r["person_id"])
        r["backstory"], hits = generate_checked(prompt, f"backstory:{r['person_id']}", PROMPTS["backstory_banned"])
        r["backstory_banned_hits"] = ";".join(hits)
        with path.open("w", encoding="utf-8-sig", newline="") as f:  # 한 명씩 저장 (중간에 멈춰도 남게)
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"{r['person_id']}: {r['backstory']}" + (f"  (재생성: {hits})" if hits else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["agent_talk", "glossary", "backstory"])
    ap.add_argument("--force", action="store_true", help="이미 있는 것도 다시 생성")
    args = ap.parse_args()
    {"agent_talk": agent_talk, "glossary": glossary, "backstory": backstory}[args.kind](args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
