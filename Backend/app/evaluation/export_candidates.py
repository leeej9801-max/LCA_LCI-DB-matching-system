"""외부 계산(Colab 재순위·판정)용 후보 내보내기(E2).

  uv run --env-file ../.env python -m app.evaluation.export_candidates --gold dev --split dev --base C2+D+V --top 30 [--out 파일] [--final]

행마다 label_id, query(bom_text), spec, unit, input_role(정답셋에는 없어 null), inferred_role(Veto 추정), 후보 목록.
정답 관련 값(expected·a_accept·s_accept·label_type·note)은 읽지도 넣지도 않는다. 파일 sha256 은 eval_export 에 남는다.
--split test 는 --final 이 함께 있어야 하고, 그 기록(split='test')이 eval_export 에 남는다.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import psycopg

from app.db.connection import conninfo
from app.embedder import OllamaEmbedder
from app.evaluation.cases import parse_case, run_cases
from app.evaluation.run import ROOT, find_gold, index_hash
from app.roles import LABEL

EXPORT_DIR = ROOT / "docs/LCA/data/eval/exports"  # 가져오기가 export_id 로 이 폴더의 파일을 찾는다
# 내보내는 파일에 절대 들어가면 안 되는 키(시험으로 검사)
FORBIDDEN = {"expected", "expected_dataset_id", "expected_name", "expected_role", "a_accept", "s_accept", "label_type", "note", "is_no_match",
             "hard_pair_group", "decided_by"}


def export_rows(labels, rankings, meta, datasets, top):
    """labels: [{label_id, bom_text, spec, unit}] (정답 열 없이 읽은 것). datasets: {dataset_id: {name_ko, name_en, category, role, org, year}}."""
    out = []
    for lab, ranking, m in zip(labels, rankings, meta):
        out.append({"label_id": lab["label_id"], "query": lab["bom_text"], "spec": lab["spec"], "unit": lab["unit"], "input_role": None,
                    "inferred_role": m["inferred_role"],
                    "candidates": [{"dataset_id": d, "rank": i, "score": s, **datasets[d]} for i, (d, s) in enumerate(ranking[:top], 1)]})
    return out


def export(conninfo_, embedder, gold, split, base, top, out=None, final=False, now=None):
    if split not in ("dev", "test"):
        raise SystemExit(f"split 은 dev 또는 test: {split}")
    if split == "test" and not final:
        raise SystemExit("test 분할 내보내기는 --split test --final 둘 다 있어야 합니다(test 열람으로 기록된다)")
    if top < 1:
        raise SystemExit(f"--top 은 1 이상: {top}")
    p = parse_case(base)
    if p["pending"] or p["run"]:
        raise SystemExit(f"내보내기 기준은 C0·C1·C2 와 G·D·V 조합만: {base}")
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    with psycopg.connect(conninfo_) as conn:
        gold_id, _, _ = find_gold(conn, gold)
        labels = [dict(zip(("label_id", "bom_text", "spec", "unit"), r)) for r in conn.execute(
            "SELECT label_id, bom_text, spec, unit FROM gold_label WHERE gold_id = %s AND split = %s ORDER BY label_id", (gold_id, split)).fetchall()]
        if not labels:
            raise SystemExit(f"{gold_id} 의 {split} 분할에 행이 없습니다")
        results, index = run_cases(conn, embedder, [lab["bom_text"] for lab in labels], [p["canonical"]])  # 검색 깊이는 평가와 같은 100, 내보낼 때만 top 개로 자른다
        res = results[p["canonical"]]
        datasets = {d: {"name_ko": n, "name_en": en, "category": cat, "role": LABEL.get(role), "org": org, "year": year}
                    for d, n, en, cat, role, org, year in conn.execute(
                        "SELECT dataset_id, name_ko, name_en, category, role, developer, dev_year FROM lci_dataset").fetchall()}
        export_id = f"exp-{stamp}-{gold_id}-{split}-{p['canonical']}"
        doc = {"export_id": export_id, "gold_id": gold_id, "split": split, "base_case": p["canonical"], "top": top,
               "index_version_id": index["version_id"], "index_hash": index_hash(conn, index["version_id"]),
               "created_at": (now or datetime.now()).isoformat(timespec="seconds"),
               "rows": export_rows(labels, res["rankings"], res["meta"], datasets, top)}
        data = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
        sha = hashlib.sha256(data).hexdigest()
        path = Path(out) if out else EXPORT_DIR / f"{export_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        with conn.transaction():
            conn.execute("INSERT INTO eval_export (export_id, gold_id, split, base_case, top, sha256) VALUES (%s, %s, %s, %s, %s, %s)",
                         (export_id, gold_id, split, p["canonical"], top, sha))
    return export_id, sha, path


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="외부 계산용 후보 내보내기")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--base", default="C2+D+V")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--out")
    ap.add_argument("--final", action="store_true", help="test 분할을 연다(기록이 남는다)")
    args = ap.parse_args(argv)
    try:
        with psycopg.connect(conninfo()) as conn:
            model = conn.execute("SELECT model_name FROM index_version WHERE active").fetchone()
        embedder = OllamaEmbedder((model[0] if model else "ollama:bge-m3").split(":", 1)[-1])
        export_id, sha, path = export(conninfo(), embedder, args.gold, args.split, args.base, args.top, args.out, args.final)
    except psycopg.OperationalError as e:
        raise SystemExit(f"DB에 접속하지 못했습니다: {e}") from e
    print(f"{export_id}\n  파일 {path}\n  sha256 {sha}")


if __name__ == "__main__":
    main()
