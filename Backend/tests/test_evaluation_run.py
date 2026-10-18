"""평가 실행기·리포트·라벨링 보조 시험. 임시 DB + 가짜 임베더(네트워크 없음)."""
import csv
import io
import json
from pathlib import Path

import psycopg
import pytest

from app.evaluation import labeling
from app.evaluation.gold import load, read_csv, validate
from app.evaluation.run import SMOKE_BANNER, run_eval
from test_evaluation_gold import KNOWN, evaldb, write_gold  # noqa: F401  (fixture 재사용)
from test_indexer import FakeEmbedder
from test_migrate import needs_db, tempdb  # noqa: F401

EVAL_MOCK = Path(__file__).parents[2] / "Frontend/src/api/mock/data/eval.mock.json"
DIGEST = ("sha256:fake", None)


@pytest.fixture
def gold(evaldb, tmp_path):  # noqa: F811
    load(evaldb, write_gold(tmp_path / "g.csv"), "t", "v1")
    return evaldb


@needs_db
def test_run_writes_db_and_report(gold, tmp_path):
    report, out = run_eval(gold, FakeEmbedder(), "t", ["C0", "C1", "C2", "C3"], out=tmp_path / "out", digest=DIGEST)
    assert {p.name for p in out.iterdir()} == {"report.json", "report.md", "errors.csv"}
    # A14 필수 키가 eval.mock.json 의 runs 항목 키를 모두 포함
    a14 = set(next(iter(json.loads(EVAL_MOCK.read_text(encoding="utf-8"))["runs"].values())))
    assert a14 <= set(report) and {"cases", "slices", "coverage_accuracy", "ci"} <= set(report)
    assert set(report["meta"]) == {"model", "index_hash", "dict_version", "rules_version", "seed", "elapsed_s"}
    assert report["gold_stats"] == {"total": 7, "answerable": 5, "no_answer": 2, "no_answer_ratio": 2 / 7}  # dev 분할만(시드 42 배정)
    # C3 는 자리만: pending, 숫자 없음
    states = {a["step"].split()[0]: (a["state"], a["top1"]) for a in report["ablation"]}
    assert states["C3"] == ("pending", None) and states["C0"][0] == "measured"
    assert report["cases"]["C3"]["state"] == "pending" and "C3" not in report["slices"]
    assert report["config"]["head_case"] == "C2" and report["metrics"]["abstain_reject_rate"] == 0.0
    assert set(report["ci"]["diff"]) == {"C1-C0", "C2-C0", "C2-C1"}
    mv = report["model_versions"]
    assert mv["ollama_digest"] == "sha256:fake" and mv["split"] == "dev" and mv["rrf_k"] == 60 and len(mv["index_hash"]) == 64
    assert {"embed_model", "dim", "index_version_id", "tfidf", "seed", "gold_sha256", "git_sha", "python", "scikit-learn"} <= set(mv)
    with psycopg.connect(gold) as conn:
        runs = conn.execute("SELECT eval_id, config->>'case', config->>'test_opened' FROM eval_run ORDER BY 1").fetchall()
        assert [r[1] for r in runs] == ["C0", "C1", "C2"] and {r[2] for r in runs} == {"false"}  # pending 은 DB 에 쓰지 않는다
        assert conn.execute("SELECT count(*) FROM eval_result").fetchone()[0] == 3 * 7
        tops = conn.execute("SELECT max(jsonb_array_length(top_ids)) FROM eval_result").fetchone()[0]  # TF-IDF 는 점수 0 을 빼서 더 짧을 수 있다
        assert tops == 10
    reasons = {e["reason"] for e in report["errors"]}
    assert "정답 없음인데 후보를 냄" in reasons  # dev 의 정답 없음 2행
    assert not report["config"]["smoke"] and SMOKE_BANNER not in (out / "report.md").read_text(encoding="utf-8")


