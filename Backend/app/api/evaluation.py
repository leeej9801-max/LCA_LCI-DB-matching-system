"""A19·A14 평가 결과 읽기 전용. 최종 평가 리포트(report.json)를 파일 그대로 내보낸다. DB·쓰기 없음, 실행(A13)은 없다."""
import json
import re
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from app.errors import ApiError
from app.schemas import EvalRunList

router = APIRouter(prefix="/eval", tags=["eval"])

REPORTS = Path(__file__).resolve().parents[1] / "data" / "eval_reports"
# run_id 에 든 gold 이름 → 화면 이름. 이 순서로 정렬하고 표에 없는 파일(튜닝용·110행)은 목록(A19)에서 뺀다. 파일이 없는 세트는 목록에서 빠질 뿐 오류가 아니다. A14 는 파일이 있으면 id 로 읽는다
SET_LABELS = [("gold-bulk-v1", "가상 BOM 2000 (검증용)"), ("gold-p1-v1", "공개 문서 표기")]
RUN_ID = re.compile(r"eval-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-(.+)")


def _set_label(run_id):
    return next((i, label) for i, (key, label) in enumerate(SET_LABELS) if key in run_id)


@router.get("/runs", response_model=EvalRunList)
def list_runs():  # A19
    found = []
    for path in REPORTS.glob("*.json"):
        m = RUN_ID.fullmatch(path.stem)
        if not m or not any(key in path.stem for key, _ in SET_LABELS):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        order, label = _set_label(path.stem)
        y, mo, d, h, mi, s = m.groups()[:6]
        found.append((order, {
            "run_id": path.stem, "status": "done", "created_at": f"{y}-{mo}-{d}T{h}:{mi}:{s}",
            "config_label": report["config"]["head_case"], "set_label": label,
            "split": report["config"]["split"], "rows": report["gold_stats"]["total"],
        }))
    items = [item for _, item in sorted(found, key=lambda f: f[0])]
    return {"items": items, "total": len(items)}


@router.get("/runs/{run_id}")
def get_run(run_id: str):  # A14
    path = REPORTS / f"{run_id}.json"
    # 경로 구분자·".."는 파일을 찾기 전에 막는다. 목록에 없는 파일도 같은 404
    if any(c in run_id for c in "/\\") or ".." in run_id or not RUN_ID.fullmatch(run_id) or not path.is_file():
        raise ApiError(404, "평가 기록을 찾을 수 없습니다.", "EVAL_RUN_NOT_FOUND")
    return Response(path.read_bytes(), media_type="application/json")
