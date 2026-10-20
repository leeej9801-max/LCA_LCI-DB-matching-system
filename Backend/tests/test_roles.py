"""T13: 데이터셋 역할, BOM 구분·부품번호, 역할로 검색 범위 나누기. 임시 DB + 가짜 임베더."""
import csv
import io
import json
from pathlib import Path

import openpyxl
import psycopg
import pytest

from app import jobs, roles
from app.bom import match
from app.bom.clean import clean_rows
from app.ingest import load
from app.schemas import SessionPayload
from app.search import dense_rank, load_index, rrf, tfidf_rank
from test_bom_match import add_session, bomdb  # noqa: F401  (fixture 재사용)
from test_indexer import FakeEmbedder
from test_ingest import inputs  # noqa: F401  (fixture 재사용)
from test_migrate import needs_db, tempdb  # noqa: F401
from test_sessions_api import client, post  # noqa: F401
from app.db.migrate import migrate

TABLE = Path(__file__).parents[2] / "docs/LCA/data/dataset-roles-2026-10-18.csv"
LABEL_OF_TABLE = {"소재+공정 합본": "합본"}  # 분류표의 글자 → 표시값
needs_table = pytest.mark.skipif(not TABLE.exists(), reason=f"{TABLE} 없음(docs/LCA 는 git 밖)")


def test_label_and_code_are_inverse():
    assert set(roles.LABEL) == {"material", "process", "combined", "transport", "waste", "utility"}
    assert all(roles.CODE[v] == k for k, v in roles.LABEL.items())


def test_seed_has_60_names_of_process_and_combined():
    seed = roles.load_seed()
    assert len(seed) == 60 and sorted(set(seed.values())) == ["combined", "process"]
    assert sum(1 for v in seed.values() if v == "combined") == 8 and sum(1 for v in seed.values() if v == "process") == 52


def test_rule_order_seed_then_category_then_material():
    seed = {"프레스 가공": "process"}
    assert roles.role_of("프레스 가공", "수송", seed) == "process"  # ① 시드가 분류 규칙보다 먼저
    assert roles.role_of("철도", "수송", seed) == "transport"
    assert roles.role_of("매립", "폐기물 처리& 재활용", seed) == "waste"
    for c in ("전기", "연료", "열", "수자원", "인프라 & 기계"):
        assert roles.role_of("x", c, seed) == "utility"
    assert roles.role_of("냉연강판", "금속", seed) == "material"  # ③ 나머지는 소재


@needs_table
def test_rules_reproduce_the_classification_table_for_all_849_rows():
    rows = list(csv.DictReader(open(TABLE, encoding="utf-8-sig")))
    seed = roles.load_seed()
    assert len(rows) == 849
    mismatch = [(r["name_ko"], r["role"], roles.LABEL[roles.role_of(r["name_ko"], r["category"], seed)])
                for r in rows if roles.LABEL[roles.role_of(r["name_ko"], r["category"], seed)] != LABEL_OF_TABLE.get(r["role"], r["role"])]
    assert mismatch == []
    counts = {}
    for r in rows:
        k = roles.role_of(r["name_ko"], r["category"], seed)
        counts[k] = counts.get(k, 0) + 1
    assert counts == {"material": 515, "process": 53, "combined": 8, "transport": 86, "waste": 85, "utility": 102}


@needs_db
def test_apply_is_idempotent_and_ingest_applies_roles(tempdb, inputs):  # noqa: F811
    migrate(tempdb)
    load(tempdb, **inputs)
    with psycopg.connect(tempdb) as conn:
        got = dict(conn.execute("SELECT name_ko, role FROM lci_dataset").fetchall())
        assert got["냉연강판"] == "material" and got["경유"] == "utility" and None not in got.values()
        assert roles.apply(conn) == 0  # 이미 채워져 있으면 바꿀 것이 없다
        conn.execute("UPDATE lci_dataset SET role = NULL")
        assert roles.apply(conn) == len(got) and None not in dict(conn.execute("SELECT name_ko, role FROM lci_dataset").fetchall()).values()
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE lci_dataset SET role = '소재'")  # 영문 코드만 허용


