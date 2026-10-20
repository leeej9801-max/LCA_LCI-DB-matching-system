"""목록 849행 + T10a 파일 단서를 lci_dataset 에 적재하고 데이터 문제를 dataset_issue 에 남긴다.

실행: uv run --env-file ../.env python -m app.ingest [--dry-run] [--list ...] [--map ...] [--features ...]
전체를 한 트랜잭션으로 한다. 같은 입력이면 다시 돌려도 결과가 같다(lci_dataset 은 upsert, 이슈는 지우고 다시 쓴다).
원문 값은 고치지 않는다. ZIP·엑셀은 다시 읽지 않고 link-features.json 만 쓴다.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from app import roles
from app.db.connection import conninfo

ROOT = Path(__file__).resolve().parents[2]
LIST = ROOT / "docs/LCA/data/lci-db-list-ecosq-849.csv"
MAP = ROOT / "data/raw/download-map.csv"
FEATURES = ROOT / "data/raw/link-features.json"
REPORT = ROOT / "data/raw/ingest-report.md"
MIGRATION = "0002_dataset_extra.sql"
ROLE_MIGRATION = "0006_role.sql"
GWP_MIGRATION = "0009_gwp.sql"
GWP_SUM_TOLERANCE = Decimal("0.01")  # 합계와 세 항목 합이 1% 넘게 다르면 이슈(값은 그대로)
GWP_KEYS = {"total": "gwp_total", "fossil": "gwp_fossil", "biogenic": "gwp_biogenic", "luluc": "gwp_luluc"}
NAME_CHECK_MIN = 0.10  # exact 인데 이름 점검 점수가 이보다 낮으면 name_mismatch(사람이 본다)
GATE_TO_GATE = re.compile(r"gate[\s-]*to[\s-]*gate", re.I)

COLUMNS = ["dataset_id", "list_sn", "ilcd_uuid", "name_ko", "name_en", "category", "developer", "dev_year", "version", "has_xml",
           "reference_year", "geography", "tech_description", "allocation", "cutoff", "dataset_type", "ref_flow_name",
           "ref_flow_unit", "ref_flow_amount", "system_boundary", "source_file", "source_hash",
           "gwp_total", "gwp_fossil", "gwp_biogenic", "gwp_luluc", "gwp_method"]
FILE_COLUMNS = ["ilcd_uuid", "reference_year", "geography", "tech_description", "allocation", "cutoff", "dataset_type",
                "ref_flow_name", "ref_flow_unit", "ref_flow_amount", "system_boundary", "source_file", "source_hash",
                "gwp_total", "gwp_fossil", "gwp_biogenic", "gwp_luluc", "gwp_method"]
UPSERT = (
    f"INSERT INTO lci_dataset ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))}) "
    f"ON CONFLICT (dataset_id) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "dataset_id")
    + ", loaded_at = now()"
)


def text(v):
    """앞뒤 공백만 지운 원문. 빈 값은 NULL."""
    v = (v or "").strip() if isinstance(v, str) or v is None else v
    return v if v not in ("", None) else None


def amount(raw):
    """(숫자 또는 None, 숫자가 아니었는지). 쉼표는 지운다."""
    if raw in (None, ""):
        return None, False
    try:
        return Decimal(str(raw).replace(",", "").strip()), False
    except InvalidOperation:
        return None, True


def gwp_values(lcia, ref_amount):
    """(열 값 dict, 이슈 [(code, severity, message, detail)]). lcia: 파일 단서의 기후변화 4개 항목(문자열). 값이 없으면 NULL 그대로 둔다.
    값은 기준 흐름 양당 결과라 ref_amount 로 나눠 1 기준 단위당으로 바꾼다. 기준 흐름 양이 없거나 숫자가 아니거나 0 이하면 NULL + gwp_no_ref."""
    empty = {c: None for c in GWP_KEYS.values()} | {"gwp_method": None}
    if not lcia:
        return empty, []
    raw = {k: amount(text(lcia.get(k)))[0] for k in GWP_KEYS}
    if raw["total"] is None:
        return empty, []
    if ref_amount is None or ref_amount <= 0:
        return empty, [("gwp_no_ref", "warning", "배출계수가 있으나 기준 흐름 양이 없어 1 기준 단위당으로 바꾸지 못했습니다",
                        {"ref_flow_amount": None if ref_amount is None else str(ref_amount)})]
    issues = []
    parts = [raw["fossil"], raw["biogenic"], raw["luluc"]]
    if None not in parts:
        total = raw["total"]
        diff = abs(total - sum(parts))
        if diff > GWP_SUM_TOLERANCE * abs(total) + Decimal("1e-12"):
            issues.append(("gwp_sum_mismatch", "info", "기후변화 합계가 세 항목의 합과 1% 넘게 다릅니다(값은 그대로 둠)",
                           {"total": str(total), "sum_of_parts": str(sum(parts))}))
    version = text(lcia.get("method_version"))
    values = {GWP_KEYS[k]: (v / ref_amount if v is not None else None) for k, v in raw.items()}
    values["gwp_method"] = f"Climate change ({version})" if version else "Climate change"
    return values, issues


def read_inputs(list_path, map_path, features_path):
    with open(list_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(map_path, encoding="utf-8-sig", newline="") as f:
        mapping = list(csv.DictReader(f))
    features = json.loads(Path(features_path).read_text(encoding="utf-8"))
    return rows, mapping, features


def build(rows, mapping, features, seed=None):
    """(데이터셋 dict 목록, 이슈 목록 [(dataset_id, code, severity, message, detail)]). DB 없이 계산만 한다.
    seed: 역할 시드(이름 → 역할). None 이면 그때 불러온다(모듈을 불러올 때는 파일을 읽지 않는다)."""
    seed = roles.load_seed() if seed is None else seed
    by_sha = {v["sha"]: v for v in features.values() if v.get("sha")}
    links = {}
    for m in mapping:
        if str(m.get("list_row", "")).strip().isdigit():
            links[int(m["list_row"])] = m

    datasets, issues = [], []

    def issue(ds, code, severity, message, detail=None):
        issues.append((ds["dataset_id"], code, severity, message, detail or {}))

    for r in sorted(rows, key=lambda r: int(r["lci_database_sn"])):
        sn = int(r["lci_database_sn"])
        year = text(r.get("year"))
        ds = {
            "dataset_id": f"list-{sn}", "list_sn": sn,
            "name_ko": text(r["name_ko"]), "name_en": text(r.get("name_en")), "category": text(r["category"]),
            "developer": text(r.get("org")), "dev_year": int(year) if year and year.isdigit() else None, "version": text(r.get("version")),
            "has_xml": False, **{c: None for c in FILE_COLUMNS},
        }
        datasets.append(ds)
        link = links.get(sn)
        listed = text(r.get("zip_file")) or text(r.get("excel_file"))

        if not link or link["status"] != "exact":
            if link and link["status"] == "content_mismatch":
                owner = re.search(r"belongs_to:(\d+)", link.get("top3", ""))
                issue(ds, "file_missing", "warning", "사이트가 다른 데이터셋의 파일을 내려줘 파일 값을 넣지 않았습니다",
                      {"reason": "site_file_error", "belongs_to": int(owner[1]) if owner else None})
            elif not listed:
                issue(ds, "file_missing", "info", "목록에 다운로드 파일명이 없습니다", {"reason": "no_filename"})
            else:
                issue(ds, "file_missing", "info", "파일을 아직 받지 못했습니다", {"reason": "download_needed"})
            continue

        feat = features.get(link["file"]) or next((v for s, v in by_sha.items() if s.startswith(link["sha"])), None) or {}
        kind = link["kind"]
        ref = feat.get("ref_flow") or None
        if ref and ref.get("estimated") and roles.role_of(ds["name_ko"], ds["category"], seed) == "transport":
            # 수송의 출력은 제품이 아니라 서비스(사람·km, 톤·km)라 "양 1.0 비요소 출력" 추정이 맞지 않는다(T13.2)
            issue(ds, "ref_flow_estimate_skipped", "info", "수송 데이터셋은 기준 흐름을 추정하지 않음", {"estimated_name": ref.get("name")})
            ref = None
        ds.update(source_file=link["file"], source_hash=feat.get("sha") or link["sha"], has_xml=kind == "xml")
        if kind == "xml":
            ds.update(ilcd_uuid=text(feat.get("uuid")), reference_year=feat.get("reference_year"), geography=text(feat.get("geography")),
                      dataset_type=text(feat.get("dataset_type")), allocation=text(feat.get("allocation")), cutoff=text(feat.get("cutoff")),
                      tech_description=text(feat.get("tech")))
        else:
            ds["system_boundary"] = text(feat.get("boundary"))

        if not ref or (text(ref.get("name")) is None and text(ref.get("amount")) is None):
            issue(ds, "no_ref_flow", "warning", "기준흐름이 비어 있습니다", {"kind": kind})
        else:
            value, bad = amount(text(ref.get("amount")))
            ds.update(ref_flow_name=text(ref.get("name")), ref_flow_unit=text(ref.get("unit")), ref_flow_amount=value)
            if ds["ref_flow_unit"] is None:
                issue(ds, "unit_blank", "warning", "기준흐름 단위가 비어 있습니다")
            if ref.get("missing_flow_property"):
                issue(ds, "flow_property_missing", "warning", f"흐름 속성 정의 없음: {ref['missing_flow_property']}",
                      {"uuid": ref["missing_flow_property"]})
            if ref.get("estimated"):
                issue(ds, "ref_flow_estimated", "info", f"기준 흐름 추정: {ds['ref_flow_name']}(XML에 지정 없음)",
                      {"rule": "비요소 출력 중 양 1.0 인 교환이 하나뿐"})
            if ref.get("unit_source") == "table":
                issue(ds, "unit_from_table", "info", "기준 단위를 꾸러미 밖 흐름 속성 정의(같은 국가 DB 다른 꾸러미)에서 찾았습니다",
                      {"table": "app/data/ilcd_flow_properties.csv"})
            if bad:
                issue(ds, "ref_flow_bad_amount", "warning", "기준흐름 양이 숫자가 아닙니다", {"raw": ref.get("amount")})
            elif value is not None and value != 1:
                issue(ds, "ref_flow_amount_not_1", "info", "기준흐름 양이 1이 아닙니다",
                      {"amount": str(value), "unit": ds["ref_flow_unit"]})
        if kind == "xml":
            values, gwp_issues = gwp_values(feat.get("lcia"), ds["ref_flow_amount"])
            ds.update(values)
            for code, severity, message, detail in gwp_issues:
                issue(ds, code, severity, message, detail)
        if ds["system_boundary"] and GATE_TO_GATE.search(ds["system_boundary"]):
            issue(ds, "gate_to_gate", "info", "gate-to-gate 데이터셋입니다(원료가 빠진 공정 데이터)", {"raw": ds["system_boundary"]})
        elif kind == "xml" and feat.get("boundary_hint"):  # system_boundary 열은 XML 에 대해 NULL 그대로(원문 값만 넣는 열)
            issue(ds, "gate_to_gate", "info", "XML 설명에 gate-to-gate 표현이 있습니다(확인 필요)",
                  {"source": "xml_text", "excerpt": feat["boundary_hint"]})
        try:
            check = float(link.get("name_check") or "")
        except ValueError:
            check = None
        if check is not None and check < NAME_CHECK_MIN:
            issue(ds, "name_mismatch", "info", "파일 자기 이름과 목록 이름이 많이 다릅니다(번역 차이일 수 있음)",
                  {"name_check": check, "file": link["file"]})

    # ilcd_uuid 는 UNIQUE: 같은 uuid 는 가장 작은 sn 에만 둔다
    kept = {}
    for ds in datasets:  # sn 순서
        u = ds["ilcd_uuid"]
        if not u:
            continue
        if u in kept:
            ds["ilcd_uuid"] = None
            issue(ds, "duplicate_uuid", "warning", "같은 ILCD UUID가 다른 행에 이미 있어 비워 두었습니다", {"uuid": u, "kept_by": kept[u]})
        else:
            kept[u] = ds["list_sn"]
    return datasets, issues


def load(conninfo_, list_path=LIST, map_path=MAP, features_path=FEATURES, report_path=REPORT, dry_run=False):
    """적재하고 요약 dict 를 돌려준다. 실패하거나 dry_run 이면 아무것도 남기지 않는다."""
    datasets, issues = build(*read_inputs(list_path, map_path, features_path))
    ids = [d["dataset_id"] for d in datasets]
    with psycopg.connect(conninfo_) as conn:
        has_table = conn.execute("SELECT to_regclass('schema_migration')").fetchone()[0] is not None
        if not has_table or not conn.execute("SELECT 1 FROM schema_migration WHERE filename = %s", (MIGRATION,)).fetchone():
            raise SystemExit("0002가 적용되지 않았습니다. python -m app.db.migrate 를 먼저 실행하세요")
        if not conn.execute("SELECT 1 FROM schema_migration WHERE filename = %s", (ROLE_MIGRATION,)).fetchone():
            raise SystemExit("0006이 적용되지 않았습니다. python -m app.db.migrate 를 먼저 실행하세요")
        if not conn.execute("SELECT 1 FROM schema_migration WHERE filename = %s", (GWP_MIGRATION,)).fetchone():
            raise SystemExit("0009가 적용되지 않았습니다. python -m app.db.migrate 를 먼저 실행하세요")
        with conn.transaction(force_rollback=dry_run):
            # uuid 가 다른 행으로 옮겨 가는 재적재에서 UNIQUE 충돌이 나지 않게 먼저 비운다
            conn.execute("UPDATE lci_dataset SET ilcd_uuid = NULL WHERE dataset_id = ANY(%s)", (ids,))
            with conn.cursor() as cur:
                cur.executemany(UPSERT, [tuple(d[c] for c in COLUMNS) for d in datasets])
                roles.apply(conn, ids)  # 새 행에도 같은 역할 규칙을 적용한다
                if conn.execute("SELECT count(*) FROM lci_dataset WHERE dataset_id = ANY(%s) AND role IS NULL", (ids,)).fetchone()[0]:
                    raise SystemExit("적재 뒤 role 이 NULL 인 행이 있습니다")
                conn.execute("DELETE FROM dataset_issue WHERE dataset_id = ANY(%s)", (ids,))
                cur.executemany("INSERT INTO dataset_issue (dataset_id, code, severity, message, detail) VALUES (%s, %s, %s, %s, %s)",
                                [(i, c, s, m, Jsonb(d)) for i, c, s, m, d in issues])
            summary = summarize(conn, ids)
    summary["dry_run"] = dry_run
    if report_path:
        Path(report_path).write_text(report(summary), encoding="utf-8")
    return summary


def summarize(conn, ids):
    one = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE has_xml), count(source_file), count(ilcd_uuid), count(ref_flow_unit) "
        "FROM lci_dataset WHERE dataset_id = ANY(%s)", (ids,)).fetchone()
    gwp = conn.execute(
        "SELECT count(*) FILTER (WHERE gwp_total IS NOT NULL), count(*) FILTER (WHERE has_xml AND gwp_total IS NULL), "
        "(SELECT count(*) FROM dataset_issue WHERE code = 'gwp_no_ref' AND dataset_id = ANY(%s)) "
        "FROM lci_dataset WHERE dataset_id = ANY(%s)", (ids, ids)).fetchone()
    codes = conn.execute("SELECT code, severity, count(*) FROM dataset_issue WHERE dataset_id = ANY(%s) GROUP BY 1, 2 ORDER BY 1",
                         (ids,)).fetchall()
    reasons = conn.execute("SELECT detail->>'reason', count(*) FROM dataset_issue WHERE code = 'file_missing' AND dataset_id = ANY(%s) "
                           "GROUP BY 1 ORDER BY 1", (ids,)).fetchall()

    def sns(code):
        return [r[0] for r in conn.execute(
            "SELECT d.list_sn FROM dataset_issue i JOIN lci_dataset d USING (dataset_id) WHERE i.code = %s AND d.dataset_id = ANY(%s) "
            "ORDER BY d.list_sn", (code, ids)).fetchall()]

    return {"rows": one[0], "has_xml": one[1], "source_file": one[2], "ilcd_uuid": one[3], "ref_flow_unit": one[4],
            "gwp_with": gwp[0], "gwp_without_xml": gwp[1], "gwp_no_ref": gwp[2], "codes": codes, "reasons": reasons, "duplicate_uuid": sns("duplicate_uuid"), "no_ref_flow": sns("no_ref_flow")}


def report(s):
    def head(xs):
        return ", ".join(map(str, xs[:20])) + (f" … (전체 {len(xs)})" if len(xs) > 20 else "") if xs else "없음"

    lines = [
        "# ingest-report (자동 생성, git 제외)" + (" — dry-run(롤백함)" if s["dry_run"] else ""), "",
        f"- 총 행 {s['rows']}, has_xml {s['has_xml']}, source_file {s['source_file']}, ilcd_uuid {s['ilcd_uuid']}, ref_flow_unit {s['ref_flow_unit']}",
        f"- 배출계수 있음 {s['gwp_with']} / 없음 {s['gwp_without_xml']}(XML 있음 {s['has_xml']}) — 전체 {s['rows']}건 대비 있음 {s['gwp_with'] / s['rows']:.0%}",
        f"  - 없음 {s['gwp_without_xml']} 중 기준 흐름이 없어 비운 것(영향평가 결과는 있음, gwp_no_ref) {s['gwp_no_ref']}, 나머지는 XML에 영향평가 결과가 없음",
        "", "## 코드별 이슈", "", "| code | severity | 건수 |", "|---|---|---|",
        *[f"| {c} | {sev} | {n} |" for c, sev, n in s["codes"]],
        "", "## file_missing 이유별", "", *[f"- {r}: {n}" for r, n in s["reasons"]],
        "", f"- duplicate_uuid sn: {head(s['duplicate_uuid'])}",
        f"- no_ref_flow sn: {head(s['no_ref_flow'])}",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="목록 + 파일 단서를 lci_dataset 에 적재")
    ap.add_argument("--list", default=LIST)
    ap.add_argument("--map", default=MAP)
    ap.add_argument("--features", default=FEATURES)
    ap.add_argument("--dry-run", action="store_true", help="같은 계산을 하고 롤백한다")
    args = ap.parse_args(argv)
    try:
        summary = load(conninfo(), args.list, args.map, args.features, REPORT, dry_run=args.dry_run)
    except psycopg.OperationalError as e:
        raise SystemExit(f"DB에 접속하지 못했습니다: {e}") from e
    print(report(summary))
    print(f"리포트: {REPORT}")


if __name__ == "__main__":
    main()
