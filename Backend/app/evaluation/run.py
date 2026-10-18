"""평가 실행기. 같은 정답셋 위에서 케이스(C0·C1·C2 …)를 비교하고 DB 와 폴더에 결과를 남긴다.

  uv run --env-file ../.env python -m app.evaluation.run --gold <gold_id 또는 이름> --cases C0,C1,C2 [--split dev] [--final] [--out 폴더]

기본은 dev 분할만. test 분할은 --split test --final 둘 다 있어야 열리고, 열면 eval_run.config.test_opened = true.
리포트 JSON 은 A14 응답 모양(status, config, meta, gold_stats, metrics, ablation, errors)에 확장 키(cases, slices, coverage_accuracy, ci)를 더한다.
"""
import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg
import sklearn
from psycopg.types.json import Jsonb

from app.db.connection import conninfo
from app.embedder import DIM, OllamaEmbedder
from app.evaluation import metrics
from app.evaluation.cases import CASES, run_cases
from app.search import RRF_K

ROOT = Path(__file__).resolve().parents[3]
SEED = 42
TFIDF = {"analyzer": "char_wb", "ngram_range": [2, 4]}  # app.search.tfidf_rank 와 같은 값(기록용)
SMOKE_BANNER = "SMOKE — 성능 근거 아님"


def git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def index_hash(conn, version_id):
    """활성(또는 지정) 버전의 'dataset_id:text_hash' 를 정렬해 이은 sha256."""
    rows = conn.execute("SELECT dataset_id, text_hash FROM index_version_item WHERE version_id = %s", (version_id,)).fetchall()
    return hashlib.sha256("\n".join(sorted(f"{d}:{h}" for d, h in rows)).encode("utf-8")).hexdigest()


def find_gold(conn, gold):
    row = conn.execute("SELECT gold_id, name, sha256 FROM gold_set WHERE gold_id = %s", (gold,)).fetchone() or \
        conn.execute("SELECT gold_id, name, sha256 FROM gold_set WHERE name = %s ORDER BY created_at DESC LIMIT 1", (gold,)).fetchone()
    if not row:
        raise SystemExit(f"정답셋 {gold} 을 찾을 수 없습니다. python -m app.evaluation.gold load 로 먼저 적재하세요")
    return row


def load_labels(conn, gold_id, split):
    cols = ["label_id", "bom_text", "expected_dataset_id", "is_no_match", "hard_pair_group", "input_style", "label_source", "source",
            "expected_name", "category"]
    rows = conn.execute(
        "SELECT g.label_id, g.bom_text, g.expected_dataset_id, g.is_no_match, g.hard_pair_group, g.input_style, g.label_source, g.source, "
        "d.name_ko, d.category FROM gold_label g LEFT JOIN lci_dataset d ON d.dataset_id = g.expected_dataset_id "
        "WHERE g.gold_id = %s AND g.split = %s ORDER BY g.label_id", (gold_id, split)).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def reason(row, partners):
    """오답 사유 한 줄(자동 분류)."""
    if row["expected"] is None:
        return "정답 없음인데 후보를 냄"
    top1 = row["ranking"][0][0] if row["ranking"] else None
    if top1 and top1 in partners.get(row["hard_pair_group"], set()) - {row["expected"]}:
        return "같은 hard_pair_group의 짝이 앞섬"
    if top1 and row["names"].get(top1) == row["expected_name"]:
        return "동명 다른 버전이 앞섬"
    rank = metrics.rank_strict(row)
    return "정답이 상위 100에 없음" if rank is None else f"정답 순위 {rank}위"


