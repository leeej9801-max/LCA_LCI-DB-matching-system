"""E3 Colab 노트북이 업로드해 쓰는 순수 함수 모듈. torch·transformers·langgraph 를 import 하지 않는다(로컬 시험용).

노트북(notebooks/E3_rerank_judge.ipynb)은 내보내기 파일(app.evaluation.export_candidates 가 만든 JSON)만 받고, 결과를
docs/LCA/spec/external-result.schema.json 형식으로 만든다. 이 모듈은 정답 값(expected·a_accept·s_accept·label_type)을
읽지도 다루지도 않는다. 정확도는 계산하지 않는다(PC 의 app.evaluation.run 에서만).
"""
import hashlib
import json
from pathlib import Path

STRUCTURES = ("S1", "S2", "S3")
FLIP_MAX = 0.05  # 5회 반복에서 행별 결정이 하나라도 달라진 행의 비율이 이를 넘는 구조는 탈락(_UNSTABLE)
REASON_MAX = 200
TOP_JUDGE = 10  # 판정에 넘기는 R 결과 상위 개수
# 질의 역할(모델 출력) → 내보낸 후보의 role 표기(app.roles.LABEL 의 한글 값). 합본은 어느 역할에서도 빼지 않는다
ROLE_LABELS = {"소재": ("소재",), "공정": ("공정",), "에너지": ("에너지·유틸리티",), "수송": ("수송",), "폐기": ("폐기·재활용",)}
COMBINED_LABELS = ("합본", "소재+공정 합본")
UNKNOWN_ROLE = "모름"

# 프롬프트 원문 전체. 구조·단계별 템플릿이고 {query}·{candidates} 등은 build_judge_prompt 가 채운다.
# 바꾸면 prompt_sha256 이 바뀐다(캐시 키에도 들어가 옛 캐시를 쓰지 않는다)
PROMPTS = {
    "S1": {
        "judge": (
            "당신은 국가 LCI 데이터베이스에서 BOM 한 줄에 맞는 데이터셋을 고르는 보조자입니다.\n"
            "아래 질의에 가장 알맞은 후보를 하나 고르세요. 재질·공정·형태가 다르면 맞지 않는 후보입니다. "
            "맞는 후보가 하나도 없으면 none 이라고 답하세요. 추측하지 마세요.\n\n"
            "질의: {query}\n\n후보:\n{candidates}\n\n"
            "답은 첫 줄에 정확히 `pick <id>` 또는 `none` 만 쓰세요. <id> 는 위 후보의 id 그대로입니다. 둘째 줄부터 짧은 이유를 쓰세요."),
    },
    "S2": {
        "role": (
            "BOM 한 줄이 국가 LCI 데이터베이스의 어떤 종류를 찾는 것인지 분류하세요.\n"
            "종류: 소재(원료·재료·부품 소재) / 공정(가공·성형·용접 등) / 에너지(전력·연료·용수) / 수송 / 폐기(소각·매립·재활용) / 모름\n\n"
            "질의: {query}\n\n답은 첫 줄에 종류 한 단어(소재, 공정, 에너지, 수송, 폐기, 모름 중 하나)만 쓰세요."),
        "judge": (
            "당신은 국가 LCI 데이터베이스에서 BOM 한 줄에 맞는 데이터셋을 고르는 보조자입니다.\n"
            "질의는 '{role}' 종류로 분류되었고, 아래 후보는 그 종류(와 소재·공정이 합쳐진 합본)만 남긴 것입니다. "
            "재질·공정·형태가 다르면 맞지 않는 후보입니다. 맞는 후보가 하나도 없으면 none 이라고 답하세요. 추측하지 마세요.\n\n"
            "질의: {query}\n\n후보:\n{candidates}\n\n"
            "답은 첫 줄에 정확히 `pick <id>` 또는 `none` 만 쓰세요. <id> 는 위 후보의 id 그대로입니다. 둘째 줄부터 짧은 이유를 쓰세요."),
    },
    "S3": {
        "judge": (
            "당신은 국가 LCI 데이터베이스에서 BOM 한 줄에 맞는 데이터셋을 고르는 보조자입니다.\n"
            "아래 질의에 가장 알맞은 후보를 하나 고르세요. 재질·공정·형태가 다르면 맞지 않는 후보입니다. "
            "맞는 후보가 하나도 없으면 none 이라고 답하세요. 추측하지 마세요.\n\n"
            "질의: {query}\n\n후보:\n{candidates}\n\n"
            "답은 첫 줄에 정확히 `pick <id>` 또는 `none` 만 쓰세요. <id> 는 위 후보의 id 그대로입니다. 둘째 줄부터 짧은 이유를 쓰세요."),
        "verify": (
            "BOM 질의와 고른 데이터셋이 서로 모순되는지 검증하세요. 질의와 데이터셋의 재질, 공정, 형태 중 하나라도 "
            "서로 어긋나면 '예', 어긋나지 않거나 알 수 없으면 '아니오'입니다.\n\n"
            "질의: {query}\n고른 데이터셋: {picked}\n\n답은 첫 줄에 `예` 또는 `아니오` 한 단어만 쓰세요."),
    },
}


