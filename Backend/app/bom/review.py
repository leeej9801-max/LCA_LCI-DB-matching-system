"""검토 흐름: A03 행 변경, A04 규칙 설명, A07 내보내기. 사전·Veto·LLM 은 없다."""
import csv
import io
import math
from datetime import datetime
from urllib.parse import quote

from psycopg.types.json import Jsonb

from app.bom.match import build_rows, summarize
from app.errors import ApiError
from app.schemas import RowPatch

STATUSES = ("pending", "approved", "rejected", "excluded")
RANGES = {  # 필드: (하한 초과, 상한 이하 또는 None, 화면 문구)
    "thickness_mm": (0, 1000, "두께는 0 초과 1000 이하(mm)여야 합니다."),
    "density_kg_m3": (0, None, "밀도는 0보다 커야 합니다(kg/m³)."),
    "unit_mass_kg": (0, 1000, "개당 중량은 0 초과 1000 이하(kg/개)여야 합니다."),
}
DISCLAIMER = "이 결과는 사람이 승인한 매칭이며 인증용 계산이 아닙니다."


def require_session(conn, session_id):
    """세션이 있고 매칭 작업이 끝났는지(A02·A03·A04·A07 공통). 반환: source_file."""
    project = conn.execute("SELECT source_file FROM bom_project WHERE project_id = %s AND expires_at > now()", (session_id,)).fetchone()
    if not project:
        raise ApiError(404, "세션을 찾을 수 없습니다. 파일을 다시 업로드해 주세요.", "SESSION_NOT_FOUND")
    job = conn.execute("SELECT job_id, state, error FROM job WHERE kind = 'match' AND params->>'session_id' = %s "
                       "ORDER BY created_at DESC LIMIT 1", (session_id,)).fetchone()
    if job and job[1] == "failed":
        error = job[2] or {}
        raise ApiError(409, f"매칭 작업이 실패했습니다: {error.get('detail', '원인을 알 수 없습니다')}", "JOB_FAILED",
                       {"job_id": job[0], "error_code": error.get("code")})
    if not job or job[1] != "succeeded":
        raise ApiError(409, "매칭이 아직 끝나지 않았습니다. 작업 상태(A21)를 확인해 주세요.", "JOB_NOT_FINISHED",
                       {"job_id": job[0] if job else None})
    return project[0]


def lock_row(conn, session_id, row_no):
    """행을 잠그고 bom_item 현재 상태를 돌려준다. 없으면 404."""
    row = conn.execute(
        "SELECT item_id, selected_id, selected_manual, override_thickness_mm, override_density_kg_m3, override_unit_mass_kg, review_status, "
        "review_note FROM bom_item WHERE project_id = %s AND row_no = %s FOR UPDATE", (session_id, row_no)).fetchone()
    if not row:
        raise ApiError(404, "행을 찾을 수 없습니다.", "ROW_NOT_FOUND")
    return dict(zip(["item_id", "selected_id", "selected_manual", "thickness_mm", "density_kg_m3", "unit_mass_kg", "review_status",
                     "review_note"], row))


def validate_patch(payload):
    """범위 → 400 OUT_OF_RANGE, 그 밖의 형식 오류 → 422 VALIDATION_ERROR. 통과하면 보낸 필드만 담은 dict."""
    if not isinstance(payload, dict):
        raise ApiError(422, "요청 본문은 JSON 객체여야 합니다.", "VALIDATION_ERROR")
    for field, (low, high, msg) in RANGES.items():
        if field in payload and payload[field] is not None:
            v = payload[field]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= low or (high is not None and v > high):
                raise ApiError(400, msg, "OUT_OF_RANGE", {"field": field})
    try:
        RowPatch.model_validate(payload)
    except Exception as e:  # pydantic ValidationError
        errors = getattr(e, "errors", lambda: [])()
        raise ApiError(422, "입력 형식이 올바르지 않습니다.", "VALIDATION_ERROR",
                       {"errors": [{"field": ".".join(map(str, x["loc"])), "type": x["type"]} for x in errors]}) from e
    return payload


