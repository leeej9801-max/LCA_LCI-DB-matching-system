"""외부 결과(Colab 재순위·판정) 가져오기(E2). 형식: docs/LCA/spec/external-result.schema.json

  uv run --env-file ../.env python -m app.evaluation.import_external <결과파일> [--export <내보낸 파일>]

검증을 하나라도 어기면 전부 거부한다(DB 에 아무것도 쓰지 않는다):
export_id 가 DB 에 있고 export_sha256 이 DB 기록·내보낸 파일의 sha256 과 같음 / label_id 가 그 내보내기에 있음 / 행 누락·중복 없음 /
ranking·picked_dataset_id 의 id 가 그 행의 내보낸 후보 안에 있음(새 id 를 만들어 내지 못함) / kind 별 필수 값.
내보낸 파일은 --export 로 주거나, 없으면 app.evaluation.export_candidates.EXPORT_DIR/<export_id>.json 에서 찾는다.
run_id = 'x-<kind>-<결과파일 sha256 앞 12자>' — 같은 파일을 다시 가져오면 새로 만들지 않는다. 평가: --cases <base>+X:<run_id>
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from app.db.connection import conninfo
from app.evaluation.export_candidates import EXPORT_DIR

KINDS = ("rerank", "judge")
DECISIONS = ("pick", "none")


def validate(doc, export_doc, db_sha):
    """오류 메시지 목록(빈 목록이면 통과). doc: 결과 파일, export_doc: 내보낸 파일(dict), db_sha: eval_export.sha256."""
    errors = []
    for k in ("export_id", "export_sha256", "run", "results"):
        if k not in doc:
            errors.append(f"필수 키가 없습니다: {k}")
    if errors:
        return errors
    if doc["export_id"] != export_doc.get("export_id"):
        errors.append(f"export_id {doc['export_id']} 가 내보낸 파일({export_doc.get('export_id')})과 다릅니다")
    if doc["export_sha256"] != db_sha:
        errors.append("export_sha256 이 DB 의 내보내기 기록과 다릅니다(다른 파일로 계산했거나 파일이 바뀜)")
    run = doc["run"] if isinstance(doc["run"], dict) else {}
    kind = run.get("kind")
    if kind not in KINDS:
        errors.append(f"run.kind 는 {'·'.join(KINDS)} 중 하나: {kind!r}")
    if not run.get("model"):
        errors.append("run.model 이 비어 있습니다")
    if not isinstance(run.get("params", {}), dict):
        errors.append("run.params 는 객체여야 합니다")
    cands = {r["label_id"]: {c["dataset_id"] for c in r["candidates"]} for r in export_doc.get("rows", [])}
    seen = set()
    for i, r in enumerate(doc["results"] if isinstance(doc["results"], list) else []):
        lid = r.get("label_id")
        where = f"results[{i}] label_id {lid}"
        if lid not in cands:
            errors.append(f"{where}: 그 내보내기에 없는 행")
            continue
        if lid in seen:
            errors.append(f"{where}: 중복")
        seen.add(lid)
        ranking = r.get("ranking") or []
        if not isinstance(ranking, list) or not all(isinstance(x, list) and len(x) == 2 and isinstance(x[1], (int, float)) for x in ranking):
            errors.append(f"{where}: ranking 은 [[dataset_id, score], ...]")
            ranking = []
        bad = [x[0] for x in ranking if x[0] not in cands[lid]]
        if bad:
            errors.append(f"{where}: 내보낸 후보에 없는 id {bad[:3]}")
        if kind == "rerank" and not ranking:
            errors.append(f"{where}: rerank 는 ranking 이 필요합니다")
        if kind == "judge":
            decision, picked = r.get("decision"), r.get("picked_dataset_id")
            if decision not in DECISIONS:
                errors.append(f"{where}: judge 는 decision 이 {'·'.join(DECISIONS)} 중 하나여야 합니다: {decision!r}")
            elif decision == "pick" and picked not in cands[lid]:
                errors.append(f"{where}: decision=pick 인데 picked_dataset_id({picked!r})가 내보낸 후보에 없습니다")
            elif decision == "none" and picked:
                errors.append(f"{where}: decision=none 인데 picked_dataset_id 가 있습니다")
        if r.get("latency_ms") is not None and not isinstance(r["latency_ms"], int):
            errors.append(f"{where}: latency_ms 는 정수")
    missing = sorted(set(cands) - seen)
    if missing:
        errors.append(f"결과가 없는 행 {len(missing)}개(예: {missing[:5]})")
    return errors


def run_id_of(doc_bytes, kind):
    return f"x-{kind}-{hashlib.sha256(doc_bytes).hexdigest()[:12]}"


def import_file(conninfo_, path, export_path=None):
    """(run_id, 새로 넣었는가). 검증 오류가 있으면 SystemExit(아무것도 쓰지 않음)."""
    data = Path(path).read_bytes()
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SystemExit(f"결과 파일을 JSON 으로 읽지 못했습니다: {e}") from e
    if not isinstance(doc, dict) or "export_id" not in doc:
        raise SystemExit("결과 파일에 export_id 가 없습니다")
    with psycopg.connect(conninfo_) as conn:
        row = conn.execute("SELECT sha256 FROM eval_export WHERE export_id = %s", (doc["export_id"],)).fetchone()
        if not row:
            raise SystemExit(f"내보내기 {doc['export_id']} 기록이 DB 에 없습니다")
        ep = Path(export_path) if export_path else EXPORT_DIR / f"{doc['export_id']}.json"
        if not ep.exists():
            raise SystemExit(f"내보낸 파일을 찾지 못했습니다: {ep} (--export 로 지정)")
        export_bytes = ep.read_bytes()
        if hashlib.sha256(export_bytes).hexdigest() != row[0]:
            raise SystemExit(f"내보낸 파일 {ep} 의 sha256 이 DB 기록과 다릅니다(파일이 바뀜)")
        errors = validate(doc, json.loads(export_bytes.decode("utf-8")), row[0])
        if errors:
            raise SystemExit(f"외부 결과 오류 {len(errors)}건 — 가져오지 않았습니다\n" + "\n".join(f"  {e}" for e in errors))
        run = doc["run"]
        run_id = run_id_of(data, run["kind"])
        if conn.execute("SELECT 1 FROM eval_external_run WHERE run_id = %s", (run_id,)).fetchone():
            return run_id, False
        with conn.transaction():
            conn.execute("INSERT INTO eval_external_run (run_id, export_id, kind, model, params, prompt_sha256, structure) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                         (run_id, doc["export_id"], run["kind"], run["model"], Jsonb(run.get("params") or {}), run.get("prompt_sha256"), run.get("structure")))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO eval_external_result (run_id, label_id, ranking, decision, picked_dataset_id, reason, confidence, latency_ms) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    [(run_id, r["label_id"], Jsonb(r.get("ranking") or []), r.get("decision"), r.get("picked_dataset_id"), r.get("reason"),
                      r.get("confidence"), r.get("latency_ms")) for r in doc["results"]])
    return run_id, True


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="외부 결과 가져오기")
    ap.add_argument("result")
    ap.add_argument("--export", help="내보낸 후보 파일(기본: EXPORT_DIR/<export_id>.json)")
    args = ap.parse_args(argv)
    try:
        run_id, created = import_file(conninfo(), args.result, args.export)
    except psycopg.OperationalError as e:
        raise SystemExit(f"DB에 접속하지 못했습니다: {e}") from e
    print(f"{run_id} {'가져옴' if created else '같은 파일이 이미 있어 그대로 둠'} — 평가: --cases <base>+X:{run_id}")


if __name__ == "__main__":
    main()