# ---------- 입출력 ----------
def load_export(path):
    """(내보내기 dict, 파일 바이트 sha256). 정답 관련 키가 들어 있으면 거부한다(내보내기는 정답을 담지 않는다)."""
    data = Path(path).read_bytes()
    doc = json.loads(data.decode("utf-8"))
    bad = _forbidden_keys(doc)
    if bad:
        raise ValueError(f"내보내기 파일에 정답 관련 키가 있습니다: {sorted(bad)}")
    return doc, hashlib.sha256(data).hexdigest()


def _forbidden_keys(x, found=None):
    # export_candidates.FORBIDDEN 과 같은 집합(이 모듈은 앱 코드를 import 하지 않는다 — Colab 에는 이 파일만 올린다)
    names = {"expected", "expected_dataset_id", "expected_name", "expected_role", "a_accept", "s_accept", "label_type", "note", "is_no_match",
             "hard_pair_group", "decided_by"}
    found = set() if found is None else found
    if isinstance(x, dict):
        found |= set(x) & names
        for v in x.values():
            _forbidden_keys(v, found)
    elif isinstance(x, list):
        for v in x:
            _forbidden_keys(v, found)
    return found


def candidate_text(c):
    """재순위 입력의 후보 문장. org·year 는 넣지 않는다. 없는 값은 빈 칸(지어내지 않는다)."""
    return " | ".join("" if c.get(k) is None else str(c[k]) for k in ("name_ko", "name_en", "category", "role"))


def query_text(row):
    out = row["query"]
    if row.get("spec"):
        out += " / " + row["spec"]
    if row.get("unit"):
        out += " / 단위 " + row["unit"]
    return out


def permute(cands, seed):
    """후보 순서 섞기(일관성 검사용). 결정적이고 파이썬 버전·해시 시드와 무관하다: (seed, dataset_id) 의 sha256 순으로 정렬."""
    return sorted(cands, key=lambda c: hashlib.sha256(f"{seed}:{c['dataset_id']}".encode("utf-8")).hexdigest())


def rank_by_scores(cands, scores):
    """점수 내림차순 ranking [[dataset_id, score], ...]. 동점은 내보낸 순서(rank) 유지."""
    if len(cands) != len(scores):
        raise ValueError(f"후보 {len(cands)}개에 점수 {len(scores)}개")
    order = sorted(range(len(cands)), key=lambda i: (-scores[i], i))
    return [[cands[i]["dataset_id"], float(scores[i])] for i in order]


def rank_with_pick(ranking, picked):
    """판정 결과 ranking: picked 를 1위로 올리고 나머지는 원래(R) 순서. 점수는 R 점수 그대로 둔다(순서만 바뀜). picked 가 None 이면 그대로."""
    if picked is None:
        return [list(x) for x in ranking]
    if picked not in [d for d, _ in ranking]:
        raise ValueError(f"{picked} 가 ranking 에 없습니다")
    return [list(x) for x in ranking if x[0] == picked] + [list(x) for x in ranking if x[0] != picked]