def action_of(patch):
    status = patch.get("review_status")
    if status:
        return {"approved": "approve", "rejected": "reject", "excluded": "exclude", "pending": "pending"}.get(status, "invalid")
    if "selected_id" in patch or patch.get("clear_selection"):
        return "select"
    if any(k in patch for k in RANGES):
        return "overrides"
    if "note" in patch:
        return "note"
    return "noop"


def record(conn, item_id, run_id, patch, outcome, from_status, to_status, reason=None, dataset_id=None):
    conn.execute(
        "INSERT INTO review_decision (item_id, run_id, dataset_id, action, thickness_mm, density_kg_m3, unit_mass_kg, note, actor, "
        "from_status, to_status, outcome, payload, reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'user',%s,%s,%s,%s,%s)",
        (item_id, run_id, dataset_id, action_of(patch), patch.get("thickness_mm"), patch.get("density_kg_m3"), patch.get("unit_mass_kg"),
         patch.get("note"), from_status, to_status, outcome, Jsonb(patch), reason))


def patch_row(conn, session_id, row_no, payload):
    """A03. 보낸 필드만 반영. 실패하면 행은 그대로 두고 거부 기록(outcome=rejected)만 남긴다."""
    require_session(conn, session_id)
    state = lock_row(conn, session_id, row_no)  # 같은 행을 동시에 바꾸는 요청은 여기서 줄을 선다
    run = conn.execute("SELECT run_id FROM match_run WHERE project_id = %s ORDER BY started_at DESC LIMIT 1", (session_id,)).fetchone()
    run_id = run[0] if run else None
    before = build_rows(conn, session_id, row_no)[0]
    try:
        patch = validate_patch(payload)
        new = apply_patch(conn, session_id, row_no, state, before, patch)
    except ApiError as e:
        # 아무것도 바꾸지 않았으므로 거부 기록만 남기고 커밋한다(오류 응답이 나가도 롤백되지 않게)
        record(conn, state["item_id"], run_id, payload if isinstance(payload, dict) else {"raw": str(payload)}, "rejected",
               before["review"]["status"], before["review"]["status"], e.detail)  # 거부 기록의 dataset_id 는 비운다(요청 원문은 payload 에)
        conn.commit()
        raise
    after, reason = new
    record(conn, state["item_id"], run_id, patch, "applied", before["review"]["status"], after["review"]["status"], reason,
           after["selected_id"])
    rows = build_rows(conn, session_id)
    return {"row": next(r for r in rows if r["id"] == row_no), "summary": summarize(rows)}