@needs_db
def test_ingest_fails_and_rolls_back_when_a_role_stays_null(tempdb, inputs, monkeypatch):  # noqa: F811
    migrate(tempdb)
    monkeypatch.setattr("app.ingest.roles.apply", lambda conn, ids=None: 0)
    with pytest.raises(SystemExit, match="role 이 NULL"):
        load(tempdb, **inputs)
    with psycopg.connect(tempdb) as conn:
        assert conn.execute("SELECT count(*) FROM lci_dataset").fetchone()[0] == 0


# ---------- 검색 범위 ----------
@pytest.fixture
def roled(bomdb):  # noqa: F811
    """냉연강판 3건 + 열연강판: 1=공정, 2=소재, 3=합본, 4=합본(이름이 달라 접히지 않음), 5=공정. 나머지는 소재."""
    with psycopg.connect(bomdb) as conn:
        conn.execute("UPDATE lci_dataset SET role = 'material'")
        for sn, role in ((1, "process"), (3, "combined"), (4, "combined"), (5, "process")):
            conn.execute("UPDATE lci_dataset SET role = %s WHERE list_sn = %s", (role, sn))
    return bomdb


def ranking(ci, text, **kw):
    with psycopg.connect(ci) as conn:
        version, model, items = load_index(conn)
        vec = FakeEmbedder().embed([text])[0]
        allowed = kw.get("allowed")
        return (tfidf_rank(items, text, kw.get("top", 100), allowed), dense_rank(conn, version, model, vec, kw.get("top", 100), kw.get("roles")))


@needs_db
def test_filter_keeps_scores_and_order_of_the_unfiltered_search(roled):
    ids = {"list-1", "list-5"}
    full_t, full_d = ranking(roled, "냉연강판")
    part_t, part_d = ranking(roled, "냉연강판", allowed=ids, roles=["process"])
    assert part_t == [x for x in full_t if x[0] in ids]  # IDF 는 전체 인덱스로 학습 → 점수·순서가 그대로
    assert part_d == [x for x in full_d if x[0] in ids]


@needs_db
def test_filter_is_applied_before_cutting_the_ranking(roled):
    full_t, full_d = ranking(roled, "냉연강판", top=2)
    assert {d for d, _ in full_d} - {"list-1", "list-5"}  # 필터 없이 2개만 자르면 공정이 아닌 것이 섞인다
    _, part_d = ranking(roled, "냉연강판", top=2, roles=["process"])
    assert [d for d, _ in part_d] == [d for d, _ in ranking(roled, "냉연강판", roles=["process"])[1]][:2] and len(part_d) == 2


T13_SETTINGS = {"search_base": "rrf", "lexicon_mode": None, "veto_mode": None, "confidence": {"rule": "R0", "params": {}}}  # E4a 이전의 검색


E4A_SETTINGS = {"search_base": "rrf", "lexicon_mode": "D", "veto_mode": "Vd", "confidence": {"rule": "R1", "params": {"tau": 0.55}}}  # E4c 이전(E4a) 기본


def run_session(ci, rows, settings=None):
    """rows: [(품명, 구분 원문)] → (session_id, 매칭 결과로 만든 SessionPayload dict). settings 를 안 주면 앱 기본 설정."""
    sid = "abcdefABCDEF"
    items = clean_rows([{"source_row": i + 2, "name": n, "spec": "", "unit": "kg", "quantity": "1", "role": r, "part_no": f"P{i}"}
                        for i, (n, r) in enumerate(rows)])
    with psycopg.connect(ci) as conn:
        conn.execute("INSERT INTO bom_project (project_id, source_file, expires_at) VALUES (%s, 'a.csv', now() + interval '1 day')", (sid,))
        for it in items:
            conn.execute("INSERT INTO bom_item (project_id, row_no, source_row, raw_name, raw_spec, raw_unit, raw_qty, clean_name, clean_spec, "
                         "clean_unit, clean_unit_display, clean_qty, norm_text, query_key, issues, target_status, target_reason, input_role, part_no) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (sid, it["row_no"], it["source_row"], it["raw_name"], it["raw_spec"], it["raw_unit"], it["raw_qty"], it["clean_name"],
                          it["clean_spec"], it["clean_unit"], it["clean_unit_display"], it["clean_qty"], it["norm_text"], it["query_key"],
                          json.dumps(it["issues"]), it["target_status"], it["target_reason"], it["input_role"], it["part_no"]))
        match.match_project(conn, sid, FakeEmbedder(), settings=settings)
        conn.commit()
        return sid, match.build_rows(conn, sid)