# ---------- 프롬프트 ----------
def prompt_sha256(structure):
    """구조의 프롬프트 원문 전체(단계 이름과 템플릿, 단계 순서 고정)의 sha256."""
    if structure not in PROMPTS:
        raise ValueError(f"모르는 구조: {structure}")
    blob = json.dumps(PROMPTS[structure], ensure_ascii=False, sort_keys=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def format_candidates(cands):
    return "\n".join(f"- {c['dataset_id']}: {candidate_text(c)}" for c in cands)


def build_judge_prompt(row, cands, structure, step, **fields):
    """프롬프트 문자열. step: S1 judge / S2 role·judge / S3 judge·verify. judge 는 cands(보여 줄 순서대로)를 쓰고,
    S2 judge 는 role=, S3 verify 는 picked= 를 fields 로 받는다."""
    if structure not in PROMPTS or step not in PROMPTS[structure]:
        raise ValueError(f"모르는 구조·단계: {structure} {step}")
    template = PROMPTS[structure][step]
    return template.format(query=query_text(row), candidates=format_candidates(cands), **fields)


# ---------- 모델 출력 파싱 ----------
def _first_line(text):
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def parse_judge_output(text, allowed_ids):
    """('pick', id) | ('none', None) | ('invalid', None). 첫 줄만 본다. 허용 id 밖이거나 형식이 다르면 invalid.
    호출한 쪽이 invalid 를 none 으로 기록하고 개수를 센다."""
    line = _first_line(text).strip("`*\"' ")
    low = line.lower()
    if low.startswith("none"):
        return ("none", None)
    if low.startswith("pick"):
        parts = line.split(None, 1)
        token = parts[1].strip().strip("`*\"'<>[]().,; ") if len(parts) == 2 else ""
        if token.split() and token.split()[0] in set(allowed_ids):
            return ("pick", token.split()[0])
    return ("invalid", None)


def parse_role(text):
    """S2 노드1 출력 → '소재'|'공정'|'에너지'|'수송'|'폐기'|'모름'. 형식이 다르면 '모름'(전체에서 판정)."""
    line = _first_line(text).strip("`*\"'. ")
    for key in (*ROLE_LABELS, UNKNOWN_ROLE):
        if line.startswith(key):
            return key
    return UNKNOWN_ROLE


def parse_yes_no(text):
    """S3 검증 출력 → True(모순) | False(모순 아님) | None(형식이 다름)."""
    line = _first_line(text).strip("`*\"'. ")
    if line.startswith("예"):
        return True
    if line.startswith("아니"):
        return False
    return None


def filter_by_role(cands, role):
    """S2 노드2 입력 후보. role 이 모름이면 전체. 알려진 역할이면 그 역할과 합본만(합본은 항상 포함). 남는 후보가 없으면 전체로 되돌리고 (후보, True)."""
    if role == UNKNOWN_ROLE or role not in ROLE_LABELS:
        return list(cands), False
    keep = [c for c in cands if c.get("role") in ROLE_LABELS[role] or c.get("role") in COMBINED_LABELS]
    return (keep, False) if keep else (list(cands), True)


# ---------- 결과 ----------
def make_result(export_doc, sha, run_meta, per_row):
    """스키마 형식 dict. 모든 행을 내보낸 파일 순서대로 담는다. 행 누락·중복·모르는 label_id, 후보 밖 id 는 ValueError.
    run_meta: {kind, model, params, prompt_sha256, structure}. per_row: [{label_id, ranking, decision, picked_dataset_id, reason, confidence, latency_ms}]"""
    kind = run_meta.get("kind")
    if kind not in ("rerank", "judge"):
        raise ValueError(f"kind 는 rerank 또는 judge: {kind!r}")
    cands = {r["label_id"]: {c["dataset_id"] for c in r["candidates"]} for r in export_doc["rows"]}
    got = {}
    for x in per_row:
        lid = x["label_id"]
        if lid not in cands:
            raise ValueError(f"내보낸 파일에 없는 label_id {lid}")
        if lid in got:
            raise ValueError(f"label_id {lid} 중복")
        got[lid] = x
    missing = [lid for lid in cands if lid not in got]
    if missing:
        raise ValueError(f"결과가 없는 행 {len(missing)}개(예: {missing[:5]})")
    results = []
    for r in export_doc["rows"]:
        x = got[r["label_id"]]
        ranking = [[d, float(s)] for d, s in x["ranking"]]
        bad = [d for d, _ in ranking if d not in cands[r["label_id"]]]
        if bad:
            raise ValueError(f"label_id {r['label_id']}: 내보낸 후보에 없는 id {bad[:3]}")
        if kind == "rerank" and not ranking:
            raise ValueError(f"label_id {r['label_id']}: rerank 는 ranking 이 필요합니다")
        item = {"label_id": r["label_id"], "ranking": ranking}
        if kind == "judge":
            decision, picked = x.get("decision"), x.get("picked_dataset_id")
            if decision not in ("pick", "none"):
                raise ValueError(f"label_id {r['label_id']}: decision 은 pick 또는 none")
            if (decision == "pick") != (picked is not None) or (picked is not None and picked not in cands[r["label_id"]]):
                raise ValueError(f"label_id {r['label_id']}: decision 과 picked_dataset_id 가 맞지 않습니다")
            item.update(decision=decision, picked_dataset_id=picked)
        for k in ("reason", "confidence", "latency_ms"):
            if x.get(k) is not None:
                item[k] = x[k]
        results.append(item)
    run = {"kind": kind, "model": run_meta["model"], "params": run_meta.get("params") or {}}
    for k in ("prompt_sha256", "structure"):
        if run_meta.get(k) is not None:
            run[k] = run_meta[k]
    return {"export_id": export_doc["export_id"], "export_sha256": sha, "run": run, "results": results}


def decision_of(item):
    """한 행의 결정: pick 한 id 또는 'none'."""
    return item["picked_dataset_id"] if item.get("decision") == "pick" else "none"


def flip_rate(results_list):
    """같은 구조의 여러 회차 결과(스키마 dict 또는 결과 행 목록)에서 행별 결정이 하나라도 다른 행의 비율.
    회차마다 label_id 집합이 같아야 한다. 행이 없으면 None(지어내지 않는다)."""
    runs = [(x["results"] if isinstance(x, dict) else x) for x in results_list]
    if len(runs) < 2:
        raise ValueError("회차가 둘 이상이어야 합니다")
    maps = [{r["label_id"]: decision_of(r) for r in run} for run in runs]
    if any(set(m) != set(maps[0]) for m in maps):
        raise ValueError("회차마다 행 집합이 다릅니다")
    if not maps[0]:
        return None
    return sum(len({m[lid] for m in maps}) > 1 for lid in maps[0]) / len(maps[0])


def is_unstable(rate):
    """5% 를 넘으면 탈락. rate 가 None 이면 판단하지 않는다(False)."""
    return rate is not None and rate > FLIP_MAX


def decision_summary(per_row):
    """params 에 남기는 회차 요약(결정 개수). 행별 내용은 남기지 않는다."""
    n_pick = sum(1 for x in per_row if x.get("decision") == "pick")
    return {"rows": len(per_row), "pick": n_pick, "none": len(per_row) - n_pick}


def result_filename(export_name, kind, structure, unstable=False):
    """results/E3-<export>-<kind>-<structure>.json (재순위는 structure 'R'). 불안정이면 _UNSTABLE."""
    return f"E3-{export_name}-{kind}-{structure or 'R'}{'_UNSTABLE' if unstable else ''}.json"


def cache_key(model, prompt_sha, label_id, order):
    """판정 캐시 키: (모델, 프롬프트 sha256, label_id, 후보 순서)."""
    blob = json.dumps([model, prompt_sha, label_id, list(order)], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