def apply_patch(conn, session_id, row_no, state, before, patch):
    """검증·계산 후 bom_item 을 바꾼다. 실패 조건은 DB 를 쓰기 전에 모두 확인한다. 반환: (바뀐 Row, 기록 사유)."""
    sel_id, manual = before["selected_id"], state["selected_manual"]
    if patch.get("clear_selection") or ("selected_id" in patch and patch["selected_id"] is None):
        sel_id, manual = None, False
    elif "selected_id" in patch:
        if not conn.execute("SELECT 1 FROM lci_dataset WHERE dataset_id = %s", (patch["selected_id"],)).fetchone():
            raise ApiError(400, f"알 수 없는 데이터셋 ID: {patch['selected_id']}", "UNKNOWN_DATASET")
        sel_id = patch["selected_id"]
        in_top3 = next((c for c in before["candidates"] if c["dataset_id"] == sel_id), None)
        manual = in_top3 is None or in_top3["veto"] is not None
    overrides = {k: state[k] for k in RANGES}
    for k in RANGES:
        if k in patch:
            overrides[k] = patch[k]
    status, note = state["review_status"], state["review_note"]
    reason = None
    selection_changed = sel_id != before["selected_id"]
    if status == "approved" and "review_status" not in patch and selection_changed:
        status, reason = "pending", "선택 변경으로 승인 해제"
    if "note" in patch:
        note = patch["note"] or ""
    if patch.get("review_status"):
        status = patch["review_status"]

    # 바뀐 상태로 Row 를 미리 만들어 환산을 확인한다(DB 에 쓰기 전)
    conn.execute("SAVEPOINT patch_preview")
    try:
        write_state(conn, state["item_id"], sel_id, manual, overrides, status, note,
                    keep_explanation=not (selection_changed or any(k in patch for k in RANGES) or "review_status" in patch))
        after = build_rows(conn, session_id, row_no)[0]
        if patch.get("review_status") == "approved" and (after["conversion"] or {}).get("status") not in ("ok", "converted"):
            why = after["conversion"]["message"] if after["selected"] else "데이터셋을 선택하지 않았습니다"
            raise ApiError(409, f"단위 환산이 완료되지 않아 승인할 수 없습니다: {why}.", "CONVERSION_INCOMPLETE")
    except ApiError:
        conn.execute("ROLLBACK TO SAVEPOINT patch_preview")
        raise
    conn.execute("RELEASE SAVEPOINT patch_preview")
    return after, reason


def write_state(conn, item_id, sel_id, manual, overrides, status, note, keep_explanation):
    conn.execute(
        "UPDATE bom_item SET selected_id = %s, selected_manual = %s, override_thickness_mm = %s, override_density_kg_m3 = %s, "
        "override_unit_mass_kg = %s, review_status = %s, review_note = %s"
        + ("" if keep_explanation else ", explanation = NULL") + " WHERE item_id = %s",
        (sel_id, manual, overrides["thickness_mm"], overrides["density_kg_m3"], overrides["unit_mass_kg"], status, note, item_id))


# ---------- A04 ----------
def explain_row(conn, session_id, row_no):
    """규칙 기반 설명(source=rule). 결과를 bom_item.explanation 에 저장한다."""
    require_session(conn, session_id)
    lock_row(conn, session_id, row_no)
    row = build_rows(conn, session_id, row_no)[0]
    sel = row["selected"]
    cand = next((c for c in row["candidates"] if c["dataset_id"] == row["selected_id"]), None)
    sentences = []
    if not sel:
        sentences.append("선택된 데이터셋이 없습니다.")
    elif not cand:
        sentences.append(f"{sel['name']}은(는) 후보 밖에서 직접 선택한 데이터셋입니다.")
    else:
        sentences.append(f"{cand['name']} 선택 근거: {', '.join(cand['reasons'])}." if cand["reasons"] else f"{cand['name']}에 기록된 근거가 없습니다.")
        sentences.append(f"신뢰도({cand['confidence']})는 두 검색 방식(TF-IDF·밀집)의 순위로 정한 임시 표시이며 확률이 아닙니다.")
    if row["conversion"]:
        sentences.append(f"환산: {row['conversion']['message']}.")
    explanation = {"source": "rule", "text": " ".join(sentences),
                   "questions": [f"{m} 값을 확인해 주세요" for m in (row["conversion"] or {}).get("missing", [])]}
    conn.execute("UPDATE bom_item SET explanation = %s WHERE project_id = %s AND row_no = %s", (Jsonb(explanation), session_id, row_no))
    return explanation


# ---------- A07 ----------
APPROVED_COLS = ["원본 행", "부품번호", "구분", "품명", "규격", "수량", "단위", "데이터셋 ID", "데이터셋", "데이터셋 역할", "기관", "연도", "버전", "기준 단위", "XML 보유",
                 "환산 값", "환산 단위", "환산 방법", "직접 선택 여부", "메모"]
OTHER_COLS = ["원본 행", "부품번호", "구분", "품명", "규격", "수량", "단위", "상태", "사유/메모"]
STATUS_KO = {"pending": "대기", "approved": "승인", "rejected": "반려", "excluded": "제외"}


