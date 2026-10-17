"""API 명세서(docs/LCA/spec/07-API명세서.md) 2·3장 객체의 Pydantic 모델. 이름·필드는 명세와 같다.

명세 표에서 `| null`이 붙은 필드는 필수 키 + null 허용(기본값 없음). `?`·"선택"만 기본값 None.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- 컬럼 매핑 (A01·A20) ---
class ColumnMapping(Model):
    field: Literal["품명", "규격", "단위", "수량"]
    required: bool
    source: str | None
    method: Literal["auto", "manual", "missing"]
    sample: str | None


# --- 후보 ---
class Veto(Model):
    rule_id: str
    reason: str


class DuplicateGroup(Model):
    size: int
    others: list[str]


class Candidate(Model):
    dataset_id: str
    name: str
    name_en: str
    category: str
    org: str
    year: int
    version: str | None
    reference_unit: str
    score: float = Field(ge=0, le=1)
    confidence: Literal["높음", "보통", "낮음"]
    reasons: list[str]
    veto: Veto | None
    duplicate_group: DuplicateGroup | None
    has_xml: bool
    geography: str | None
    allocation: str | None
    cutoff: str | None
    tech_summary: str | None


class SelectedDataset(Model):
    # 명세에 필드 표가 없다. session.mock.json 의 selected 를 보고 만들었다
    dataset_id: str
    name: str
    category: str
    reference_unit: str
    score: float = Field(ge=0, le=1)
    confidence: Literal["높음", "보통", "낮음"]
    manual: bool


class Conversion(Model):
    status: Literal["ok", "converted", "needs_info", "incompatible", "invalid"]
    value: float | None
    unit: str
    message: str
    missing: list[str]
    method: str | None


class Explanation(Model):
    source: Literal["rule", "llm"]
    text: str
    questions: list[str]


# --- 요약 ---
class ReviewCounts(Model):
    pending: int
    approved: int
    rejected: int
    excluded: int


class MatchCounts(Model):
    candidate: int
    vetoed: int
    no_answer: int


class Summary(Model):
    total: int
    target: int
    exclude: int
    needs_review: int
    with_issues: int
    needs_info: int
    high_confidence: int
    review: ReviewCounts
    match: MatchCounts


# --- 행 ---
class RawFields(Model):
    name: str
    spec: str
    unit: str
    quantity: str


class CleanFields(Model):
    name: str
    spec: str
    unit: str | None
    unit_display: str | None
    quantity: float | None


class Target(Model):
    status: Literal["대상", "제외", "검토"]
    reason: str


class Overrides(Model):
    thickness_mm: float | None = None
    density_kg_m3: float | None = None
    unit_mass_kg: float | None = None


class Review(Model):
    status: Literal["pending", "approved", "rejected", "excluded"]
    note: str


class Row(Model):
    id: int
    source_row: int
    raw: RawFields
    clean: CleanFields
    normalized_name: str
    synonym_hits: list[str]
    # 명세: 값은 string, number 또는 boolean. Strict: "true"나 1 이 bool 로 조용히 바뀌지 않는다
    attrs: dict[str, StrictStr | StrictInt | StrictFloat | StrictBool]
    issues: list[str]
    target: Target
    match_state: Literal["candidate", "vetoed", "no_answer"]
    candidates: list[Candidate]
    ambiguous: bool
    selected_id: str | None
    selected: SelectedDataset | None
    overrides: Overrides
    review: Review
    conversion: Conversion | None
    explanation: Explanation | None


class SessionPayload(Model):
    session_id: str
    filename: str
    rows: list[Row]
    summary: Summary
    db_note: str
    column_mapping: list[ColumnMapping] | None = None  # A01 응답에만


# --- 데이터셋 (A05·A06) ---
class Dataset(Model):
    dataset_id: str
    name: str
    name_en: str
    category: str
    org: str
    year: int
    version: str | None
    has_xml: bool
    list_row: int
    reference_unit: str
    duplicate_count: int


class DatasetDuplicate(Model):
    dataset_id: str
    org: str
    year: int
    version: str | None


class DatasetDetail(Dataset):
    data_type: str
    allocation: str | None
    cutoff: str | None
    geography: str | None
    tech_summary: str | None
    duplicates: list[DatasetDuplicate]


class DatasetFacets(Model):
    category: dict[str, int]
    has_xml: dict[str, int]


class DatasetSearchResponse(Model):
    items: list[Dataset]
    total: int
    facets: DatasetFacets


# --- A20 ---
class PreviewResponse(Model):
    filename: str
    rows_total: int
    column_mapping: list[ColumnMapping]
    file_columns: list[str]
    preview_rows: list[list[str]]


# --- A21 ---
class JobStage(Model):
    name: str
    state: str  # 명세에 값 목록 없음
    done: int
    total: int
    started_at: str | None
    finished_at: str | None


class JobResult(Model):
    session_id: str | None = None
    report_id: str | None = None


class JobError(Model):
    detail: str
    code: str


class JobStatus(Model):
    job_id: str
    kind: Literal["ingest", "match"]
    state: Literal["queued", "running", "succeeded", "failed"]
    stages: list[JobStage]
    result: JobResult
    error: JobError | None = None
    queued_position: int | None = None


# --- A03 ---
class RowPatch(Model):
    selected_id: str | None = None
    clear_selection: bool | None = None
    review_status: Literal["pending", "approved", "rejected", "excluded"] | None = None
    note: str | None = None
    thickness_mm: float | None = Field(default=None, gt=0, le=1000)
    density_kg_m3: float | None = Field(default=None, gt=0)
    unit_mass_kg: float | None = Field(default=None, gt=0, le=1000)


class RowUpdateResponse(Model):
    row: Row
    summary: Summary


# --- 오류 ---
class ErrorBody(Model):
    detail: str
    code: str | None = None
    meta: dict | None = None
