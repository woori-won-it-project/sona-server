"""동양생명 RAG 5문항, 3×2×2 조건, 조건별 6회. 평가 기준은 미열람 60% 이하."""
import itertools
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import common_llm as llm

data = llm.ROOT / "results_valid/dy_rag"
out = data / "memo_factorial_1"
out.mkdir(exist_ok=True)
llm.LOG = out / "calls.jsonl"
llm.load_dotenv()
import os
os.environ["OPENAI_MODEL"] = "gpt-6-luna"
facts = json.loads((data / "facts.json").read_text(encoding="utf-8"))
options = {r["fact_id"]: r["options"] for r in json.loads((data / "options.json").read_text(encoding="utf-8"))}
doc = (data / "document.txt").read_text(encoding="utf-8")
old = "※ 최초계약의 경우 계약일로부터 1년 경과시점 전일 이전에 암, 기타피부암 또는\n갑상선암으로 최초 진단확정된 경우 보험금 지급기간동안 50%를 지급"
new = "※ 최초계약에서 계약일부터 1년이 지나기 전에 암·기타피부암·갑상선암으로 처음 진단이 확정되면, 감액 여부는 그 진단일로 결정합니다. 치료를 계약 1년 뒤에 받아도 보험금 지급기간 내내 각 차년도 지급액의 절반(50%)을 지급합니다."
assert doc.count(old) == 2
cards = {"high":"보험 용어를 일상적으로 접하는 사람", "mid":"일반적인 보험 용어 몇 가지에 익숙한 사람", "low":"보험 용어를 처음 접하는 사람"}

def ask(prompt, purpose, schema=None):
    return llm.call_openai(prompt, purpose, json_schema=schema, thinking="disabled", max_tokens=600)["text"]

def run(job, *, require_units=False):
    level, check, version, rep = job
    name = f"{level}-{check}-{version}-{rep}"
    destination = data / "memo_required_units" if require_units else out
    destination.mkdir(exist_ok=True)
    path = destination / (name + ".json")
    if path.exists() and not require_units:
        return
    memo = ""
    if level != "empty":
        rule = "정리한 뒤 원문에서 기간·예외 조건을 한 번 더 확인하세요." if check else ""
        memo = ask(f"당신은 {cards[level]}입니다. 아래 상품설명서를 읽고 나중에 스스로 보려고 300자 이내 한국어 메모를 작성하세요. {rule} 메모만 출력하세요.\n" + (doc if version == "orig" else doc.replace(old,new)), name+"_memo")[:300]
    qs, keys, answers = [], {}, {}
    for i, f in enumerate(facts):
        q = f["fact_id"]
        opts = list(itertools.permutations(options[q]))[(rep+i)%6]
        keys[q] = next(k for k,o in zip("ABC",opts) if o["correct"])
        if require_units and not all(re.search(unit, memo) for unit in f["units"]):
            answers[q] = "모르겠다"
            continue
        qs.append(q+" "+f["question"]+"\n"+"\n".join(k+" "+o["text"] for k,o in zip("ABC",opts)))
    if qs:
        pending = [q for q in keys if q not in answers]
        schema = {"type":"object","properties":{q:{"type":"string","enum":["A","B","C"]} for q in pending},"required":pending,"additionalProperties":False}
        answers.update(json.loads(ask("당신의 메모로 다음 질문에 답하세요. 확실하지 않아도 가장 그럴듯한 보기를 고르세요.\n메모: "+(memo or "(없음)")+"\n"+"\n".join(qs), name+"_answer",schema)))
    path.write_text(json.dumps(dict(level=level,check=check,version=version,rep=rep,memo=memo,answers=answers,correct={q:answers[q]==k for q,k in keys.items()}),ensure_ascii=False),encoding="utf-8")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-empty", action="store_true")
    if parser.parse_args().verify_empty:
        for rep in range(6):
            run(("empty", 0, "none", rep), require_units=True)
        raise SystemExit
    jobs = [("empty",0,"none",i) for i in range(6)] + list(itertools.product(cards,[0,1],["orig","edit"],range(6)))
    with ThreadPoolExecutor(5) as pool:
        list(pool.map(run,jobs))
