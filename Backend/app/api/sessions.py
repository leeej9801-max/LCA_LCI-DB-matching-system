"""세션 API: A20 미리보기, A01 업로드(매칭 작업 생성), A02 세션 읽기, A03 행 변경, A04 설명, A07 내보내기."""
import secrets
import string
from datetime import timedelta
from typing import Literal

import psycopg
from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from psycopg.types.json import Jsonb

from app.bom import clean, mapping, match, review
from app.bom.reader import MAX_BYTES, read_bom_ex
from app.db.connection import conninfo
from app.errors import ApiError
from app.jobs import enqueue
from app.schemas import Explanation, PreviewResponse, RowUpdateResponse, SessionPayload

router = APIRouter(prefix="/sessions", tags=["sessions"])
SESSION_TTL = timedelta(hours=24)
ALNUM = string.ascii_letters + string.digits


def get_db():
    """요청마다 접속 하나(풀 없음, 튜플 행). 시험에서는 임시 DB 로 바꿔 끼운다."""
    with psycopg.connect(conninfo()) as conn:
        yield conn


def read_upload(file):
    data = file.file.read(MAX_BYTES + 1)  # 상한보다 1바이트 더 읽어 초과를 안다
    return read_bom_ex(file.filename, data)


def parse(file, mapping_raw):
    """(파일명, 헤더, 행, column_mapping, 뺀 행 수)."""
    override = mapping.parse_mapping(mapping_raw)
    header, rows, skipped = read_upload(file)
    return file.filename, header, rows, mapping.detect(header, rows[0][1] if rows else None, override), skipped


@router.post("/preview", response_model=PreviewResponse)
def preview(file: UploadFile = File(...), mapping_raw: str | None = Form(None, alias="mapping")):  # A20 (DB 쓰기 없음)
    filename, header, rows, column_mapping, skipped = parse(file, mapping_raw)
    return {"filename": filename, "rows_total": len(rows), "rows_skipped": skipped, "column_mapping": column_mapping, "file_columns": header,
            "preview_rows": [r for _, r in rows[:5]]}


@router.post("", status_code=202)
def create_session(file: UploadFile = File(...), mapping_raw: str | None = Form(None, alias="mapping"), conn=Depends(get_db)):  # A01
    filename, header, rows, column_mapping, _ = parse(file, mapping_raw)
    missing = mapping.missing_required(column_mapping)
    if missing:
        names = ", ".join(f"'{m}'" for m in missing)
        raise ApiError(400, f"필수 컬럼 {names}을(를) 찾지 못했습니다.", "MISSING_COLUMN", {"missing": missing})
    items = clean.clean_rows(clean.extract(header, rows, column_mapping))
    session_id = "".join(secrets.choice(ALNUM) for _ in range(12))
    with conn.transaction():
        conn.execute("INSERT INTO bom_project (project_id, source_file, expires_at) VALUES (%s, %s, now() + %s)",
                     (session_id, filename, SESSION_TTL))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO bom_item (project_id, row_no, source_row, raw_name, raw_spec, raw_unit, raw_qty, clean_name, clean_spec, "
                "clean_unit, clean_unit_display, clean_qty, norm_text, query_key, issues, target_status, target_reason, review_status, "
                "input_role, part_no) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(session_id, it["row_no"], it["source_row"], it["raw_name"], it["raw_spec"], it["raw_unit"], it["raw_qty"], it["clean_name"],
                  it["clean_spec"], it["clean_unit"], it["clean_unit_display"], it["clean_qty"], it["norm_text"], it["query_key"],
                  Jsonb(it["issues"]), it["target_status"], it["target_reason"],
                  "excluded" if it["target_status"] == "제외" else "pending", it["input_role"], it["part_no"]) for it in items])
        job_id = enqueue(conn, session_id)
    return JSONResponse({"job_id": job_id, "session_id": session_id}, status_code=202)


@router.get("/{session_id}", response_model=SessionPayload)
def get_session(session_id: str, conn=Depends(get_db)):  # A02
    source_file = review.require_session(conn, session_id)
    rows = match.build_rows(conn, session_id)
    count = conn.execute("SELECT count(*) FROM lci_dataset").fetchone()[0]
    return {"session_id": session_id, "filename": source_file, "rows": rows, "summary": match.summarize(rows),
            "db_note": f"국가 LCI DB {count}건(공개 목록 기준)", "column_mapping": None}


@router.patch("/{session_id}/rows/{row_no}", response_model=RowUpdateResponse)
def update_row(session_id: str, row_no: int, payload: dict = Body(...), conn=Depends(get_db)):  # A03
    return review.patch_row(conn, session_id, row_no, payload)


@router.post("/{session_id}/rows/{row_no}/explain", response_model=Explanation)
def explain(session_id: str, row_no: int, conn=Depends(get_db)):  # A04
    return review.explain_row(conn, session_id, row_no)


@router.get("/{session_id}/export")
def export(session_id: str, format: Literal["xlsx", "csv"] = "xlsx", conn=Depends(get_db)):  # A07
    source_file, approved, others, info = review.export_rows(conn, session_id)
    _, disposition = review.export_filename(source_file, format)
    if format == "csv":
        return Response(review.to_csv(approved), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": disposition})
    return Response(review.to_xlsx(approved, others, info), headers={"Content-Disposition": disposition},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
