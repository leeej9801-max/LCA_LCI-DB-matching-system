"""E3: Colab 노트북이 쓰는 순수 함수(e3_core)와 노트북 파일의 형식. torch·langgraph 없이 도는 시험."""
import ast
import hashlib
import json
from pathlib import Path

import pytest

from app.evaluation import e3_core as e3
from app.evaluation.import_external import validate as import_validate

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks/E3_rerank_judge.ipynb"
SCHEMA = ROOT / "docs/LCA/spec/external-result.schema.json"
EXPORT_DIR = ROOT / "docs/LCA/data/export"
E2B_SHA = {"dev-C2DV.json": "f21a2c4104b8824994489f07d58ca6252d8e5ebdee51fa1039238b6040303ebf",
           "dev-C1GDV.json": "1bea380a92790dd9922c2f436d2c92582e9d81a4eb1879dbefbcc822bd2f7939"}


def cand(i, role="소재", rank=None):
    return {"dataset_id": f"list-{i}", "rank": rank or i, "score": 1.0 / i, "name_ko": f"이름{i}", "name_en": f"name{i}", "category": "금속",
            "role": role, "org": "기관", "year": 2022}


def export_doc():
    """정답 열이 전혀 없는 내보내기(export_candidates 가 만드는 모양)."""
    return {"export_id": "exp-test", "gold_id": "g", "split": "dev", "base_case": "C2+D+V", "top": 3, "rows": [
        {"label_id": 10, "query": "PP 수지", "spec": "t1.2", "unit": "kg", "input_role": None, "inferred_role": "material",
         "candidates": [cand(1), cand(2, "공정"), cand(3, "합본")]},
        {"label_id": 11, "query": "사출", "spec": None, "unit": None, "input_role": None, "inferred_role": None,
         "candidates": [cand(4, "공정"), cand(5), cand(6, "소재+공정 합본")]}]}


def write_export(tmp_path, doc=None):
    p = tmp_path / "exp.json"
    p.write_bytes(json.dumps(doc or export_doc(), ensure_ascii=False).encode("utf-8"))
    return p


# ---------- 모듈 성격 ----------
def test_core_imports_only_light_modules():
    tree = ast.parse(Path(e3.__file__).read_text(encoding="utf-8"))
    names = {n.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for n in [a.name for a in node.names]}
    names |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert names <= {"hashlib", "json", "pathlib"}  # torch·transformers·langgraph·앱 코드 import 없음
    assert not names & {"torch", "transformers", "langgraph", "numpy", "psycopg", "app"}


# ---------- 입력 ----------
def test_load_export_works_without_answer_columns_and_hashes_bytes(tmp_path):
    p = write_export(tmp_path)
    doc, sha = e3.load_export(p)
    assert doc["rows"][0]["label_id"] == 10 and sha == hashlib.sha256(p.read_bytes()).hexdigest()


def test_load_export_rejects_answer_keys(tmp_path):
    for key in ("expected_dataset_id", "a_accept", "s_accept", "label_type", "note"):
        doc = export_doc()
        doc["rows"][0][key] = "x"
        with pytest.raises(ValueError, match="정답 관련 키"):
            e3.load_export(write_export(tmp_path, doc))
    doc = export_doc()
    doc["rows"][0]["candidates"][0]["expected"] = "x"  # 후보 안에 있어도 거부
    with pytest.raises(ValueError):
        e3.load_export(write_export(tmp_path, doc))


def test_candidate_and_query_text():
    c = cand(7)
    assert e3.candidate_text(c) == "이름7 | name7 | 금속 | 소재" and "기관" not in e3.candidate_text(c) and "2022" not in e3.candidate_text(c)
    assert e3.candidate_text({"name_ko": "가", "name_en": None, "category": "나", "role": None}) == "가 |  | 나 | "  # 없는 값은 빈 칸
    rows = export_doc()["rows"]
    assert e3.query_text(rows[0]) == "PP 수지 / t1.2 / 단위 kg" and e3.query_text(rows[1]) == "사출"
    assert e3.query_text({"query": "a", "spec": "", "unit": "m"}) == "a / 단위 m"


def test_permute_is_deterministic_and_a_permutation():
    cands = [cand(i) for i in range(1, 11)]
    a, b = e3.permute(cands, 0), e3.permute(cands, 0)
    assert a == b and sorted(c["dataset_id"] for c in a) == sorted(c["dataset_id"] for c in cands)
    orders = {tuple(c["dataset_id"] for c in e3.permute(cands, s)) for s in range(5)}
    assert len(orders) == 5  # 시드마다 다른 순서
    assert e3.permute(cands, 3) == e3.permute(list(reversed(cands)), 3)  # 입력 순서와 무관
    assert cands[0]["dataset_id"] == "list-1"  # 입력을 바꾸지 않는다


