"""데이터셋 목록(A05)·상세(A06). lci_dataset(T10b 적재) 위에서 동작한다. 사전·임베딩 검색은 아직 없다."""
import re
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row

from app.db.connection import conninfo
from app.errors import ApiError
from app.schemas import Dataset, DatasetDetail, DatasetSearchResponse

router = APIRouter(prefix="/datasets", tags=["datasets"])

DATASET_ID = re.compile(r"^list-\d+$")

# 같은 name_ko 개수는 검색 조건과 무관하게 표 전체에서 센다
BASE = """
WITH d AS (SELECT *, count(*) OVER (PARTITION BY name_ko) AS dup_count FROM lci_dataset)
SELECT dataset_id, name_ko, name_en, category, developer, dev_year, version, has_xml, list_sn, ref_flow_unit, dup_count,
       dataset_type, allocation, cutoff, geography, tech_description
FROM d
"""


def get_conn():
    """요청마다 접속 하나(풀 없음). 시험에서는 이 의존성을 임시 DB 로 바꿔 끼운다."""
    with psycopg.connect(conninfo(), row_factory=dict_row) as conn:
        yield conn


def version(v):
    """목록 원문의 '-'는 버전 없음 자리표시(엑셀 데이터셋 393행). 응답에서는 null, DB 값은 그대로 둔다."""
    return None if v == "-" else v


def to_item(r):
    return {
        "dataset_id": r["dataset_id"], "name": r["name_ko"], "name_en": r["name_en"], "category": r["category"], "org": r["developer"],
        "year": r["dev_year"], "version": version(r["version"]), "has_xml": r["has_xml"], "list_row": r["list_sn"],
        "reference_unit": r["ref_flow_unit"], "duplicate_count": r["dup_count"],
    }


def like_pattern(q):
    """사용자 입력의 \\, %, _ 를 글자 그대로 찾도록 이스케이프한 ILIKE 부분 일치 패턴."""
    return "%" + re.sub(r"([\\%_])", r"\\\1", q) + "%"


def year_key(r):
    return (r["dev_year"] is not None, r["dev_year"] or 0, r["list_sn"])  # 연도 최신(같으면 list_sn 큰 것), 연도 없음은 뒤


def group(rows):
    """같은 name_ko 를 한 행으로 접는다. 대표는 연도 최신, 같으면 list_sn 큰 것."""
    best = {}
    for r in rows:
        if r["name_ko"] not in best or year_key(r) > year_key(best[r["name_ko"]]):
            best[r["name_ko"]] = r
    return list(best.values())


def relevance(q):
    ql = q.lower()

    def rank(r):
        names = [n.lower() for n in (r["name_ko"], r["name_en"]) if n]
        return 0 if ql in names else 1 if any(n.startswith(ql) for n in names) else 2
    return rank


@router.get("", response_model=DatasetSearchResponse)
def search_datasets(
    q: str | None = Query(None, max_length=100),
    category: str | None = None,
    has_xml: bool | None = None,
    sort: Literal["relevance", "year_desc", "name"] = "relevance",
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    group_duplicates: bool = True,
    conn=Depends(get_conn),
):  # A05
    q = (q or "").strip() or None
    if q:
        pat = like_pattern(q)
        rows = conn.execute(BASE + r" WHERE name_ko ILIKE %s ESCAPE '\' OR name_en ILIKE %s ESCAPE '\'", (pat, pat)).fetchall()
    else:
        rows = conn.execute(BASE).fetchall()

    cats = [c.strip() for c in (category or "").split(",") if c.strip()]

    def visible(cats_, xml_):
        """분류(cats_, 빈 목록이면 전체)·has_xml(xml_, None 이면 전체) 필터 후 접은 행 = 화면에 보이는 행."""
        out = [r for r in rows if (not cats_ or r["category"] in cats_) and (xml_ is None or r["has_xml"] == xml_)]
        return group(out) if group_duplicates else out

    # facet 값마다 "그 값을 고르면 보일 행 수"를 센다: 자기 필터만 그 값으로 바꾸고 다른 조건(q·다른 필터·접기)은 그대로.
    # 그래서 숫자가 그 값을 골랐을 때의 total 과 같다. 접기 때문에 한 동명 그룹이 두 값에 모두 셀 수 있어 합은 total 보다 클 수 있다
    in_xml = [r for r in rows if has_xml is None or r["has_xml"] == has_xml]
    facets = {"category": {c: len(visible([c], has_xml)) for c in dict.fromkeys(r["category"] for r in in_xml)},
              "has_xml": {"true": len(visible(cats, True)), "false": len(visible(cats, False))}}

    items = visible(cats, has_xml)

    items.sort(key=lambda r: tuple(-x for x in year_key(r)[:2]) + (-r["list_sn"],))  # year_desc 가 기본 순서
    if sort == "name":
        items.sort(key=lambda r: (r["name_ko"], r["list_sn"]))
    elif sort == "relevance" and q:
        items.sort(key=relevance(q))  # 안정 정렬이라 같은 순위 안에서는 연도 내림이 유지된다
    page = items[offset:offset + limit]
    return {"items": [to_item(r) for r in page], "total": len(items), "facets": facets}


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: str, conn=Depends(get_conn)):  # A06
    r = conn.execute(BASE + " WHERE dataset_id = %s", (dataset_id,)).fetchone() if DATASET_ID.match(dataset_id) else None
    if not r:
        raise ApiError(404, f"데이터셋을 찾을 수 없습니다: {dataset_id}", "DATASET_NOT_FOUND")
    dups = conn.execute(
        "SELECT dataset_id, developer, dev_year, version FROM lci_dataset WHERE name_ko = %s AND dataset_id <> %s "
        "ORDER BY dev_year DESC NULLS LAST, list_sn DESC", (r["name_ko"], dataset_id)).fetchall()
    return {
        **to_item(r), "data_type": r["dataset_type"], "allocation": r["allocation"], "cutoff": r["cutoff"], "geography": r["geography"],
        "tech_summary": r["tech_description"],
        "duplicates": [{"dataset_id": d["dataset_id"], "org": d["developer"], "year": d["dev_year"], "version": version(d["version"])} for d in dups],
    }
