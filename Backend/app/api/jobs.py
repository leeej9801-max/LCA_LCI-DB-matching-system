"""A21 작업 상태."""
from fastapi import APIRouter, Depends

from app.api.sessions import get_db
from app.errors import ApiError
from app.jobs import queued_position
from app.schemas import JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobStatus)
def get_job(job_id: str, conn=Depends(get_db)):  # A21
    row = conn.execute("SELECT job_id, kind, state, stages, result, error FROM job WHERE job_id = %s", (job_id,)).fetchone()
    if not row:
        raise ApiError(404, "작업을 찾을 수 없습니다.", "JOB_NOT_FOUND")
    job_id, kind, state, stages, result, error = row
    # job.result 에는 queries·cache_hits 도 있지만 A21 계약은 session_id·report_id 만 내보낸다
    out = {"job_id": job_id, "kind": kind, "state": state, "stages": stages,
           "result": {k: result[k] for k in ("session_id", "report_id") if k in result} if state == "succeeded" else {}}
    if state == "failed" and error:
        out["error"] = {"detail": error.get("detail", ""), "code": error.get("code", "MATCH_FAILED")}
    if state == "queued":
        out["queued_position"] = queued_position(conn, job_id)
    return out