# ---------- 순위 ----------
def test_rank_by_scores_and_pick():
    cands = [cand(1), cand(2), cand(3)]
    assert e3.rank_by_scores(cands, [0.1, 0.9, 0.9]) == [["list-2", 0.9], ["list-3", 0.9], ["list-1", 0.1]]  # 동점은 내보낸 순서
    with pytest.raises(ValueError):
        e3.rank_by_scores(cands, [1.0])
    r = [["list-2", 0.9], ["list-3", 0.5], ["list-1", 0.1]]
    assert e3.rank_with_pick(r, "list-1") == [["list-1", 0.1], ["list-2", 0.9], ["list-3", 0.5]]
    assert e3.rank_with_pick(r, None) == r and e3.rank_with_pick(r, None) is not r
    with pytest.raises(ValueError):
        e3.rank_with_pick(r, "list-9")


# ---------- 프롬프트 ----------
def test_prompts_hash_and_build():
    assert len({e3.prompt_sha256(s) for s in e3.STRUCTURES}) == 3 and e3.prompt_sha256("S1") == e3.prompt_sha256("S1")
    with pytest.raises(ValueError):
        e3.prompt_sha256("S9")
    row, cands = export_doc()["rows"][0], export_doc()["rows"][0]["candidates"]
    p = e3.build_judge_prompt(row, cands, "S1", "judge")
    assert "PP 수지 / t1.2 / 단위 kg" in p and "- list-1: 이름1 | name1 | 금속 | 소재" in p and "기관" not in p
    assert "{" not in p and "pick <id>" in p
    assert "'공정' 종류" in e3.build_judge_prompt(row, cands, "S2", "judge", role="공정")
    assert "질의: PP 수지" in e3.build_judge_prompt(row, [], "S2", "role")
    assert "list-1: 이름1" in e3.build_judge_prompt(row, [], "S3", "verify", picked="list-1: 이름1")
    for bad in (("S1", "verify"), ("S9", "judge"), ("S2", "nope")):
        with pytest.raises(ValueError):
            e3.build_judge_prompt(row, cands, *bad)


# ---------- 출력 파싱 ----------
ALLOWED = ["list-12", "list-3", "list-45"]


@pytest.mark.parametrize("text,expect", [
    ("pick list-12", ("pick", "list-12")), ("pick list-12\n이유: 재질이 같다", ("pick", "list-12")),
    ("  Pick list-3.  ", ("pick", "list-3")), ("`pick list-45`", ("pick", "list-45")), ("pick <list-3>", ("pick", "list-3")),
    ("\n\npick list-12", ("pick", "list-12")),
    ("none", ("none", None)), ("None.", ("none", None)), ("none\n맞는 후보 없음", ("none", None)),
    ("pick list-99", ("invalid", None)),  # 허용 id 밖
    ("pick", ("invalid", None)), ("list-12", ("invalid", None)), ("", ("invalid", None)), ("모르겠습니다", ("invalid", None)),
    ("pick list-1", ("invalid", None)),  # 접두어만 같은 id 는 아님
])
def test_parse_judge_output(text, expect):
    assert e3.parse_judge_output(text, ALLOWED) == expect


def test_parse_role_yes_no_and_filter():
    assert e3.parse_role("공정\n이유") == "공정" and e3.parse_role("에너지") == "에너지" and e3.parse_role("폐기.") == "폐기"
    assert e3.parse_role("잘 모르겠다") == "모름" and e3.parse_role("") == "모름"
    assert e3.parse_yes_no("예\n설명") is True and e3.parse_yes_no("아니오") is False and e3.parse_yes_no("글쎄") is None
    cands = [cand(1, "소재"), cand(2, "공정"), cand(3, "합본"), cand(4, "수송")]
    keep, fallback = e3.filter_by_role(cands, "공정")
    assert [c["dataset_id"] for c in keep] == ["list-2", "list-3"] and fallback is False  # 합본은 항상 포함
    assert e3.filter_by_role(cands, "모름") == (cands, False)
    only_material = [cand(1, "소재"), cand(2, "소재")]
    assert e3.filter_by_role(only_material, "수송") == (only_material, True)  # 남는 게 없으면 전체로 되돌림