@needs_db
def test_rows_search_only_inside_their_roles_and_say_so(roled):
    _, rows = run_session(roled, [("냉연강판", "소재"), ("냉연강판", "공정"), ("냉연강판", "")], T13_SETTINGS)  # 강등(Vd)을 끄고 구분 필터만 본다
    mat, proc, free = rows
    assert {c["role"] for c in mat["candidates"]} <= {"소재", "합본"} and {c["role"] for c in proc["candidates"]} == {"공정"}
    with psycopg.connect(roled) as conn:  # 구분 없음 → 저장된 후보(접기 전)에 모든 역할이 섞여 있다
        stored = {r[0] for r in conn.execute("SELECT d.role FROM match_candidate c JOIN lci_dataset d USING (dataset_id) "
                                              "JOIN bom_item i USING (query_key) WHERE i.row_no = 3").fetchall()}
    assert stored >= {"material", "process", "combined"}
    assert (mat["input_role"], proc["input_role"], free["input_role"]) == ("소재", "공정", None)
    assert [r["part_no"] for r in rows] == ["P0", "P1", "P2"]
    assert all("구분 '공정' → 공정 데이터셋 안에서 찾음" in c["reasons"] for c in proc["candidates"])
    assert all(not any(s.startswith("구분 '") for s in c["reasons"]) for c in free["candidates"])
    combined = [c for c in mat["candidates"] if c["role"] == "합본"]
    assert combined and all("소재와 공정이 합쳐진 데이터셋 — 같은 부품의 공정 행과 겹치지 않는지 확인" in c["reasons"] for c in combined)
    assert mat["selected"]["role"] == mat["candidates"][0]["role"]
    SessionPayload.model_validate({"session_id": "x", "filename": "a.csv", "rows": rows, "summary": match.summarize(rows), "db_note": "",
                                   "column_mapping": None})


@needs_db
def test_without_role_the_saved_candidates_equal_the_unfiltered_search(roled):
    """구분이 없으면 T13 전과 같다: 저장된 후보(TOP_N개)가 필터 없는 하이브리드 검색 결과와 같다(사전·Veto 를 끈 설정)."""
    run_session(roled, [("냉연강판", "")], T13_SETTINGS)
    with psycopg.connect(roled) as conn:
        version, model, items = load_index(conn)
        t = tfidf_rank(items, "냉연강판")
        d = dense_rank(conn, version, model, FakeEmbedder().embed(["냉연강판"])[0])
        sn = {it["dataset_id"]: it["list_sn"] for it in items}
        saved = [r[0] for r in conn.execute("SELECT dataset_id FROM match_candidate ORDER BY rank").fetchall()]
    assert saved == [ds for ds, _ in rrf([t, d], sn)][:match.TOP_N]


@needs_db
def test_without_role_default_settings_push_opposite_role_back(roled):
    """E4a: RRF 검색에 Vd 를 켜면 '냉연강판'은 소재로 추정되어 공정 데이터셋(list-1, list-5)만 뒤로 가고 나머지 순서는 그대로다(E4c 로 앱 기본이 밀집 단독이 되어 설정을 명시)."""
    run_session(roled, [("냉연강판", "")], E4A_SETTINGS)
    with psycopg.connect(roled) as conn:
        version, model, items = load_index(conn)
        t = tfidf_rank(items, "냉연강판")
        d = dense_rank(conn, version, model, FakeEmbedder().embed(["냉연강판"])[0])
        sn = {it["dataset_id"]: it["list_sn"] for it in items}
        saved = [r[0] for r in conn.execute("SELECT dataset_id FROM match_candidate ORDER BY rank").fetchall()]
    plain = [ds for ds, _ in rrf([t, d], sn)]
    from app.bom.veto import demote
    with psycopg.connect(roled) as conn:
        role_of = dict(conn.execute("SELECT dataset_id, role FROM lci_dataset").fetchall())
    expected = [ds for ds, _ in rrf([demote(t, role_of, "process"), demote(d, role_of, "process")], sn)][:match.TOP_N]
    assert saved == expected and saved != plain[:match.TOP_N]
    assert saved.index("list-3") < saved.index("list-1") and "list-5" not in saved[:saved.index("list-1")]  # 공정 데이터셋(list-1, list-5)은 소재 후보 뒤로


