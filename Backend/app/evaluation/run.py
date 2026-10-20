"""평가 실행기. 같은 정답셋 위에서 케이스(C0·C1·C2 …)를 비교하고 DB 와 폴더에 결과를 남긴다.

  uv run --env-file ../.env python -m app.evaluation.run --gold <gold_id 또는 이름> --cases C0,C1,C2 [--split dev] [--final] [--out 폴더]
  케이스 표기(E2): 기준 C0·C1·C2 + 요소 G·D·V·X:<run_id> (예: C2+D+V, C1+G+D+V, C4+X:x-rerank-…). 자세한 것은 app/evaluation/cases.py

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

from app.bom.match import NO_ANSWER_CONFIDENCE, confidence  # 앱의 신뢰도·no_answer 규칙을 그대로 쓴다(여기서 다시 쓰지 않는다)
from app.db.connection import conninfo
from app.embedder import DIM, OllamaEmbedder
from app.bom import lexicon
from app.bom.infer_role import MATERIAL_KEYWORDS
from app.evaluation import confidence_rules, metrics
from app.evaluation.cases import VETO_EXCLUDE, ladder_key, run_cases
from app.roles import LABEL as ROLE_LABEL
from app.search import RRF_K

ROOT = Path(__file__).resolve().parents[3]
SEED = 42
TFIDF = {"analyzer": "char_wb", "ngram_range": [2, 4]}  # app.search.tfidf_rank 와 같은 값(기록용)
SMOKE_BANNER = "SMOKE — 성능 근거 아님"
# E1: 기존 열 뒤에 행별 신뢰도·순위 열. rows.csv 는 모든 행(정답 행 포함)에 판정·조각 열을 더한다
ERROR_COLS = ["case", "id", "query", "gold_ids", "top1", "top1_name", "reason", "confidence", "rank_tfidf", "rank_dense", "score_dense", "gold_rank"]
ROW_COLS = ERROR_COLS + ["top1_ok_A", "top1_ok_strict", "label_type", "input_style", "expected_role",
                         # E2: 1·2위 밀집 점수 차, 사전 확장, Veto 추정 역할·1위 변화, 외부 판정, 이 케이스의 no_answer 판정
                         "gap_dense", "query_expanded", "lexicon_hits", "inferred_role", "veto_changed", "decision", "no_answer"]
# E2b: 기본으로 넣는 짝 비교(기준, 비교 대상; 케이스 표기는 canonical). D 대 Ds 의 차이 = dev 에서 본 과적합 가능분, V 대 Vd = 제외형 대 강등형
PAIRS_EXTRA = (("C2+D+V", "C2+Ds+V"), ("C2+D+V", "C2+D+Vd"))


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
            "expected_name", "category", "product", "label_type", "a_accept", "s_accept", "decided_by", "expected_role"]
    rows = conn.execute(
        "SELECT g.label_id, g.bom_text, g.expected_dataset_id, g.is_no_match, g.hard_pair_group, g.input_style, g.label_source, g.source, "
        "d.name_ko, d.category, g.product, g.label_type, g.a_accept, g.s_accept, g.decided_by, d.role FROM gold_label g LEFT JOIN lci_dataset d ON d.dataset_id = g.expected_dataset_id "
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
        # 케이스마다 그 케이스가 쓴 TF-IDF·밀집 두 목록을 같이 돌려받는다 → 신뢰도·no_answer 판정은 그 두 목록에서 1위의 순위로(앱과 같은 규칙)
        results, index = run_cases(conn, embedder, [lab["bom_text"] for lab in labels], case_ids, label_ids=[lab["label_id"] for lab in labels])
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

        rows_by_case, cases_out, errors_all, rows_all, no_answer_c2, levels_c2 = {}, {}, [], [], None, None
        no_answer_by_case, rules_by_case, external_runs = {}, {}, {}
        recall_by_case, lexicon_by_case, veto_hurt_by_case, canon_of = {}, {}, {}, {}
        role_of = dict(conn.execute("SELECT dataset_id, role FROM lci_dataset").fetchall())
        with conn.transaction():
            for c in case_ids:
                res = results[c]
                if res["state"] == "pending":
                    cases_out[c] = {"label": res["label"], "state": "pending", "strict": None, "name": None}
                    continue
                rows = [{"label_id": lab["label_id"], "query": lab["bom_text"], "expected": lab["expected_dataset_id"],
                         "expected_name": lab["expected_name"], "ranking": ranking, "names": names,
                         "input_style": lab["input_style"], "hard_pair_group": lab["hard_pair_group"],
                         "label_source": lab["label_source"], "category": lab["category"], "product": lab["product"],
                         "label_type": lab["label_type"], "a_accept": lab["a_accept"], "s_accept": lab["s_accept"],
                         "expected_role": ROLE_LABEL.get(lab["expected_role"])}
                        for lab, ranking in zip(labels, res["rankings"])]
                comps = list(zip(res["tfidf"], res["dense"], res["rankings"]))
                if res["decisions"] is not None:  # 외부 판정(judge): decision='none' 이면 no_answer
                    flags, flag_rule = [d == "none" for d in res["decisions"]], "외부 판정(judge) decision='none' 이면 no_answer"
                else:
                    flags = [metrics.says_no_answer(t, dn, r, confidence, NO_ANSWER_CONFIDENCE) for t, dn, r in comps]
                    flag_rule = f"앱과 같은 판정: 1위의 TF-IDF·밀집 순위 → confidence() == {NO_ANSWER_CONFIDENCE!r} 이면 no_answer"
                no_answer_by_case[c] = {"case": c, "rule": flag_rule, **metrics.no_answer_table(rows, flags)}
                if c == "C2":
                    no_answer_c2 = {**no_answer_by_case[c], "rule": f"앱과 같은 판정: C2 1위의 C0·C1 순위 → confidence() == {NO_ANSWER_CONFIDENCE!r} 이면 no_answer"}
                    levels = [metrics.top1_level(t, dn, r, confidence) for t, dn, r in comps]
                    levels_c2 = {"case": c, "rule": "C2 1위의 신뢰도 등급(앱 confidence)별 1위 정답률. 정답 없음 행은 오답",
                                 "levels": metrics.level_table(rows, levels)}
                if res["external"]:
                    external_runs[c] = res["external"]
                rows_by_case[c] = rows
                canon_of[res["canonical"]] = c
                recall_by_case[c] = {lv: metrics.recall_at(rows, lv) for lv in ("A", "S")}
                if res["lexicon_mode"]:
                    lexicon_by_case[c] = lexicon_hit_rates(res["meta"], res["lexicon_mode"])
                if res["before_veto"] is not None:  # Veto(제외·강등) 뒤 정답 순위(A)가 나빠진 행
                    veto_hurt_by_case[c] = veto_hurt(rows, res["before_veto"], res["meta"], role_of)
                eval_id = f"{base}-{c}"
                config = {"case": c, "label": res["label"], "canonical": res["canonical"], "cases": case_ids, "split": split,
                          "test_opened": split == "test", "group": base, "smoke": smoke, "top": 100, "external": res["external"],
                          "lexicon": {"synonyms": len(lexicon.SYNONYMS), "form_words": list(lexicon.FORM_WORDS)} if "+D" in res["canonical"] else None,
                          "veto_material_keywords": list(MATERIAL_KEYWORDS) if "+V" in res["canonical"] else None}
                conn.execute("INSERT INTO eval_run (eval_id, gold_id, config, model_versions) VALUES (%s, %s, %s, %s)",
                             (eval_id, gold_id, Jsonb(config), Jsonb(model_versions)))
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO eval_result (eval_id, label_id, predicted_dataset_id, gold_rank, confidence, top1_ok, top3_ok, rejected, "
                        "top_ids, top1_name_ok) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(eval_id, r["label_id"], r["ranking"][0][0] if r["ranking"] else None, metrics.rank_strict(r),
                          r["ranking"][0][1] if r["ranking"] else None, int(metrics.top1_ok(r)),
                          int(r["expected"] is not None and (metrics.rank_strict(r) or 99) <= 3), int(bool(flags and flags[i])),
                          Jsonb([{"dataset_id": d, "score": s} for d, s in r["ranking"][:10]]),
                          int(metrics.top1_ok(r, "name")) if r["expected"] is not None else None) for i, r in enumerate(rows)])
                cases_out[c] = {"label": res["label"], "state": "measured", "eval_id": eval_id,
                                **{lv: metrics.summarize(rows, lv) for lv in metrics.LEVELS}}
                recs = []
                for i, (r, (t, dn, _)) in enumerate(zip(rows, comps)):
                    top1 = r["ranking"][0][0] if r["ranking"] else None
                    ok = metrics.top1_ok(r)
                    meta = res["meta"][i]
                    rec = {"case": c, "id": r["label_id"], "query": r["query"], "gold_ids": [r["expected"]] if r["expected"] else [], "top1": top1,
                           "top1_name": names.get(top1), "reason": "" if ok else reason(r, partners), **metrics.row_detail(r, t, dn, confidence),
                           "top1_ok_A": int(metrics.top1_ok(r, "A")), "top1_ok_strict": int(ok), "label_type": r["label_type"],
                           "input_style": r["input_style"], "expected_role": r["expected_role"], "gap_dense": metrics.dense_gap(dn),
                           "query_expanded": meta["query_expanded"], "lexicon_hits": ";".join(meta["lexicon_hits"]), "inferred_role": meta["inferred_role"],
                           "veto_changed": None if res["veto_changed"] is None else int(res["veto_changed"][i]),
                           "decision": res["decisions"][i] if res["decisions"] is not None else None, "no_answer": int(flags[i]),
                           "is_none": int(r["expected"] is None)}
                    recs.append(rec)
                    if not ok:
                        errors_all.append(rec)
                rows_all += recs
                rules_by_case[c] = confidence_rules.compare([{**x, "ok_A": x["top1_ok_A"], "ok_strict": x["top1_ok_strict"]} for x in recs])

    measured = [c for c in case_ids if cases_out[c]["state"] == "measured"]
    pair_base = measured[0] if measured else None  # 짝 비교 기준 = --cases 의 첫 실측 케이스
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
                       "no_answer_ratio": no_answer / len(labels),
                       "s_applicable": sum(metrics.applicable(r, "S") for r in next(iter(rows_by_case.values()), [])),
                       "gold_name": gold_name, **{k: v for k, v in metrics.gold_header(labels).items() if k != "rows"}},
        "metrics": {"top1": cases_out[head]["strict"]["top1"] if head else None, "top3": cases_out[head]["strict"]["top3"] if head else None,
                    "high_conf_error_rate": high_conf_error(levels_c2), "abstain_reject_rate": abstain},
        "ablation": [{"step": f"{c} {cases_out[c]['label']}", "top1": cases_out[c]["strict"]["top1"] if cases_out[c]["strict"] else None,
                      "top3": cases_out[c]["strict"]["top3"] if cases_out[c]["strict"] else None,
                      "abstain_reject_rate": abstain if cases_out[c]["state"] == "measured" else None,
                      "state": cases_out[c]["state"]} for c in sorted(case_ids, key=ladder_key)],
        "errors": [{k: e[k] for k in ("id", "query", "gold_ids", "top1", "reason")} for e in errors_all if e["case"] == head],
        "cases": cases_out,
        "slices": {c: metrics.slices(rows_by_case[c]) for c in measured},
        "coverage_accuracy": {c: metrics.coverage_accuracy(rows_by_case[c]) for c in measured},
        "ci": metrics.bootstrap({c: rows_by_case[c] for c in measured}, n=1000, seed=SEED) if measured else None,
        "ci_levels": {lv: metrics.bootstrap({c: rows_by_case[c] for c in measured}, n=1000, seed=SEED, level=lv) for lv in ("A", "S")} if measured else None,
        "no_answer_judgement": no_answer_c2,
        "confidence_levels": levels_c2,
        "no_answer_by_case": no_answer_by_case,
        "paired": paired(rows_by_case, pair_base),
        "pair_counts": pair_counts(rows_by_case, pair_base),
        "paired_extra": paired_extra(rows_by_case, canon_of),
        "recall_at_k": recall_by_case,
        "lexicon_hits": lexicon_by_case,
        "veto_hurt": veto_hurt_by_case,
        "confidence_rules": rules_by_case,
        "external_runs": external_runs,
        "model_versions": model_versions,
    }
    out = Path(out) if out else ROOT / "docs/LCA/data/eval" / base
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.md").write_text(report_md(report), encoding="utf-8")
    for name, recs, cols in (("errors.csv", errors_all, ERROR_COLS), ("rows.csv", rows_all, ROW_COLS)):
        with open(out / name, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows([{**e, "gold_ids": ";".join(e["gold_ids"])} for e in recs])
    with open(out / "confidence_rules.csv", "w", encoding="utf-8-sig", newline="") as f:  # 후보 전체(리포트 md 는 요약)
        w = csv.writer(f)
        w.writerow(["case", "candidate", "high_rows", "high_coverage", "high_cov_lo", "high_cov_hi", "high_error_A", "high_err_lo", "high_err_hi",
                    "mid_rows", "mid_acc_A", "low_rows", "low_acc_A", "selected"])
        for c, cmp_ in rules_by_case.items():
            for t in cmp_["candidates"]:
                ci = t["ci"] or {"high_coverage": [None, None], "high_error_A": [None, None]}
                lv = t["levels"]
                w.writerow([c, t["name"], lv["높음"]["rows"], t["high_coverage"], *ci["high_coverage"], t["high_error_A"], *ci["high_error_A"],
                            lv["보통"]["rows"], lv["보통"]["acc_A"], lv["낮음"]["rows"], lv["낮음"]["acc_A"], int(t["name"] == cmp_["selected"])])
    return report, out


def _pair(ref_rows, rows):
    ref = {r["label_id"]: metrics.top1_ok(r, "A") for r in ref_rows}
    got = {r["label_id"]: metrics.top1_ok(r, "A") for r in rows}
    return {"new_right": [i for i in ref if got[i] and not ref[i]], "new_wrong": [i for i in ref if ref[i] and not got[i]]}


def pair_counts(rows_by_case, base):
    """기준 케이스(--cases 첫 케이스) 대비 행 단위 변화 개수(E4b): {case: {A|S: {new_right, new_wrong, same, rows}}}. 분모는 그 수준에 드는 행."""
    if base not in rows_by_case:
        return None
    out = {}
    for c, rows in rows_by_case.items():
        if c == base:
            continue
        out[c] = {}
        for lv in ("A", "S"):
            ref = {r["label_id"]: metrics.top1_ok(r, lv) for r in rows_by_case[base] if metrics.applicable(r, lv)}
            got = {r["label_id"]: metrics.top1_ok(r, lv) for r in rows if metrics.applicable(r, lv)}
            nr = sum(got[i] and not ref[i] for i in ref)
            nw = sum(ref[i] and not got[i] for i in ref)
            out[c][lv] = {"new_right": nr, "new_wrong": nw, "same": len(ref) - nr - nw, "rows": len(ref)}
    return {"base": base, "cases": out}


def paired(rows_by_case, base):
    """기준 케이스 대비 같은 행끼리의 A 수준 1위 비교: {case: {new_right: [label_id], new_wrong: [label_id]}}. 기준이 없으면 None."""
    if base not in rows_by_case:
        return None
    return {"base": base, "level": "A",
            "cases": {c: _pair(rows_by_case[base], rows) for c, rows in rows_by_case.items() if c != base}}


def paired_extra(rows_by_case, canon_of, pairs=PAIRS_EXTRA):
    """PAIRS_EXTRA 중 두 케이스가 모두 돌았을 때만: [{base, case, new_right, new_wrong}]. 표기(C4 등)가 달라도 canonical 로 찾는다."""
    return [{"base": canon_of[a], "case": canon_of[b], **_pair(rows_by_case[canon_of[a]], rows_by_case[canon_of[b]])}
            for a, b in pairs if a in canon_of and b in canon_of]


def veto_hurt(rows, before, meta, role_of):
    """Veto 전후 비교(E2b). target = 정답(a_accept)이 거를/강등할 역할의 데이터셋이라 밀린 행(순위 하락), other = 그 밖의 이유로 순위가 나빠진 행
    (필터로 목록이 바뀌어 RRF 순서가 달라진 경우 등)."""
    target, other = [], []
    for r, b, m in zip(rows, before, meta):
        if not metrics.rank_worse(dict(r, ranking=b), r):
            continue
        excluded = VETO_EXCLUDE.get(m["inferred_role"])
        (target if excluded and any(role_of.get(d) == excluded for d in metrics.accept_ids(r, "A")) else other).append(r["label_id"])
    return {"n": len(target), "ids": target, "other_n": len(other), "other_ids": other}


def lexicon_hit_rates(meta, mode):
    """사전 적중 행 비율(E2b). 적중 ≥1인 행 수를 전체와 출처별로. meta 의 lexicon_hits 는 expand 의 항목 목록."""
    n = len(meta)
    hit = lambda origin=None: sum(any(origin is None or lexicon.hit_origin(h) == origin for h in m["lexicon_hits"]) for m in meta)  # noqa: E731
    return {"mode": mode, "rows": n, "any": hit(), **{o: hit(o) for o in lexicon.ORIGINS}}


def high_conf_error(levels_c2):
    """'높음' 등급 1위 오류율(A 수준). 등급 표가 없거나 '높음' 행이 없으면 None."""
    if not levels_c2:
        return None
    acc = levels_c2["levels"]["높음"]["acc_A"]
    return None if acc is None else 1 - acc


def pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def num(v):
    return "—" if v is None else f"{v:.3f}"


def report_md(r):
    gs = r["gold_stats"]
    lt = " / ".join(f"{k} {v}" for k, v in gs["label_types"].items())
    who = " / ".join(f"{k} {v}" for k, v in gs["decided_by"].items())
    lines = []
    if r["config"]["smoke"]:
        lines += [f"# {SMOKE_BANNER}", "", "이 정답셋은 형식 확인용 스모크다. 아래 숫자를 성능 근거로 쓰지 않는다.", ""]
    lines.append(f"정답셋 `{gs['gold_name']}` · {gs['total']}행 · label_type {lt} · decided_by {who}")
    if gs["warning"]:
        lines.append(f"**{gs['warning']}**")
    if gs.get("synthetic_warning"):
        lines.append(f"**{gs['synthetic_warning']}** (decided_by=claude {gs['claude_ratio']:.0%})")
    lines.append("")
    mv = r["model_versions"]
    lines += [f"# 평가 리포트 {r['config']['group']}", "",
              f"- 정답셋 `{r['config']['gold_id']}` · 분할 `{r['config']['split']}` · test 열람 {r['config']['test_opened']}",
              f"- 행 {r['gold_stats']['total']} (정답 있음 {r['gold_stats']['answerable']}, 정답 없음 {r['gold_stats']['no_answer']})",
              f"- 모델 `{mv['embed_model']}` digest `{mv['ollama_digest']}`{' (' + mv['ollama_digest_error'] + ')' if mv['ollama_digest_error'] else ''}",
              f"- 인덱스 `{mv['index_version_id']}` hash `{mv['index_hash'][:16]}…` · TF-IDF {mv['tfidf']} · RRF k={mv['rrf_k']} · seed {mv['seed']}",
              f"- git `{mv['git_sha']}` · python {mv['python']} · scikit-learn {mv['scikit-learn']} · 걸린 시간 {r['meta']['elapsed_s']}초", ""]
    for level, title in (("strict", "strict (dataset_id 일치)"), ("name", "name-level (국문명 일치, 동명 접기)"),
                         ("A", "A 수준 (a_accept 안에 있으면 맞음)"),
                         ("S", f"S 수준 (s_accept 안에 있으면 맞음; s_accept 가 빈 행은 분모에서 뺌, 분모 {gs['s_applicable']}행)")):
        lines += [f"## 케이스 × 지표 — {title}", "", "| 케이스 | 상태 | Top-1 | Top-3 | Recall@5 | Recall@10 | MRR |", "|---|---|---|---|---|---|---|"]
        for c, v in r["cases"].items():
            s = v.get(level) or {}
            lines.append(f"| {c} {v['label']} | {v['state']} | {pct(s.get('top1'))} | {pct(s.get('top3'))} | {pct(s.get('recall@5'))} | "
                         f"{pct(s.get('recall@10'))} | {num(s.get('mrr'))} |")
        lines.append("")
    for level, ci in (("strict", r["ci"]), ("A", (r.get("ci_levels") or {}).get("A")), ("S", (r.get("ci_levels") or {}).get("S"))):
        if not (ci and ci["cases"]):
            continue
        lines += [f"## 부트스트랩 95% 구간 ({level}, {ci['n']}회, seed {ci['seed']}, 분모 {ci.get('rows', 0)}행)", "",
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
    na = r.get("no_answer_judgement")
    if na:
        lines += [f"## 맞는 후보 없음 판정 — {na['case']} ({na['rule']})", "",
                  "| 정답 | 행 | no_answer 로 답함 | 후보를 냄 |", "|---|---|---|---|",
                  f"| none (국가 DB에 없음) | {na['none']['rows']} | {na['none']['no_answer']} | {na['none']['candidate']} |",
                  f"| 정답 있음 (exact·proxy) | {na['answerable']['rows']} | {na['answerable']['no_answer']} | {na['answerable']['candidate']} |", "",
                  f"- 정거부율(none 중 no_answer): {pct(na['correct_reject_rate'])} · 오거부율(정답 있음 중 no_answer): {pct(na['false_reject_rate'])}", ""]
    lv = r.get("confidence_levels")
    if lv:
        lines += [f"## 신뢰도 등급별 정답률 — {lv['case']} ({lv['rule']})", "",
                  "| 등급 | 행 | 그중 정답 없음 | 1위 정답(A) | 정답률(A) | 1위 정답(strict) | 정답률(strict) |", "|---|---|---|---|---|---|---|"]
        for name, x in lv["levels"].items():
            lines.append(f"| {name} | {x['rows']} | {x['none_rows']} | {x['ok_A']} | {pct(x['acc_A'])} | {x['ok_strict']} | {pct(x['acc_strict'])} |")
        lines += ["", f"- '높음' 오류율(A): {pct(r['metrics'].get('high_conf_error_rate'))}", ""]
    lines += report_md_e2(r)
    for c, sl in r["slices"].items():
        lines += [f"## 조각 — {c} (strict)", "", "| 조각 | 값 | 행 | 정답 있음 | Top-1 | Top-3 | MRR | Top-1(A) | Top-1(S) | |", "|---|---|---|---|---|---|---|---|---|---|"]
        for name, vals in sl.items():
            for value, s in vals.items():
                lines.append(f"| {name} | {value} | {s['n']} | {s['answerable']} | {pct(s['top1'])} | {pct(s['top3'])} | {num(s['mrr'])} | "
                             f"{pct(s['top1_A'])} | {pct(s['top1_S'])} | {'표본 적음' if s['small'] else ''} |")
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


def report_md_e2(r):
    """E2 절: 외부 결과 run, 짝 비교, 케이스별 no_answer, 신뢰도 규칙 후보. 키가 없으면(옛 리포트) 빈 목록."""
    lines = []
    for c, x in (r.get("external_runs") or {}).items():
        lines += [f"## 외부 결과 — {c}", "", f"- run `{x['run_id']}` · kind {x['kind']} · model `{x['model']}` · structure {x['structure'] or '—'}",
                  f"- params `{json.dumps(x['params'], ensure_ascii=False)}` · prompt sha256 {x['prompt_sha256'] or '—'} · export `{x['export_id']}` (base {x['base_case']})", ""]
    pr = r.get("paired")
    if pr and pr["cases"]:
        lines += [f"## 짝 비교 — 기준 {pr['base']} 대비 같은 행의 1위({pr['level']} 수준)", "", "| 케이스 | 새로 맞힘 | 새로 틀림 | 새로 맞힌 행 id | 새로 틀린 행 id |", "|---|---|---|---|---|"]
        for c, x in pr["cases"].items():
            lines.append(f"| {c} | {len(x['new_right'])} | {len(x['new_wrong'])} | {', '.join(map(str, x['new_right'])) or '—'} | "
                         f"{', '.join(map(str, x['new_wrong'])) or '—'} |")
        lines.append("")
    pc = r.get("pair_counts")
    if pc and pc["cases"]:
        lines += [f"## 행 단위 변화 — 기준 {pc['base']} (--cases 첫 케이스) 대비 1위", "",
                  "| 케이스 | A 새로 맞힘 | A 새로 틀림 | A 그대로 | S 새로 맞힘 | S 새로 틀림 | S 그대로 |", "|---|---|---|---|---|---|---|"]
        for c, x in pc["cases"].items():
            lines.append(f"| {c} | " + " | ".join(f"{x[lv][k]}" for lv in ("A", "S") for k in ("new_right", "new_wrong", "same")) + " |")
        lines += ["", f"분모: A {next(iter(pc['cases'].values()))['A']['rows']}행, S {next(iter(pc['cases'].values()))['S']['rows']}행. 그대로 = 맞음·틀림이 같은 행.", ""]
    rc = r.get("recall_at_k")
    if rc:
        lines += ["## 후보 재현율 — 정답이 상위 K 안에 있는 비율 (재순위가 올릴 수 있는 상한; none·분모 밖 행 제외)", "",
                  "| 케이스 | 수준 | 분모 | K=1 | K=3 | K=10 | K=30 | 30 안에 없는 행 |", "|---|---|---|---|---|---|---|---|"]
        for c, x in rc.items():
            for lv in ("A", "S"):
                y = x[lv]
                lines.append(f"| {c} | {lv} | {y['n']} | " + " | ".join(pct(y[f"top{k}"]) for k in metrics.RECALL_KS) +
                             f" | {len(y['miss_ids'])}개: {', '.join(map(str, y['miss_ids'])) or '—'} |")
        lines.append("")
    lh = r.get("lexicon_hits")
    if lh:
        lines += ["## 사전 적중 행 비율 (적중 ≥1; 출처별은 그 출처 항목이 1개 이상 걸린 행)", "",
                  "| 케이스 | 모드 | 행 | 전체 | std | db | dev |", "|---|---|---|---|---|---|---|"]
        for c, x in lh.items():
            lines.append(f"| {c} | {x['mode']} | {x['rows']} | " + " | ".join(f"{x[k]} ({pct(x[k] / x['rows'])})" for k in ("any", "std", "db", "dev")) + " |")
        lines.append("")
    for x in r.get("paired_extra") or []:
        lines += [f"## 짝 비교 — {x['base']} 대비 {x['case']} (A 수준 1위)", "",
                  f"- 새로 맞힘 {len(x['new_right'])}: {', '.join(map(str, x['new_right'])) or '—'}",
                  f"- 새로 틀림 {len(x['new_wrong'])}: {', '.join(map(str, x['new_wrong'])) or '—'}", ""]
    vh = r.get("veto_hurt")
    if vh:
        lines += ["## Veto로 정답 순위가 나빠진 행 (A 수준; Veto 전 대비)", "",
                  "| 케이스 | 정답이 거른·강등한 역할이라 밀림 | label_id | 그 밖의 이유로 하락 | label_id |", "|---|---|---|---|---|"]
        lines += [f"| {c} | {x['n']} | {', '.join(map(str, x['ids'])) or '—'} | {x['other_n']} | {', '.join(map(str, x['other_ids'])) or '—'} |"
                  for c, x in vh.items()]
        lines.append("")
    nb = r.get("no_answer_by_case")
    if nb:
        lines += ["## 맞는 후보 없음 판정 — 케이스별", "", "| 케이스 | 정거부(none 중 no_answer) | 오거부(정답 있음 중 no_answer) | 판정 |", "|---|---|---|---|"]
        for c, x in nb.items():
            lines.append(f"| {c} | {x['none']['no_answer']}/{x['none']['rows']} ({pct(x['correct_reject_rate'])}) | "
                         f"{x['answerable']['no_answer']}/{x['answerable']['rows']} ({pct(x['false_reject_rate'])}) | {x['rule']} |")
        lines.append("")
    for c, cmp_ in (r.get("confidence_rules") or {}).items():
        lines += [f"## 신뢰도 규칙 후보 — {c}", "", f"선택 기준: {cmp_['rule']}", "",
                  "| 후보 | 높음 행 | 높음 비율 (95%) | 높음 오류율 A (95%) | 보통 행 · 정답률 A | 낮음 행 · 정답률 A |", "|---|---|---|---|---|---|"]
        cands = cmp_["candidates"]
        shown = [t for t in cands if t["rule"] in ("R0", "R1", "R2")]
        r3 = sorted((t for t in cands if t["rule"] == "R3" and (t["high_coverage"] or 0) >= confidence_rules.COVERAGE_MIN),
                    key=lambda t: (t["high_error_A"] if t["high_error_A"] is not None else 9, -(t["high_coverage"] or 0)))[:5]
        sel = [t for t in cands if t["name"] == cmp_["selected"] and t not in shown + r3]
        for t in shown + r3 + sel:
            ci = t["ci"] or {"high_coverage": [None, None], "high_error_A": [None, None]}
            lv = t["levels"]
            mark = " **(선택)**" if t["name"] == cmp_["selected"] else ""
            lines.append(f"| {t['name']}{mark} | {lv['높음']['rows']} | {pct(t['high_coverage'])} ({pct(ci['high_coverage'][0])}~{pct(ci['high_coverage'][1])}) | "
                         f"{pct(t['high_error_A'])} ({pct(ci['high_error_A'][0])}~{pct(ci['high_error_A'][1])}) | "
                         f"{lv['보통']['rows']} · {pct(lv['보통']['acc_A'])} | {lv['낮음']['rows']} · {pct(lv['낮음']['acc_A'])} |")
        lines += ["", f"- 판정 규칙(고정): 합격 = '높음' 비율 ≥ {confidence_rules.HIGH_RATIO_MIN:.0%} 이고 오류율(A) 점추정 ≤ {confidence_rules.HIGH_ERR_PASS:.0%}, "
                       f"목표 {confidence_rules.HIGH_ERR_GOAL:.0%} 보증 = 오류율 95% 구간 상한 ≤ {confidence_rules.HIGH_ERR_GOAL:.0%}"]
        for t in cands:
            if t["name"] == "R0" or t["name"] == cmp_["selected"]:
                lines += [f"- **{t['name']}**", *["  " + x for x in confidence_rules.verdict_lines(t)]]
        lines += ["", f"- R3 는 비율 {confidence_rules.COVERAGE_MIN:.0%} 이상 중 오류율 낮은 5개만. 후보 전체는 confidence_rules.csv",
                  f"- 선택: {cmp_['selected'] or '기준을 만족하는 후보 없음'} · 합격선({confidence_rules.PASS_ERROR:.0%}) {'통과' if cmp_['passed'] else '미달'}"]
        if cmp_["curve"]:
            by = {t["name"]: t for t in cands}
            lines.append("- 비율을 낮췄을 때 선택: " + " · ".join(
                f"{float(k):.0%} 이상 → {v} (비율 {pct(by[v]['high_coverage'])}, 오류율 {pct(by[v]['high_error_A'])})" if v else f"{float(k):.0%} 이상 → 없음"
                for k, v in cmp_["curve"].items()))
        lines.append("")
    return lines


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