# ---------- 결과 ----------
def rerank_rows(doc, reverse=False):
    out = []
    for r in doc["rows"]:
        ranking = [[c["dataset_id"], float(i)] for i, c in enumerate(r["candidates"][::-1] if reverse else r["candidates"])][::-1]
        out.append({"label_id": r["label_id"], "ranking": ranking, "latency_ms": 5})
    return out


RERANK_META = {"kind": "rerank", "model": "m", "params": {"batch": 10}, "structure": None, "prompt_sha256": None}


def judge_rows(doc, picks):
    out = []
    for r in doc["rows"]:
        ranking = e3.rank_by_scores(r["candidates"], [c["score"] for c in r["candidates"]])
        picked = picks.get(r["label_id"])
        out.append({"label_id": r["label_id"], "ranking": e3.rank_with_pick(ranking, picked), "decision": "pick" if picked else "none",
                    "picked_dataset_id": picked, "reason": "r"})
    return out


def test_make_result_passes_import_validation_and_schema():
    doc = export_doc()
    res = e3.make_result(doc, "s" * 64, RERANK_META, rerank_rows(doc))
    assert [x["label_id"] for x in res["results"]] == [10, 11] and res["run"] == {"kind": "rerank", "model": "m", "params": {"batch": 10}}
    assert import_validate(res, doc, "s" * 64) == []
    meta = {"kind": "judge", "model": "j", "params": {}, "structure": "S1", "prompt_sha256": e3.prompt_sha256("S1")}
    res = e3.make_result(doc, "s" * 64, meta, judge_rows(doc, {10: "list-2"}))
    assert res["results"][0]["decision"] == "pick" and res["results"][0]["ranking"][0][0] == "list-2"
    assert res["results"][1]["decision"] == "none" and res["results"][1]["picked_dataset_id"] is None
    assert import_validate(res, doc, "s" * 64) == [] and res["run"]["structure"] == "S1"
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(res)
    jsonschema.Draft202012Validator(schema).validate(e3.make_result(doc, "s" * 64, RERANK_META, rerank_rows(doc)))


def test_make_result_cannot_drop_or_invent_rows():
    doc, sha = export_doc(), "s" * 64
    rows = rerank_rows(doc)
    with pytest.raises(ValueError, match="결과가 없는 행"):
        e3.make_result(doc, sha, RERANK_META, rows[:1])
    with pytest.raises(ValueError, match="없는 label_id"):
        e3.make_result(doc, sha, RERANK_META, rows + [{"label_id": 99, "ranking": [["list-1", 1.0]]}])
    with pytest.raises(ValueError, match="중복"):
        e3.make_result(doc, sha, RERANK_META, rows + [rows[0]])
    bad = [dict(rows[0], ranking=[["list-999", 1.0]]), rows[1]]
    with pytest.raises(ValueError, match="내보낸 후보에 없는 id"):
        e3.make_result(doc, sha, RERANK_META, bad)
    with pytest.raises(ValueError, match="rerank 는 ranking"):
        e3.make_result(doc, sha, RERANK_META, [dict(rows[0], ranking=[]), rows[1]])
    with pytest.raises(ValueError, match="kind"):
        e3.make_result(doc, sha, {"kind": "x", "model": "m"}, rows)
    j = {"kind": "judge", "model": "j"}
    jr = judge_rows(doc, {10: "list-2"})
    for broken in (dict(jr[0], decision="maybe"), dict(jr[0], picked_dataset_id=None), dict(jr[0], picked_dataset_id="list-5")):
        with pytest.raises(ValueError):
            e3.make_result(doc, sha, j, [broken, jr[1]])
    with pytest.raises(ValueError):  # none 인데 picked 가 있음
        e3.make_result(doc, sha, j, [jr[0], dict(jr[1], decision="none", picked_dataset_id="list-4")])


def result_with(decisions):
    return {"results": [{"label_id": i, "decision": "none" if d == "none" else "pick", "picked_dataset_id": None if d == "none" else d}
                        for i, d in enumerate(decisions, 1)]}


def test_flip_rate_by_hand():
    same = result_with(["a", "none", "b", "c"])
    assert e3.flip_rate([same] * 5) == 0.0
    flip = result_with(["a", "none", "b", "x"])  # 4번째 행만 다름
    assert e3.flip_rate([same, same, flip, same, same]) == 0.25
    both = result_with(["none", "none", "b", "x"])  # 1번째 행도 다름
    assert e3.flip_rate([same, flip, both]) == 0.5
    assert e3.flip_rate([same["results"], same["results"]]) == 0.0  # 결과 행 목록도 받는다
    assert e3.flip_rate([result_with([]), result_with([])]) is None  # 행이 없으면 지어내지 않는다
    with pytest.raises(ValueError):
        e3.flip_rate([same])
    with pytest.raises(ValueError):
        e3.flip_rate([same, result_with(["a"])])


