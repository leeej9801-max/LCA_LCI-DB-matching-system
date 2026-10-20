"""U8·U9 A19·A14 평가 결과 읽기 전용. DB 없이 실제 앱의 eval 경로만 호출한다(lifespan 을 열지 않는다)."""
import json
import shutil

from fastapi.testclient import TestClient

from app.api import evaluation
from app.api.evaluation import REPORTS
from app.schemas import ErrorBody, EvalRunList
from main import app

client = TestClient(app)
P1 = "eval-20261020-004831-gold-p1-v1-test"
MEASURE = "eval-20261020-004523-gold-measure-v2-test"
BULK = "eval-20261020-151720-gold-bulk-v1-test"


def without_bulk(tmp_path, monkeypatch):
    """bulk 리포트가 아직 없는 경우를 흉내 낸다: 실제 리포트 중 bulk 만 빼고 임시 폴더에 복사."""
    for f in REPORTS.glob("*.json"):
        if "gold-bulk-v1" not in f.name:
            shutil.copy(f, tmp_path / f.name)
    monkeypatch.setattr(evaluation, "REPORTS", tmp_path)


def test_list_without_bulk_report_has_only_p1(tmp_path, monkeypatch):
    without_bulk(tmp_path, monkeypatch)
    r = client.get("/api/eval/runs")
    assert r.status_code == 200
    body = EvalRunList.model_validate(r.json())
    assert body.total == 1
    assert [(i.run_id, i.set_label, i.split, i.rows) for i in body.items] == [(P1, "공개 문서 표기", "test", 58)]
    assert body.items[0].created_at == "2026-10-20T00:48:31"


def test_list_with_bulk_report_shows_bulk_then_p1_and_hides_dev_and_110():
    body = EvalRunList.model_validate(client.get("/api/eval/runs").json())
    assert [(i.set_label, i.run_id, i.rows) for i in body.items] == [("가상 BOM 2000 (검증용)", BULK, 2000), ("공개 문서 표기", P1, 58)]


def test_detail_is_the_file_as_is_even_for_sets_hidden_from_the_list():
    for run_id, total in [(P1, 58), (MEASURE, 110)]:
        r = client.get(f"/api/eval/runs/{run_id}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
        assert r.content == (REPORTS / f"{run_id}.json").read_bytes()
        assert r.json()["gold_stats"]["total"] == total and "C1+G+D+Vd" in r.json()["cases"]
        json.loads(r.text)


def test_unknown_id_is_404_in_common_shape():
    r = client.get("/api/eval/runs/eval-20200101-000000-gold-bulk-v1-test")
    assert r.status_code == 404
    ErrorBody.model_validate(r.json())


def test_path_escape_is_404():
    for bad in ["..", "../main", "..%2Fmain", "%2E%2E%2Fmain", "a%5Cb", "..%5Cmain", f"{P1}%2F..%2F..%2Fmain"]:
        r = client.get(f"/api/eval/runs/{bad}")
        assert r.status_code == 404, bad
        assert "detail" in r.json()