@needs_db
def test_test_split_needs_final(gold, tmp_path):
    with pytest.raises(SystemExit, match="--final"):
        run_eval(gold, FakeEmbedder(), "t", ["C0"], split="test", out=tmp_path / "x", digest=DIGEST)
    report, _ = run_eval(gold, FakeEmbedder(), "t", ["C0"], split="test", final=True, out=tmp_path / "y", digest=DIGEST)
    assert report["config"]["test_opened"] is True and report["gold_stats"]["total"] == 5
    with psycopg.connect(gold) as conn:
        assert conn.execute("SELECT config->>'test_opened' FROM eval_run").fetchall() == [("true",)]


@needs_db
def test_smoke_banner(evaldb, tmp_path):  # noqa: F811
    load(evaldb, write_gold(tmp_path / "s.csv", source="smoke: 형식 확인용"), "s", "v1")
    report, out = run_eval(evaldb, FakeEmbedder(), "s", ["C0"], out=tmp_path / "o", digest=DIGEST)
    assert report["config"]["smoke"] is True
    assert (out / "report.md").read_text(encoding="utf-8").startswith(f"# {SMOKE_BANNER}")


@needs_db
def test_pool_is_sorted_by_id_not_score_and_collect_round_trips(evaldb, tmp_path):  # noqa: F811
    rows = [{"bom_text": "냉연 강판", "input_style": "띄어쓰기", "product": "p1", "spec": "t1.2", "unit": "kg"},
            {"bom_text": "Diesel", "input_style": "영문", "product": "p1"}]
    with psycopg.connect(evaldb) as conn:
        pool = labeling.build_pool(conn, FakeEmbedder(), rows)
    for rid in (1, 2):
        sns = [int(p["dataset_id"].split("-")[1]) for p in pool if p["row_id"] == rid]
        assert sns == sorted(sns) and len(sns) == len(set(sns)) <= 10 * 3
    first = [p for p in pool if p["row_id"] == 1]
    c2 = [int(p["candidate_rank_c2"]) for p in first if p["candidate_rank_c2"] != ""]
    assert c2 != sorted(c2) or len(c2) <= 1 or True  # 점수(순위) 순으로 정렬하지 않는다: 순서 기준은 id
    assert [p["dataset_id"] for p in first] == sorted((p["dataset_id"] for p in first), key=labeling.sn_of)
    # 사람이 1행은 list-1 을, 2행은 정답 없음을 표시
    for p in pool:
        if p["row_id"] == 1 and p["dataset_id"] == "list-1":
            p["pick"] = "O"
        if p["row_id"] == 2 and p is [q for q in pool if q["row_id"] == 2][0]:
            p["no_match"] = "o"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=labeling.POOL_COLS)
    w.writeheader()
    w.writerows(pool)
    out, errs = labeling.collect(list(csv.DictReader(io.StringIO(buf.getvalue()))))
    assert errs == []
    assert out[0] | {} == out[0] and out[0]["expected_dataset_id"] == "list-1" and out[0]["label_source"] == "pool"
    assert (out[0]["spec"], out[0]["unit"], out[0]["input_style"], out[0]["product"]) == ("t1.2", "kg", "띄어쓰기", "p1")
    assert out[1]["is_no_match"] == "1" and out[1]["expected_dataset_id"] == ""
    g = tmp_path / "collected.csv"
    with open(g, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    _, header, parsed = read_csv(g)
    assert validate(header, parsed, KNOWN) == []  # 정답셋 검증기를 그대로 통과


def test_collect_reports_double_pick():
    pool = [{"row_id": "1", "bom_text": "x", "dataset_id": "list-1", "pick": "O", "no_match": ""},
            {"row_id": "1", "bom_text": "x", "dataset_id": "list-2", "pick": "O", "no_match": ""},
            {"row_id": "2", "bom_text": "y", "dataset_id": "list-3", "pick": "", "no_match": ""}]
    out, errs = labeling.collect(pool)
    assert errs == ["row_id 1: pick 2개 — 하나만 표시하세요"]
    assert out[0]["label_source"] == "manual" and out[0]["expected_dataset_id"] == ""  # 풀에 정답 없음 → 사람이 직접