@needs_db
def test_match_run_records_role_filter_rule(roled):
    run_session(roled, [("냉연강판", "공정")])
    with psycopg.connect(roled) as conn:
        config = conn.execute("SELECT config FROM match_run").fetchone()[0]
    assert config["role_filter_rule"] == match.ROLE_FILTER_RULE and "{공정}" in config["role_filter_rule"]


# ---------- API ----------
CSV_SPLIT = ("부품번호,구분,품명,단위,수량\nP01,소재,냉연강판,kg,2.4\nP01,공정,냉연강판,kg,2.4\nP02,,열연강판,kg,1\nP03,부품,폴리프로필렌,kg,1\n"
             .encode("utf-8"))


@needs_db
def test_upload_with_role_columns_end_to_end(client, roled):  # noqa: F811
    p = post(client, "/api/sessions/preview", CSV_SPLIT)
    assert {m["field"]: (m["source"], m["method"], m["required"]) for m in p.json()["column_mapping"]} == {
        "품명": ("품명", "auto", True), "규격": (None, "missing", False), "단위": ("단위", "auto", True), "수량": ("수량", "auto", True),
        "구분": ("구분", "auto", False), "부품번호": ("부품번호", "auto", False)}
    r = post(client, "/api/sessions", CSV_SPLIT)
    assert r.status_code == 202
    jobs.claim(client.ci)
    jobs.run_match_job(client.ci, r.json()["job_id"], lambda ci: FakeEmbedder())
    body = SessionPayload.model_validate(client.get(f"/api/sessions/{r.json()['session_id']}").json()).model_dump()
    rows = body["rows"]
    assert [(x["part_no"], x["input_role"]) for x in rows] == [("P01", "소재"), ("P01", "공정"), ("P02", None), ("P03", None)]
    assert rows[3]["issues"] == ["구분 값을 알 수 없음: 부품"]
    assert {c["role"] for c in rows[1]["candidates"]} == {"공정"} and "공정" not in {c["role"] for c in rows[0]["candidates"]}
    # 같은 품명이라도 구분이 다르면 다른 검색(query_key)이고, 중복 행으로 보지 않는다
    assert rows[0]["issues"] == [] and rows[1]["issues"] == []
    # 승인 → 내보내기에 부품번호·구분·데이터셋 역할
    sid = r.json()["session_id"]
    assert client.patch(f"/api/sessions/{sid}/rows/2", json={"review_status": "approved"}).status_code == 200
    c = client.get(f"/api/sessions/{sid}/export", params={"format": "csv"})
    lines = list(csv.reader(io.StringIO(c.content.decode("utf-8-sig"))))
    head = lines[0]
    assert lines[1][head.index("부품번호")] == "P01" and lines[1][head.index("구분")] == "공정" and lines[1][head.index("데이터셋 역할")] == "공정"
    wb = openpyxl.load_workbook(io.BytesIO(client.get(f"/api/sessions/{sid}/export").content))
    assert [c.value for c in wb["미승인·제외"][2]][1:3] == ["부품번호", "구분"]  # X1: 1행은 그룹 띠, 2행이 열 이름
    assert "구분 필터 규칙" in {row[0].value for row in wb["정보"].iter_rows(min_row=2)}


@needs_db
def test_bom_without_role_columns_behaves_as_before(client, roled):  # noqa: F811
    csv_old = "품명,단위,수량\n냉연강판,kg,2.4\n".encode("utf-8")
    r = post(client, "/api/sessions", csv_old)
    jobs.claim(client.ci)
    jobs.run_match_job(client.ci, r.json()["job_id"], lambda ci: FakeEmbedder())
    row = client.get(f"/api/sessions/{r.json()['session_id']}").json()["rows"][0]
    assert (row["input_role"], row["part_no"]) == (None, None) and row["issues"] == []
    with psycopg.connect(client.ci) as conn:
        import hashlib
        assert conn.execute("SELECT query_key FROM bom_item").fetchone()[0] == hashlib.sha256("냉연강판".encode("utf-8")).hexdigest()