def run_eval(conninfo_, embedder, gold, case_ids, split="dev", final=False, out=None, now=None, digest=None):
    if split == "test" and not final:
        raise SystemExit("test 분할은 --split test --final 둘 다 있어야 엽니다(튜닝에 쓰지 않았는지 기록하려는 장치)")
    if split not in ("dev", "test"):
        raise SystemExit(f"split 은 dev 또는 test: {split}")
    started = time.perf_counter()
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    with psycopg.connect(conninfo_) as conn:
        gold_id, gold_name, gold_sha = find_gold(conn, gold)
        labels = load_labels(conn, gold_id, split)
        if not labels:
            raise SystemExit(f"{gold_id} 의 {split} 분할에 행이 없습니다")
        results, index = run_cases(conn, embedder, [lab["bom_text"] for lab in labels], case_ids)
        names = {it["dataset_id"]: it["name"] for it in index["items"]}
        smoke = gold_name == "smoke" or all((lab["source"] or "").lower().startswith("smoke") for lab in labels)
        if digest is None:
            digest = embedder.model_digest() if hasattr(embedder, "model_digest") else (None, "임베더가 digest 를 주지 않음")
        model_versions = {
            "embed_model": embedder.model_name, "ollama_digest": digest[0], "ollama_digest_error": digest[1], "dim": DIM,
            "index_version_id": index["version_id"], "index_hash": index_hash(conn, index["version_id"]),
            "tfidf": TFIDF, "rrf_k": RRF_K, "seed": SEED, "gold_sha256": gold_sha, "split": split, "git_sha": git_sha(),
            "python": platform.python_version(), "scikit-learn": sklearn.__version__,
        }
        base = f"eval-{stamp}-{gold_id}-{split}"
        partners = {}
        for lab in labels:
            if lab["hard_pair_group"] and lab["expected_dataset_id"]:
                partners.setdefault(lab["hard_pair_group"], set()).add(lab["expected_dataset_id"])

        rows_by_case, cases_out, errors_all = {}, {}, []
        with conn.transaction():
            for c in case_ids:
                res = results[c]
                if res["state"] == "pending":
                    cases_out[c] = {"label": res["label"], "state": "pending", "strict": None, "name": None}
                    continue
                rows = [{"label_id": lab["label_id"], "query": lab["bom_text"], "expected": lab["expected_dataset_id"],
                         "expected_name": lab["expected_name"], "ranking": ranking, "names": names,
                         "input_style": lab["input_style"], "hard_pair_group": lab["hard_pair_group"],
                         "label_source": lab["label_source"], "category": lab["category"]} for lab, ranking in zip(labels, res["rankings"])]
                rows_by_case[c] = rows
                eval_id = f"{base}-{c}"
                config = {"case": c, "label": res["label"], "cases": case_ids, "split": split, "test_opened": split == "test",
                          "group": base, "smoke": smoke, "top": 100}
                conn.execute("INSERT INTO eval_run (eval_id, gold_id, config, model_versions) VALUES (%s, %s, %s, %s)",
                             (eval_id, gold_id, Jsonb(config), Jsonb(model_versions)))
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO eval_result (eval_id, label_id, predicted_dataset_id, gold_rank, confidence, top1_ok, top3_ok, rejected, "
                        "top_ids, top1_name_ok) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(eval_id, r["label_id"], r["ranking"][0][0] if r["ranking"] else None, metrics.rank_strict(r),
                          r["ranking"][0][1] if r["ranking"] else None, int(metrics.top1_ok(r)),
                          int(r["expected"] is not None and (metrics.rank_strict(r) or 99) <= 3), 0,
                          Jsonb([{"dataset_id": d, "score": s} for d, s in r["ranking"][:10]]),
                          int(metrics.top1_ok(r, "name")) if r["expected"] is not None else None) for r in rows])
                cases_out[c] = {"label": res["label"], "state": "measured", "eval_id": eval_id,
                                "strict": metrics.summarize(rows, "strict"), "name": metrics.summarize(rows, "name")}
                for r in rows:
                    if not metrics.top1_ok(r):
                        top1 = r["ranking"][0][0] if r["ranking"] else None
                        errors_all.append({"case": c, "id": r["label_id"], "query": r["query"],
                                           "gold_ids": [r["expected"]] if r["expected"] else [], "top1": top1,
                                           "top1_name": names.get(top1), "reason": reason(r, partners)})

    measured = [c for c in case_ids if cases_out[c]["state"] == "measured"]
    head = measured[-1] if measured else None  # A14 의 metrics·errors 는 마지막 실측 케이스(보통 C2)
    no_answer = sum(lab["expected_dataset_id"] is None for lab in labels)
    abstain = 0.0 if no_answer else None  # 늘 후보를 내므로 정답 없음 거부율은 0(정답 없음 행이 없으면 None)
    report = {
        "status": "done",
        "config": {"gold_id": gold_id, "cases": case_ids, "split": split, "final": final, "test_opened": split == "test", "smoke": smoke,
                   "head_case": head, "group": base},
        "meta": {"model": embedder.model_name, "index_hash": model_versions["index_hash"], "dict_version": None, "rules_version": None,
                 "seed": SEED, "elapsed_s": round(time.perf_counter() - started, 2)},
        "gold_stats": {"total": len(labels), "answerable": len(labels) - no_answer, "no_answer": no_answer,
                       "no_answer_ratio": no_answer / len(labels)},
        "metrics": {"top1": cases_out[head]["strict"]["top1"] if head else None, "top3": cases_out[head]["strict"]["top3"] if head else None,
                    "high_conf_error_rate": None, "abstain_reject_rate": abstain},
        "ablation": [{"step": f"{c} {cases_out[c]['label']}", "top1": cases_out[c]["strict"]["top1"] if cases_out[c]["strict"] else None,
                      "top3": cases_out[c]["strict"]["top3"] if cases_out[c]["strict"] else None,
                      "abstain_reject_rate": abstain if cases_out[c]["state"] == "measured" else None,
                      "state": cases_out[c]["state"]} for c in case_ids],
        "errors": [{k: e[k] for k in ("id", "query", "gold_ids", "top1", "reason")} for e in errors_all if e["case"] == head],
        "cases": cases_out,
        "slices": {c: metrics.slices(rows_by_case[c]) for c in measured},
        "coverage_accuracy": {c: metrics.coverage_accuracy(rows_by_case[c]) for c in measured},
        "ci": metrics.bootstrap({c: rows_by_case[c] for c in measured}, n=1000, seed=SEED) if measured else None,
        "model_versions": model_versions,
    }
    out = Path(out) if out else ROOT / "docs/LCA/data/eval" / base
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.md").write_text(report_md(report), encoding="utf-8")
    with open(out / "errors.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["case", "id", "query", "gold_ids", "top1", "top1_name", "reason"])
        w.writeheader()
        w.writerows([{**e, "gold_ids": ";".join(e["gold_ids"])} for e in errors_all])
    return report, out


def pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def num(v):
    return "—" if v is None else f"{v:.3f}"


def report_md(r):
    lines = []
    if r["config"]["smoke"]:
        lines += [f"# {SMOKE_BANNER}", "", "이 정답셋은 형식 확인용 스모크다. 아래 숫자를 성능 근거로 쓰지 않는다.", ""]
    mv = r["model_versions"]
    lines += [f"# 평가 리포트 {r['config']['group']}", "",
              f"- 정답셋 `{r['config']['gold_id']}` · 분할 `{r['config']['split']}` · test 열람 {r['config']['test_opened']}",
              f"- 행 {r['gold_stats']['total']} (정답 있음 {r['gold_stats']['answerable']}, 정답 없음 {r['gold_stats']['no_answer']})",
              f"- 모델 `{mv['embed_model']}` digest `{mv['ollama_digest']}`{' (' + mv['ollama_digest_error'] + ')' if mv['ollama_digest_error'] else ''}",
              f"- 인덱스 `{mv['index_version_id']}` hash `{mv['index_hash'][:16]}…` · TF-IDF {mv['tfidf']} · RRF k={mv['rrf_k']} · seed {mv['seed']}",
              f"- git `{mv['git_sha']}` · python {mv['python']} · scikit-learn {mv['scikit-learn']} · 걸린 시간 {r['meta']['elapsed_s']}초", ""]
    for level, title in (("strict", "strict (dataset_id 일치)"), ("name", "name-level (국문명 일치, 동명 접기)")):
        lines += [f"## 케이스 × 지표 — {title}", "", "| 케이스 | 상태 | Top-1 | Top-3 | Recall@5 | Recall@10 | MRR |", "|---|---|---|---|---|---|---|"]
        for c, v in r["cases"].items():
            s = v[level] or {}
            lines.append(f"| {c} {v['label']} | {v['state']} | {pct(s.get('top1'))} | {pct(s.get('top3'))} | {pct(s.get('recall@5'))} | "
                         f"{pct(s.get('recall@10'))} | {num(s.get('mrr'))} |")
        lines.append("")
    ci = r["ci"]
    if ci and ci["cases"]:
        lines += [f"## 부트스트랩 95% 구간 (strict, {ci['n']}회, seed {ci['seed']}, 정답 있는 {ci.get('rows', 0)}행)", "",
                  "| 케이스 | Top-1 | Top-3 | MRR |", "|---|---|---|---|"]
        for c, v in ci["cases"].items():
            lines.append(f"| {c} | {pct(v['top1'][0])} ~ {pct(v['top1'][1])} | {pct(v['top3'][0])} ~ {pct(v['top3'][1])} | "
                         f"{num(v['mrr'][0])} ~ {num(v['mrr'][1])} |")
        if ci["diff"]:
            lines += ["", "| 차이(대응 비교) | Top-1 | Top-3 | MRR |", "|---|---|---|---|"]
            for k, v in ci["diff"].items():
                lines.append(f"| {k} | {pct(v['top1'][0])} ~ {pct(v['top1'][1])} | {pct(v['top3'][0])} ~ {pct(v['top3'][1])} | "
                             f"{num(v['mrr'][0])} ~ {num(v['mrr'][1])} |")
        lines.append("")
    for c, sl in r["slices"].items():
        lines += [f"## 조각 — {c} (strict)", "", "| 조각 | 값 | 행 | 정답 있음 | Top-1 | Top-3 | MRR | |", "|---|---|---|---|---|---|---|---|"]
        for name, vals in sl.items():
            for value, s in vals.items():
                lines.append(f"| {name} | {value} | {s['n']} | {s['answerable']} | {pct(s['top1'])} | {pct(s['top3'])} | {num(s['mrr'])} | "
                             f"{'표본 적음' if s['small'] else ''} |")
        lines.append("")
    for c, rows in r["coverage_accuracy"].items():
        lines += [f"## 커버리지-정확도 — {c} (1위 점수 내림차순으로 상위 p%만 받아들임, 정답 없음 행은 오답)", "",
                  "| 커버리지 | 받아들인 행 | 최저 점수 | 정확도(strict) | 오답 | 정확도(name) | 오답 |", "|---|---|---|---|---|---|---|"]
        for x in rows:
            lines.append(f"| {x['coverage']}% | {x['accepted']} | {num(x['min_score'])} | {pct(x['accuracy_strict'])} | {x['errors_strict']} | "
                         f"{pct(x['accuracy_name'])} | {x['errors_name']} |")
        lines.append("")
    lines += [f"## 오답 사례 — {r['config']['head_case']} (전체 케이스는 errors.csv)", "", "| id | 입력 | 정답 | 1순위 | 이유 |", "|---|---|---|---|---|"]
    lines += [f"| {e['id']} | {e['query']} | {', '.join(e['gold_ids']) or '정답 없음'} | {e['top1']} | {e['reason']} |" for e in r["errors"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="평가 실행")
    ap.add_argument("--gold", required=True, help="gold_id 또는 정답셋 이름(같은 이름이면 가장 최근)")
    ap.add_argument("--cases", default="C0,C1,C2")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--final", action="store_true", help="test 분할을 연다(기록이 남는다)")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    case_ids = [c.strip() for c in args.cases.split(",") if c.strip()]
    try:
        with psycopg.connect(conninfo()) as conn:
            model = conn.execute("SELECT model_name FROM index_version WHERE active").fetchone()
        embedder = OllamaEmbedder((model[0] if model else "ollama:bge-m3").split(":", 1)[-1])
        report, out = run_eval(conninfo(), embedder, args.gold, case_ids, args.split, args.final, args.out)
    except psycopg.OperationalError as e:
        raise SystemExit(f"DB에 접속하지 못했습니다: {e}") from e
    print(report_md(report))
    print(f"결과: {out}")


if __name__ == "__main__":
    main()