def export_rows(conn, session_id):
    """(파일명 원본, 승인 행 표, 미승인·제외 행 표, 정보 표)."""
    source_file = require_session(conn, session_id)
    rows = build_rows(conn, session_id)
    approved = [r for r in rows if r["review"]["status"] == "approved"]
    if not approved:
        raise ApiError(409, "승인된 항목이 없습니다. 먼저 항목을 검토·승인해 주세요.", "NO_APPROVED_ROWS")
    ids = [r["selected_id"] for r in approved]
    ds = {r[0]: r[1:] for r in conn.execute("SELECT dataset_id, developer, dev_year, version, has_xml FROM lci_dataset WHERE dataset_id = ANY(%s)",
                                             (ids,)).fetchall()}
    a = []
    for r in approved:
        org, year, version, xml = ds.get(r["selected_id"], (None, None, None, None))
        c = r["conversion"] or {}
        a.append([r["source_row"], r["part_no"], r["input_role"], r["raw"]["name"], r["raw"]["spec"], r["raw"]["quantity"], r["raw"]["unit"],
                  r["selected_id"], r["selected"]["name"], r["selected"]["role"], org, year, None if version == "-" else version, r["selected"]["reference_unit"],
                  "예" if xml else "아니오", c.get("value"), c.get("unit"), c.get("method"), "예" if r["selected"]["manual"] else "아니오",
                  r["review"]["note"]])
    others = [[r["source_row"], r["part_no"], r["input_role"], r["raw"]["name"], r["raw"]["spec"], r["raw"]["quantity"], r["raw"]["unit"],
               STATUS_KO[r["review"]["status"]], r["review"]["note"] or r["target"]["reason"]]
              for r in rows if r["review"]["status"] != "approved"]
    run = conn.execute("SELECT config, model_versions FROM match_run WHERE project_id = %s ORDER BY started_at DESC LIMIT 1",
                       (session_id,)).fetchone()
    config, mv = (run or ({}, {}))
    info = [["세션 ID", session_id], ["파일명", source_file], ["내보낸 시각", datetime.now().astimezone().isoformat(timespec="seconds")],
            ["인덱스 버전", mv.get("index_version_id")], ["임베딩 모델", mv.get("embed_model")], ["임베딩 모델 digest", mv.get("ollama_digest")],
            ["신뢰도 규칙", config.get("confidence_rule")], ["구분 필터 규칙", config.get("role_filter_rule")], ["안내", DISCLAIMER]]
    return source_file, a, others, info


def export_filename(source_file, ext, now=None):
    stem = source_file.rsplit(".", 1)[0] if "." in source_file else source_file
    name = f"LCI-Match_{stem}_{(now or datetime.now()):%Y%m%d}.{ext}"
    ascii_stem = "".join(ch for ch in stem if ch.isascii() and (ch.isalnum() or ch in "-_")) or "session"
    fallback = f"LCI-Match_{ascii_stem}_{(now or datetime.now()):%Y%m%d}.{ext}"
    return name, f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"


def to_csv(approved):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(APPROVED_COLS)
    w.writerows(approved)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def to_xlsx(approved, others, info):
    import openpyxl
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    for i, (title, header, body) in enumerate([("승인", APPROVED_COLS, approved), ("미승인·제외", OTHER_COLS, others),
                                               ("정보", ["항목", "값"], info)]):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        ws.append(header)
        for r in body:
            ws.append(r)
        ws.freeze_panes = "A2"  # 머리행 고정
        for col, name in enumerate(header, start=1):  # 열 너비 대략 맞춤(글자 수 기준, 한글은 2칸)
            width = max([len(str(name))] + [len(str(r[col - 1])) for r in body if r[col - 1] is not None] or [4])
            ws.column_dimensions[get_column_letter(col)].width = min(60, max(6, width * 1.6 + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