def test_unstable_threshold_and_names():
    assert not e3.is_unstable(0.05) and e3.is_unstable(0.0501) and not e3.is_unstable(None)
    # 134행에서 6행이 뒤집히면 4.48%(통과), 7행이면 5.22%(탈락)
    assert not e3.is_unstable(6 / 134) and e3.is_unstable(7 / 134)
    assert e3.result_filename("dev-C2DV", "rerank", None) == "E3-dev-C2DV-rerank-R.json"
    assert e3.result_filename("dev-C2DV", "judge", "S2", True) == "E3-dev-C2DV-judge-S2_UNSTABLE.json"
    assert e3.decision_summary(judge_rows(export_doc(), {10: "list-2"})) == {"rows": 2, "pick": 1, "none": 1}
    k = e3.cache_key("m", "p", 3, ["judge", "list-1"])
    assert k == e3.cache_key("m", "p", 3, ["judge", "list-1"]) and len({k, e3.cache_key("m2", "p", 3, ["judge", "list-1"]),
        e3.cache_key("m", "p2", 3, ["judge", "list-1"]), e3.cache_key("m", "p", 4, ["judge", "list-1"]), e3.cache_key("m", "p", 3, ["judge", "list-2"])}) == 5


# ---------- 실제 내보내기 파일(있을 때) ----------
@pytest.mark.skipif(not (EXPORT_DIR / "dev-C2DV.json").exists(), reason="내보내기 파일 없음")
@pytest.mark.parametrize("name", ["dev-C2DV.json", "dev-C1GDV.json"])
def test_real_exports_match_e2b_sha_and_make_valid_results(name):
    doc, sha = e3.load_export(EXPORT_DIR / name)
    assert sha == E2B_SHA[name] and doc["split"] == "dev" and len(doc["rows"]) == 134
    res = e3.make_result(doc, sha, RERANK_META, rerank_rows(doc, reverse=True))
    assert len(res["results"]) == 134 and import_validate(res, doc, sha) == []
    picks = {r["label_id"]: r["candidates"][2]["dataset_id"] for r in doc["rows"][::2]}
    judge = e3.make_result(doc, sha, {"kind": "judge", "model": "j", "structure": "S3"}, judge_rows(doc, picks))
    assert import_validate(judge, doc, sha) == []


# ---------- 노트북 ----------
def nb_cells():
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    return [(c["cell_type"], "".join(c["source"])) for c in nb["cells"]]


def test_notebook_structure_and_code_parses():
    cells = nb_cells()
    code = [src for kind, src in cells if kind == "code"]
    assert [s.splitlines()[0].split(" — ")[0] for s in code] == [f"# 셀 {i}" for i in range(6)]  # 셀 0~5 순서
    for i, src in enumerate(code):
        py = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith(("!", "%")))
        ast.parse(py, filename=f"cell{i}")
    joined = "\n".join(code)
    for needle in ("transformers>=", "accelerate>=", "bitsandbytes>=", "langgraph>=", "jsonschema>="):  # 설치 줄은 범위 지정
        assert needle in code[0]
    assert "<5" in code[0] and "VERSIONS" in code[0]  # transformers 는 4.x 로 제한, 실제 설치 버전은 VERSIONS 로 기록
    assert "BAAI/bge-reranker-v2-m3" in code[2] and "Qwen/Qwen2.5-7B-Instruct" in code[3]
    assert "StateGraph" in code[3] and "do_sample=False" in code[3] and "load_in_4bit=True" in code[3]
    assert "SEEDS = (0, 1, 2, 3, 4)" in code[3] and "_UNSTABLE" not in code[3] and "result_filename" in code[5]
    assert "Draft202012Validator" in code[5] and "files.download" in code[5] and "torch.no_grad" in code[2] and ".eval()" in code[2]
    assert "JUDGE_EXPORTS = [\"dev-C2DV\"]" in code[3]  # 판정은 dev-C2DV 하나에서만 먼저
    for key in E2B_SHA.values():
        assert key in code[1]  # 첫 셀들에서 E2b-run 의 sha256 과 대조
    for forbidden in ("a_accept", "s_accept", "label_type", "expected_dataset_id", "top1", "accuracy"):
        assert forbidden not in joined  # 정답 값을 다루지 않고 정확도를 계산하지 않는다
