"""4-6. 가상고객 48명을 규칙으로 만든다. [C5]

배경 이야기(backstory)는 AI 생성이라 여기서는 비워 두고, 따로 생성해 채운다.
같은 사람 ID 는 언제 만들어도 같은 꼼꼼함·지식·성향·나이를 가진다 (시드 = 사람 ID 의 해시).
실행: python scripts/03_build_personas.py   (persona-pilot 폴더에서)
결과: data/personas.csv
"""

import csv
import hashlib
import random
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
OUT = ROOT / "data" / "personas.csv"

FIELDS = ["person_id", "age_group", "age", "path", "band", "score", "diligence",
          "knowledge", "disposition", "seed", "backstory"]


def seed_of(person_id: str) -> int:
    return int(hashlib.sha256(person_id.encode("utf-8")).hexdigest()[:12], 16)


def band_of(score: float, bands: list[dict]) -> dict:
    for b in bands:  # 위에서부터 min 이상이면 그 구간
        if score >= b["min"]:
            return b
    raise ValueError(score)


def quota(total: int, ratios: dict[str, float]) -> dict[str, int]:
    """비율을 인원수로 바꾼다 (최대 나머지 방식). 예: 16명 × 15/35/50% → 2/6/8명"""
    raw = {k: total * v for k, v in ratios.items()}
    counts = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[: total - sum(counts.values())]:
        counts[k] += 1
    return counts


def assign_group(age_group: str, band: dict, paths: list[str], per_path: int) -> dict[str, tuple[str, str]]:
    """연령대 안에서 지식·성향을 '비율대로 나눠' 배정한다 (사용자 결정 2026-11-26, 명세서의 확률 추첨 대신).

    - 지식: 연령대 인원 × 구간 비율만큼 정확히 배정. 경로마다 고르게 돌아가도록 차례로 나눈 뒤,
      경로 안에서 누가 받을지는 연령대 시드로 섞는다.
    - 성향: 경로마다 낙관 절반, 신중 절반.
    결과: {person_id: (knowledge, disposition)}
    """
    rng = random.Random(seed_of(f"group:{age_group}"))
    counts = quota(len(paths) * per_path, band["knowledge"])
    levels = [lv for lv in ("하", "중", "상") for _ in range(counts[lv])]
    by_path: dict[str, list[str]] = {p: [] for p in paths}
    for i, lv in enumerate(levels):  # 차례로 돌려 담아 경로마다 비슷한 구성이 되게 한다
        by_path[paths[i % len(paths)]].append(lv)

    result = {}
    n = 0
    for p in paths:
        kn = by_path[p][:]
        rng.shuffle(kn)
        disp = ["optimistic"] * (per_path // 2) + ["cautious"] * (per_path - per_path // 2)
        rng.shuffle(disp)
        for k, d in zip(kn, disp):
            n += 1
            result[f"{age_group}-{n:02d}"] = (k, d)
    return result


def make_person(person_id: str, age_group: str, path_id: str, age_rules: dict,
                knowledge: str, disposition: str) -> dict:
    score = age_rules["scores"][age_group]
    band = dict(band_of(score, age_rules["bands"]))
    if age_group in age_rules.get("diligence_by_age", {}):
        band["diligence_mean"] = age_rules["diligence_by_age"][age_group]
    seed = seed_of(person_id)
    rng = random.Random(seed)
    # 사람마다 추첨하는 것: 꼼꼼함 → 나이 (순서 고정)
    lo, hi = band["diligence_mean"] - band["diligence_range"], band["diligence_mean"] + band["diligence_range"]
    diligence = min(1.0, max(0.0, rng.uniform(lo, hi)))
    age = rng.randint(*age_rules["age_ranges"][age_group])
    return {
        "person_id": person_id, "age_group": age_group, "age": age, "path": path_id,
        "band": band["name"], "score": score, "diligence": round(diligence, 3),
        "knowledge": knowledge, "disposition": disposition, "seed": seed, "backstory": "",
    }


def main() -> int:
    settings = yaml.safe_load((CONFIG / "settings.yaml").read_text(encoding="utf-8"))
    age_rules = yaml.safe_load((CONFIG / "age_rules.yaml").read_text(encoding="utf-8"))
    per_path = settings["people_per_path"]

    # 이미 검토한 배경 이야기는 다시 만들어도 남긴다
    old = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8-sig") as f:
            old = {r["person_id"]: r["backstory"] for r in csv.DictReader(f)}

    people = []
    path_ids = [p["id"] for p in settings["paths"]]
    if settings.get("assignment") == "balanced":
        # 연령대 × 경로 × 용어 이해 단계 칸마다 같은 인원, 칸 안에서 성향 반반 (2026-11-27)
        per_cell = settings["people_per_cell"]
        disp = ["optimistic", "cautious"] * (per_cell // 2) + ["optimistic"] * (per_cell % 2)
        for age_group in settings["age_groups"]:
            n = 0
            for path_id in path_ids:
                for level in ("상", "중", "하"):
                    for d in disp:
                        n += 1
                        pid = f"{age_group}-{n:02d}"
                        p = make_person(pid, age_group, path_id, age_rules, level, d)
                        p["backstory"] = old.get(pid, "")
                        people.append(p)
        path_ids = []  # 아래 quota 방식은 건너뜀
    for age_group in (settings["age_groups"] if path_ids else []):
        band = dict(band_of(age_rules["scores"][age_group], age_rules["bands"]))
        # 연령대별 실측 비율(보험연구원 2019)이 있으면 구간 가정값 대신 쓴다
        if age_group in age_rules.get("knowledge_by_age", {}):
            band["knowledge"] = age_rules["knowledge_by_age"][age_group]
        # 꼼꼼함 평균도 보험 전용 행동 자료(보험연구원 2019 '가입 전 정보 탐색')가 있으면 그 값을 쓴다
        if age_group in age_rules.get("diligence_by_age", {}):
            band["diligence_mean"] = age_rules["diligence_by_age"][age_group]
        assigned = assign_group(age_group, band, path_ids, per_path)
        n = 0
        for path_id in path_ids:  # 경로 순서대로 4명씩: 01~04 약관 정독, 05~08 해당 조항만 ...
            for _ in range(per_path):
                n += 1
                pid = f"{age_group}-{n:02d}"
                p = make_person(pid, age_group, path_id, age_rules, *assigned[pid])
                p["backstory"] = old.get(p["person_id"], "")
                people.append(p)

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:  # 엑셀에서 한글이 깨지지 않게 BOM
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(people)

    print(f"{len(people)}명 → {OUT.relative_to(ROOT)}")
    for g in settings["age_groups"]:
        grp = [p for p in people if p["age_group"] == g]
        dil = [p["diligence"] for p in grp]
        print(f"{g} ({grp[0]['band']}, {grp[0]['score']}점): 꼼꼼함 평균 {sum(dil)/len(dil):.3f} "
              f"[{min(dil):.2f}~{max(dil):.2f}], 지식 {dict(Counter(p['knowledge'] for p in grp))}, "
              f"성향 {dict(Counter(p['disposition'] for p in grp))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
