"""목록(849행) <-> data/raw 파일 자동 연결기. DB 없이 돈다.

실행(Backend에서):
  uv run python -m tools.link_files --list ../docs/LCA/data/lci-db-list-ecosq-849.csv --raw ../data/raw --out ../data/raw/download-map.csv

1순위는 목록의 다운로드 파일명 정확 일치(exact). 파일명이 목록에 없는 파일만 이름·연도로 짝을 찾는다(auto/review/unmatched).
키는 lci_database_sn(dataset_id = list-<sn>). 결과 CSV·리포트는 data/raw 아래(git 제외)에 쓴다.
"""
import argparse
import csv
import hashlib
import html
import json
import math
import random
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from tools.flow_properties import load_table, parse_flow_property, parse_unit_group

KEITI = "한국환경산업기술원"
# 보조 경로(fuzzy)는 자체 평가 정확도가 65%라 점수와 관계없이 review 로만 낸다(T10a.1). 아래 두 값은 auto 를 다시 켤 때의 기준으로 남겨 둔다
AUTO_SCORE = 0.75
AUTO_MARGIN = 0.10
MIN_CANDIDATE = 0.30  # 이보다 낮은 점수는 후보로 치지 않는다(잡음). 후보가 없으면 unmatched
CONTENT_MARGIN = 0.10  # 한 파일을 이름이 다른 여러 행이 가리킬 때, 1·2위 이름 점수 차이가 이보다 작으면 정하지 않고 review
OUT_COLS = ["file", "sha", "kind", "list_row", "name_ko", "name_en", "org", "year", "score", "margin", "status", "method", "name_check",
            "top3", "confirmed"]
STATUS_ORDER = {"review": 0, "content_mismatch": 1, "unmatched": 2, "auto": 3, "exact": 4}
EXTS = {".zip": "xml", ".xls": "excel", ".xlsx": "excel"}
GATE_TO_GATE = re.compile(r"gate[\s-]*to[\s-]*gate", re.I)
OWN_OUTPUTS ={"download-map.csv", "link-report.md", "link-features.json"}  # 이 도구가 같은 폴더에 쓰는 파일


# ---------- 작은 도구 ----------
def normalize(s):
    """공백·괄호·하이픈·밑줄을 지우고 소문자로."""
    return re.sub(r"[\s()\[\]（）\-‐‑–—_]", "", s or "").lower()


def normalize_filename(name):
    """정확 일치에 실패한 파일명 비교용: NFC, 확장자 소문자, ' (숫자)' 꼬리 제거, 공백·'_'·제어 문자 제거.
    제어 문자: 목록의 '골판지\\x80 GtG_CtG sheet.xls' 처럼 사이트 목록에 깨진 글자가 끼어 있다."""
    name = "".join(ch for ch in unicodedata.normalize("NFC", name) if unicodedata.category(ch) != "Cc")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    return re.sub(r"[\s_]", "", stem) + ("." + ext.lower() if dot else "")


def excel_year(v):
    """엑셀 일련번호(36799), 연도 숫자, '2003년 7월' 같은 글자, datetime 에서 연도를 뽑는다. 못 뽑으면 None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.year
    if isinstance(v, str):
        text = v.strip()
        try:
            v = float(text)
        except ValueError:
            m = re.search(r"(?:19|20)\d{2}", text)
            return int(m[0]) if m else None
    if isinstance(v, (int, float)):
        if 1900 <= v <= 2100:
            return int(v)
        if 1 <= v < 60000:
            return (datetime(1899, 12, 30) + timedelta(days=float(v))).year
    return None


FLAGS = {
    "recycled": ("recycl", "재활용", "재생"),
    "stainless": ("stainless", "스테인리스", "스테인레스"),
    "primary": ("primary", "1차", "신재"),
}
ALLOY = re.compile(r"\b[A-Z]\d{4}\b")


def flags(text):
    t = text.lower()
    return {k for k, words in FLAGS.items() if any(w in t for w in words)}


def hard_conflict(a, b):
    """합금 기호가 다르거나, 재활용·스테인리스·1차 여부가 다르면 같은 데이터셋일 수 없다."""
    if flags(a) != flags(b):
        return True
    alloys_a, alloys_b = set(ALLOY.findall(a.upper())), set(ALLOY.findall(b.upper()))
    return bool(alloys_a and alloys_b and alloys_a != alloys_b)


def grams(s):
    s = normalize(s)
    return Counter(s[i:i + 3] for i in range(len(s) - 2)) if len(s) >= 3 else Counter([s] if s else [])


def cosine(a, b):
    dot = sum(v * b[k] for k, v in a.items() if k in b)
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def tokens(s):
    return set(re.findall(r"[a-z0-9]{2,}|[가-힣]{2,}", (s or "").lower()))


def name_score(a, b):
    """문자 3-gram 코사인 0.6 + 단어 일치(자카드) 0.4."""
    if not a or not b:
        return 0.0
    ta, tb = tokens(a), tokens(b)
    jaccard = len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0
    return 0.6 * cosine(grams(a), grams(b)) + 0.4 * jaccard


def korean_tail(filename):
    """'LCI-2024-312_폴리프로필렌(PP) 사출 공정.zip' 의 국문명 꼬리. 없으면 ''."""
    m = re.match(r"^\(?(LCI-\d{4}-\d+)\)?[ _]*(.*)\.zip$", filename)
    tail = m[2].strip() if m else ""
    return tail if re.search("[가-힣]", tail) else ""


def file_year(filename):
    m = re.match(r"^\(?LCI-(\d{4})-\d+", filename)
    return int(m[1]) if m else None


# ---------- 파일에서 단서 뽑기 ----------
def _tags(text, tag):
    pat = r"<(?:\w+:)?%s\b[^>]*>(.*?)</(?:\w+:)?%s>" % (tag, tag)
    out = []
    for m in re.finditer(pat, text, re.S):
        value = html.unescape(re.sub(r"<[^>]+>", "", m[1])).strip()
        if value:
            out.append(re.sub(r"\s+", " ", value))
    return out


NON_ELEMENTARY = {"Product flow", "Waste flow", "Other flow"}  # 기준 흐름이 될 수 있는 흐름 종류


def _read(zf, folder, uuid):
    for n in zf.namelist():
        if f"/{folder}/{uuid}" in n:
            return zf.read(n).decode("utf-8", "replace")
    return None


def _flow_unit(zf, flow_id, table=None):
    """기준흐름의 단위: flow -> flowproperty -> unitgroup -> 기준 단위 이름.
    흐름 속성(또는 그 단위 그룹)을 ① 꾸러미 안에서 찾고, 없으면 ② 국가 DB 꾸러미 전체에서 만든 표(tools.flow_properties)에서 찾는다.
    반환: (단위 또는 None, "package" | "table" | None, 풀지 못한 흐름 속성 UUID 또는 None)."""
    flow = _read(zf, "flows", flow_id)
    prop = re.search(r'referenceToFlowPropertyDataSet[^>]*refObjectId="([^"]+)"', flow or "")
    if not prop:
        return None, None, None  # 흐름 파일이나 흐름 속성 참조가 없다(흐름 속성까지 가지 못함)
    fp = _read(zf, "flowproperties", prop[1])
    if fp:
        _, ug_id = parse_flow_property(fp)
        ug = _read(zf, "unitgroups", ug_id) if ug_id else None
        unit = parse_unit_group(ug)[1] if ug else None
        if unit:
            return unit, "package", None
    hit = (load_table() if table is None else table).get(prop[1])
    if hit:
        return hit["reference_unit"], "table", None
    return None, None, prop[1]


def _flow_type(zf, flow_id):
    flow = _read(zf, "flows", flow_id)
    m = re.search(r"<typeOfDataSet>([^<]*)<", flow or "")
    return m[1].strip() if m else None


def _estimate_reference(zf, text):
    """quantitativeReference 가 없을 때: 비요소(Product/Waste/Other) 출력 중 meanAmount 가 정확히 1.0 인 교환이 하나뿐이면 그 dataSetInternalID.
    둘 이상이거나 없으면 None(추측하지 않는다). 흐름 파일이 없어 종류를 모르는 교환은 세지 않는다."""
    found = []
    for internal_id, body in re.findall(r'<exchange dataSetInternalID="(\d+)">(.*?)</exchange>', text, re.S):
        if "<exchangeDirection>Output<" not in body:
            continue
        amount = re.search(r"<meanAmount>([^<]*)<", body)
        try:
            one = amount is not None and float(amount[1]) == 1.0
        except ValueError:
            one = False
        flow_id = re.search(r'refObjectId="([^"]+)"', body)
        if one and flow_id and _flow_type(zf, flow_id[1]) in NON_ELEMENTARY:
            found.append(internal_id)
    return found[0] if len(found) == 1 else None


# 영향평가 결과(<LCIAResult>)에서 읽는 기후변화 4개 항목. shortDescription 이 정확히 이 이름인 것만 (다른 영향범주는 읽지 않는다)
GWP_LABELS = {"Climate change": "total", "Climate change-Fossil": "fossil", "Climate change-Biogenic": "biogenic",
              "Climate change-Land use and land use change": "luluc"}


def read_lcia(text):
    """기후변화 4개 항목의 meanAmount(문자열 그대로)와 합계 항목의 방법 버전. 하나도 없으면 None.
    값은 데이터셋의 기준 흐름 양당 결과다(1 기준 단위당으로 바꾸는 일은 적재기가 한다)."""
    out = {}
    for body in re.findall(r"<(?:\w+:)?LCIAResult>(.*?)</(?:\w+:)?LCIAResult>", text, re.S):
        key = GWP_LABELS.get((_tags(body, "shortDescription") or [None])[0])
        if key is None or key in out:
            continue
        amount = re.search(r"<meanAmount>([^<]*)<", body)
        out[key] = amount[1].strip() if amount else None
        if key == "total":
            version = re.search(r'referenceToLCIAMethodDataSet[^>]*\sversion="([^"]*)"', body)
            out["method_version"] = version[1] if version else None
    return out or None


def read_zip(path):
    """XML ZIP 한 개의 단서. 크기 0인 항목은 건너뛴다."""
    with zipfile.ZipFile(path) as zf:
        procs = [i for i in zf.infolist() if "/processes/" in i.filename and i.filename.endswith(".xml") and i.file_size > 0]
        if not procs:
            raise ValueError("processes 폴더에 읽을 XML이 없음")
        text = zf.read(procs[0].filename).decode("utf-8", "replace")
        head = text[: text.find("<exchanges>")] if "<exchanges>" in text else text[:60000]
        names = _tags(head, "baseName")
        for tag in ("synonyms", "treatmentStandardsRoutes", "mixAndLocationTypes"):
            for v in _tags(head, tag):
                names += [p.strip() for p in v.split(";") if p.strip()]
        feat = {
            "uuid": (_tags(head, "UUID") or [None])[0],
            "reference_year": excel_year((_tags(head, "referenceYear") or [None])[0]),
            "geography": (re.findall(r'<locationOfOperationSupplyOrProduction[^>]*location="([^"]*)"', head) or [None])[0],
            "classification": _tags(head, "class"),
            "dataset_type": (_tags(head, "typeOfDataSet") or [None])[0],
            "allocation": (_tags(head, "LCIMethodApproaches") or [None])[0],
            "cutoff": (_tags(head, "dataCutOffAndCompletenessPrinciples") or [None])[0],
            "tech": ((_tags(head, "technologyDescriptionAndIncludedProcesses") or [""])[0])[:300],
            "ref_flow": None,
            "lcia": read_lcia(text),
        }
        ref = re.search(r"<referenceToReferenceFlow>(\d+)<", head)
        ref_id, estimated = (ref[1], False) if ref else (_estimate_reference(zf, text), True)
        if ref_id is not None:
            i = text.find('<exchange dataSetInternalID="%s">' % ref_id)
            if i >= 0:
                seg = text[i:i + 2500]
                flow_id = re.search(r'refObjectId="([^"]+)"', seg)
                name = (_tags(seg, "shortDescription") or [None])[0]
                amount = re.search(r"<meanAmount>([^<]*)<", seg)
                if name:
                    names.append(name)
                unit, source, missing = _flow_unit(zf, flow_id[1]) if flow_id else (None, None, None)
                feat["ref_flow"] = {
                    "name": name,
                    "amount": amount[1] if amount else None,
                    "unit": unit,
                    "unit_source": source,  # package: 꾸러미 안 / table: 흐름 속성 표 / None: 못 찾음
                    "missing_flow_property": missing,
                    "estimated": estimated,  # XML 에 기준 흐름 지정이 없어 "양 1.0 비요소 출력이 하나뿐" 규칙으로 정함
                }
        feat["names"] = list(dict.fromkeys(names))
        # XML 은 시스템 경계 칸이 없어 본문의 'gate to gate' 표현을 찾아 앞뒤 80자를 남긴다(T10b 가 이슈로 기록, 판단은 사람)
        g2g = GATE_TO_GATE.search(text)
        if g2g:
            excerpt = html.unescape(re.sub(r"<[^>]+>", " ", text[max(0, g2g.start() - 80):g2g.end() + 80]))
            feat["boundary_hint"] = re.sub(r"\s+", " ", excerpt).strip()
        # 파일 자기 이름: baseName + 기준흐름 이름 (이름 점검·사이트 파일 오류 판단용)
        own = _tags(head, "baseName") + ([feat["ref_flow"]["name"]] if feat["ref_flow"] and feat["ref_flow"]["name"] else [])
        feat["own_names"] = list(dict.fromkeys(own))
        return feat


def sheets_of(path):
    """[(시트 이름, [행(값 목록)])]. .xls 는 xlrd, .xlsx 는 openpyxl."""
    if path.suffix.lower() == ".xls":
        import xlrd
        book = xlrd.open_workbook(str(path))
        return [(s.name, [s.row_values(r) for r in range(s.nrows)]) for s in book.sheets()]
    import openpyxl
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in book.worksheets]
    finally:
        book.close()


def read_excel(path):
    """엑셀 한 개의 단서: 프로세스 명칭, 기준흐름(명칭·단위·양), 시스템 경계, 연도."""
    sheets = sheets_of(path)
    if not sheets:
        raise ValueError("시트가 없음")
    feat = {"names": [], "ref_flow": {"name": None, "unit": None, "amount": None}, "boundary": None, "year": None}
    section = None
    for row in sheets[0][1]:
        cells = [str(c).strip() for c in row if c not in ("", None) and str(c).strip()]
        if not cells:
            continue
        label, value = cells[0], cells[1] if len(cells) > 1 else ""
        m = re.match(r"(\d+)\.", label)
        if m:
            section = int(m[1])
            if section == 4 and value:
                feat["boundary"] = value
            continue
        # 177.xls 는 "3. 기준 참조량" 머리 행이 ")" 한 글자로 깨져 있다. 2절에 "(1) 유형"은 다른 엑셀(337개)에 없으므로 3절의 시작으로 본다
        if section == 2 and re.sub(r"^\(\d+\)\s*", "", label) == "유형":
            section = 3
        if section == 2 and "프로세스 명칭" in label and value:
            feat["names"].append(value)
        elif section == 3 and value:
            key = {"명칭": "name", "단위": "unit", "양": "amount"}.get(re.sub(r"^\(\d+\)\s*", "", label))
            if key:
                feat["ref_flow"][key] = value
        elif section == 7 and "시작일" in label:
            feat["year"] = feat["year"] or excel_year(value)
    if feat["ref_flow"]["name"]:
        feat["names"].append(feat["ref_flow"]["name"])
    admin = next((rows for name, rows in sheets if "관리" in name), sheets[2][1] if len(sheets) > 2 else [])
    for row in admin:
        cells = [c for c in row if c not in ("", None)]
        if len(cells) > 1 and "작성완료일" in str(cells[0]):
            feat["year"] = excel_year(cells[1]) or feat["year"]
            break
    feat["names"] = list(dict.fromkeys(feat["names"]))
    feat["own_names"] = feat["names"]  # 엑셀은 프로세스 명칭 + 기준흐름 명칭이 곧 자기 이름
    return feat


# ---------- 점수·후보 ----------
def read_list(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r["sn"] = int(r["lci_database_sn"])
            r["year_n"] = int(r["year"]) if str(r["year"]).strip().isdigit() else None
            r["file"] = r["zip_file"] or r["excel_file"]
            rows.append(r)
    return rows


def candidates(feat, rows):
    """블록 안에서 점수 순 [(점수, 행)]. XML: 한국환경산업기술원 + 파일명 연도, 엑셀: 그 밖의 기관 + 연도 ±1."""
    xml = feat["kind"] == "xml"
    out = []
    for r in rows:
        is_keiti = KEITI in r["org"]
        if xml != is_keiti:
            continue
        if xml and feat.get("year") and r["year_n"] != feat["year"]:
            continue
        if not xml and feat.get("year") and r["year_n"] and abs(r["year_n"] - feat["year"]) > 1:
            continue
        names = feat["names"]
        tail = feat.get("tail", "")
        if tail and normalize(tail) == normalize(r["name_ko"]) or any(normalize(n) == normalize(r["name_ko"]) for n in names if not xml):
            s = 1.0
        else:
            if xml:
                s = max([name_score(r["name_en"], n) for n in names] + ([name_score(r["name_ko"], tail)] if tail else []), default=0.0)
            else:
                s = max((name_score(r["name_ko"], n) for n in names), default=0.0)
            if hard_conflict(f'{r["name_ko"]} {r["name_en"]}', " ".join(names + [tail])):
                s = 0.0
        if s >= MIN_CANDIDATE:
            out.append((s, r))
    out.sort(key=lambda x: (-x[0], x[1]["sn"]))
    return out


def own_score(feat, r):
    """파일 자기 이름과 목록 이름(국문·영문 중 높은 쪽)의 점수. 보조 경로와 같은 점수 함수."""
    return max((name_score(x, n) for n in feat.get("own_names") or [] for x in (r["name_ko"], r["name_en"])), default=0.0)


def top3_text(cands):
    return ";".join(f'{r["sn"]}:{s:.2f}' for s, r in cands[:3])


# ---------- 파일 목록 ----------
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_raw(raw):
    """(파일 그룹, 지원하지 않는 항목). 해시가 같은 파일은 한 그룹."""
    groups, other = {}, []
    for p in sorted(Path(raw).iterdir()):
        if p.name in OWN_OUTPUTS:
            continue
        if p.is_dir() or p.suffix.lower() not in EXTS:
            other.append(p.name)
            continue
        groups.setdefault(sha256(p), []).append(p)
    return groups, other


def read_previous(out):
    """사람이 확인한(confirmed=Y) 행을 파일 이름별로 모은다."""
    kept = defaultdict(list)
    if Path(out).exists():
        with open(out, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("confirmed") or "").strip().upper() == "Y":
                    kept[r["file"]].append(r)
    return kept


# ---------- 본체 ----------
def link(list_path, raw, out):
    rows = read_list(list_path)
    by_sn = {r["sn"]: r for r in rows}
    groups, other = scan_raw(raw)
    previous = read_previous(out)
    errors, features = [], {}

    # 파일 그룹: 대표 이름 = 목록에 있는 이름, 없으면 가장 짧은 이름
    listed_names = {r["file"] for r in rows if r["file"]}
    files = []  # {name, names, sha, kind, path, dups}
    for sha, paths in groups.items():
        names = sorted(p.name for p in paths)
        name = next((n for n in names if n in listed_names), min(names, key=len))
        path = next(p for p in paths if p.name == name)
        files.append({"name": name, "names": names, "sha": sha, "kind": EXTS[path.suffix.lower()], "path": path})
    files.sort(key=lambda f: f["name"])

    out_rows, claimed = [], set()
    # 1) 사람이 확인한 행은 그대로 보존 (파일 그룹의 어느 이름으로 적혀 있어도 된다)
    present = {n for f in files for n in f["names"]}
    dropped_confirmed = 0
    for fname, prev_rows in previous.items():
        if fname not in present:
            dropped_confirmed += len(prev_rows)
            continue
        for pr in prev_rows:
            sn = int(pr["list_row"]) if str(pr["list_row"]).strip().isdigit() else None
            r = by_sn.get(sn)
            if r:
                pr.update(name_ko=r["name_ko"], name_en=r["name_en"], org=r["org"], year=r["year"])
                claimed.add(sn)
            out_rows.append({c: pr.get(c, "") for c in OUT_COLS})
    confirmed_files = set(previous) & present

    def is_confirmed(f):
        return bool(set(f["names"]) & confirmed_files)

    # 2) 모든 파일에서 단서를 먼저 읽는다 (사이트 파일 오류 판단·이름 점검·보조 경로에 쓴다)
    for f in files:
        try:
            feat = read_zip(f["path"]) if f["kind"] == "xml" else read_excel(f["path"])
        except Exception as e:  # 읽지 못한 파일은 리포트에 남기고 계속
            errors.append((f["name"], f"{type(e).__name__}: {e}"))
            feat = {"names": [], "own_names": [], "ref_flow": None}
        feat["kind"] = f["kind"]
        feat["year"] = file_year(f["name"]) if f["kind"] == "xml" else feat.get("year")
        feat["tail"] = korean_tail(f["name"]) if f["kind"] == "xml" else ""
        f["feat"] = feat
        features[f["name"]] = {"sha": f["sha"], "kind": f["kind"], **{k: v for k, v in feat.items() if k not in ("kind", "tail")}}

    # 3) 파일명 일치: 그대로(name), 안 되면 정규화한 이름(name_norm)
    norm_rows = defaultdict(list)  # 목록 파일명이 data/raw 에 그대로는 없는 행만
    for r in rows:
        if r["file"] and r["file"] not in present:
            norm_rows[normalize_filename(r["file"])].append(r)
    mismatches = []  # (행, 파일, 실제 주인 행)
    for f in files:
        f["exact"], f["linked"] = [], False
        if is_confirmed(f):
            f["linked"] = True
            continue
        hits = [(r, "name") for r in rows if r["file"] in f["names"]]
        if not hits:
            keys = sorted({normalize_filename(n) for n in f["names"]})
            hits = [(r, "name_norm") for k in keys for r in norm_rows.get(k, [])]
        if not hits:
            continue
        f["linked"] = True
        scores = {r["sn"]: own_score(f["feat"], r) for r, _ in hits}
        status = {r["sn"]: "exact" for r, _ in hits}
        note = {}
        # 사이트 파일 오류: 한 파일 내용을 국문명이 다른 여러 행이 가리키면 파일 자기 이름에 가장 가까운 행만 남긴다
        if len({r["name_ko"] for r, _ in hits}) > 1:
            order = sorted(hits, key=lambda h: (-scores[h[0]["sn"]], h[0]["sn"]))
            best = order[0][0]
            if scores[best["sn"]] - scores[order[1][0]["sn"]] < CONTENT_MARGIN:
                listing = ";".join(f'{r["sn"]}:{scores[r["sn"]]:.2f}' for r, _ in order)
                for r, _ in hits:
                    status[r["sn"]], note[r["sn"]] = "review", listing
            else:
                for r, _ in order[1:]:
                    status[r["sn"]], note[r["sn"]] = "content_mismatch", f'belongs_to:{best["sn"]}'
                    mismatches.append((r, f, best))
        for r, method in hits:
            sn = r["sn"]
            claimed.add(sn)  # content_mismatch 행도 보조 경로에 다시 넣지 않는다(T10b 가 파일 없음으로 적재)
            out_rows.append({"file": r["file"] if r["file"] in f["names"] else f["name"], "sha": f["sha"][:12], "kind": f["kind"],
                             "list_row": sn, "name_ko": r["name_ko"], "name_en": r["name_en"], "org": r["org"], "year": r["year"],
                             "score": "1.000" if status[sn] == "exact" else f"{scores[sn]:.3f}", "margin": "", "status": status[sn],
                             "method": method, "name_check": f"{scores[sn]:.3f}" if status[sn] == "exact" else "",
                             "top3": note.get(sn, ""), "confirmed": ""})
        f["exact"] = [sn for sn, st in status.items() if st == "exact"]

    # 4) 나머지 파일은 단서로 짝 찾기(보조 경로). 정확도가 낮아 auto 없이 review 로만 낸다
    rest = [f for f in files if not f["linked"]]
    pool = [r for r in rows if r["sn"] not in claimed]
    ranked = {f["name"]: candidates(f["feat"], pool) for f in rest}

    pairs = sorted(((s, f["name"], r["sn"]) for f in rest for s, r in ranked[f["name"]]), key=lambda x: (-x[0], x[1], x[2]))
    chosen, used = {}, set()
    for s, name, sn in pairs:
        if name not in chosen and sn not in used:
            chosen[name] = (s, sn)
            used.add(sn)
    for f in rest:
        cands = ranked[f["name"]]
        base = {"file": f["name"], "sha": f["sha"][:12], "kind": f["kind"], "method": "fuzzy", "name_check": "",
                "top3": top3_text(cands), "confirmed": ""}
        if f["name"] in chosen:
            s, sn = chosen[f["name"]]
            r = by_sn[sn]
            margin = s - (cands[1][0] if len(cands) > 1 else 0.0)
            out_rows.append({**base, "list_row": sn, "name_ko": r["name_ko"], "name_en": r["name_en"], "org": r["org"], "year": r["year"],
                             "score": f"{s:.3f}", "margin": f"{margin:.3f}", "status": "review"})
        else:
            out_rows.append({**base, "list_row": "", "name_ko": "", "name_en": "", "org": "", "year": "", "score": "", "margin": "",
                             "status": "unmatched"})

    out_rows.sort(key=lambda r: (STATUS_ORDER.get(r["status"], 9) if r["confirmed"] != "Y" else 5, r["file"], str(r["list_row"])))
    own_names = {n: f["feat"].get("own_names") or [] for f in files for n in f["names"]}
    return {"rows": rows, "by_sn": by_sn, "files": files, "groups": groups, "other": other, "out_rows": out_rows,
            "errors": errors, "features": features, "claimed": claimed, "dropped_confirmed": dropped_confirmed,
            "mismatches": mismatches, "own_names": own_names}


def write_csv(path, out_rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        w.writerows(out_rows)


# ---------- 자체 평가 ----------
def blind_eval(result, files, hide_year):
    """정확 일치로 붙은 XML 파일을 단서만으로 다시 짝지어 같은 행에 붙는지 본다(전체 목록 대상, 다른 파일과 경쟁 없음)."""
    exact = {f["name"]: f["exact"] for f in files}
    outcomes = []
    for f in files:
        feat = dict(f["feat"], tail="")
        if hide_year:
            feat["year"] = None
        cands = candidates(feat, result["rows"])
        top = cands[0][1]["sn"] if cands else None
        outcomes.append((f["name"], exact[f["name"]], top, cands[0][0] if cands else 0.0, top in exact[f["name"]]))
    return outcomes


def self_eval(result, seed=20261017):
    xml_exact = [f for f in result["files"] if f["kind"] == "xml" and f.get("exact") and f["feat"].get("names")]
    tails = [f for f in xml_exact if korean_tail(f["name"])]
    sample = random.Random(seed).sample(xml_exact, min(20, len(xml_exact)))
    return blind_eval(result, tails, hide_year=False), blind_eval(result, sample, hide_year=True)


# ---------- 리포트 ----------
def report(result, evals):
    rows, files, out_rows = result["rows"], result["files"], result["out_rows"]
    status = Counter(r["status"] for r in out_rows)
    exact_by = Counter(r["method"] for r in out_rows if r["status"] == "exact")
    linked = {int(r["list_row"]) for r in out_rows if str(r["list_row"]).strip().isdigit() and r["status"] != "content_mismatch"}
    site_err = {int(r["list_row"]) for r in out_rows if r["status"] == "content_mismatch"}
    present = {n for f in files for n in f["names"]}
    missing_rows = [r for r in rows if r["sn"] not in linked]
    no_name = [r for r in missing_rows if not r["file"]]
    to_download = [r for r in missing_rows if r["file"] and r["file"] not in present]
    wrong_file = [r for r in missing_rows if r["sn"] in site_err]
    kinds = Counter(f["kind"] for f in files)
    dups = [f for f in files if len(f["names"]) > 1]
    tail_eval, blind = evals
    lines = [
        "# link-report (자동 생성, git 제외)", "",
        "## 요약",
        f"- 목록 {len(rows)}행 (파일명 있음 {sum(1 for r in rows if r['file'])}, 없음 {sum(1 for r in rows if not r['file'])})",
        f"- data/raw 파일 {sum(len(g) for g in result['groups'].values())}개 → 해시 중복 제거 후 {len(files)}개 (XML ZIP {kinds['xml']}, 엑셀 {kinds['excel']})",
        f"- 해시가 같은 중복 그룹 {len(dups)}개: " + ", ".join(" = ".join(f["names"]) for f in dups),
        f"- 결과 행: exact {status['exact']} (name {exact_by['name']}, name_norm {exact_by['name_norm']}), content_mismatch {status['content_mismatch']}, auto {status['auto']}, review {status['review']}, unmatched {status['unmatched']}",
        f"- 연결된 목록 행 {len(linked)}행 / 파일이 없는 목록 행 {len(missing_rows)}행 (다운로드 필요 {len(to_download)}, 사이트 파일 오류 {len(wrong_file)}, 목록에 파일명 없음 {len(no_name)})",
        f"- 읽지 못한 파일 {len(result['errors'])}개, 지원하지 않는 항목 {len(result['other'])}개, 확인 행 보존 중 파일이 사라져 버린 것 {result['dropped_confirmed']}행",
        "",
        "## 파일이 없는 목록 행 (분류별)", "", "| 분류 | 다운로드 필요 | 사이트 파일 오류 | 목록에 파일명 없음 |", "|---|---|---|---|",
    ]
    cats = sorted({r["category"] for r in missing_rows})
    for c in cats:
        lines.append(f"| {c} | {sum(1 for r in to_download if r['category'] == c)} | {sum(1 for r in wrong_file if r['category'] == c)} "
                     f"| {sum(1 for r in no_name if r['category'] == c)} |")
    own = result["own_names"]
    lines += ["", "## 사이트 파일 오류 (content_mismatch: T10b 는 파일 없음으로 적재)", "",
              "| 행 sn | 목록 이름 | 파일 | 파일 자기 이름 | 실제 주인 sn |", "|---|---|---|---|---|"]
    for r, f, best in result["mismatches"]:
        lines.append(f"| {r['sn']} | {r['name_ko']} | {r['file']} | {' / '.join(own.get(f['name'], []))} | {best['sn']} {best['name_ko']} |")
    undecided = [r for r in out_rows if r["status"] == "review" and r["method"] != "fuzzy"]
    if undecided:
        lines += ["", "한 파일을 여러 행이 가리키지만 이름 점수 차이가 작아 정하지 못한 것(review):", ""]
        lines += [f"- `{r['file']}` sn {r['list_row']} {r['name_ko']} (점수 {r['top3']})" for r in undecided]
    norm = [r for r in out_rows if r["method"] == "name_norm"]
    if norm:
        lines += ["", "## 파일명 정규화로 붙은 파일 (name_norm)", ""]
        lines += [f"- `{r['file']}` → {r['status']} sn {r['list_row']} {r['name_ko']} (목록 파일명 `{result['by_sn'][int(r['list_row'])]['file']}`)" for r in norm]
    checks = sorted((r for r in out_rows if r["status"] == "exact" and r["name_check"]), key=lambda r: (float(r["name_check"]), int(r["list_row"])))
    lines += ["", "## 이름 점검 낮은 순 15건 (exact, 상태는 바꾸지 않음)", "", "| sn | 목록 국문명 | 파일 자기 이름 | 점수 |", "|---|---|---|---|"]
    lines += [f"| {r['list_row']} | {r['name_ko']} | {' / '.join(own.get(r['file'], [])) or '—'} | {r['name_check']} |" for r in checks[:15]]
    lines += ["", "## 목록에 없는 파일 (보조 경로, 모두 review 또는 unmatched)", ""]
    for r in out_rows:
        if r["method"] == "fuzzy":
            lines.append(f"- `{r['file']}` → {r['status']} {r['list_row']} {r['name_ko']} (점수 {r['score']}, 후보 {r['top3']})")
    if result["other"]:
        lines += ["", "## 지원하지 않는 항목", ""] + [f"- `{n}`" for n in result["other"]]
    if result["errors"]:
        lines += ["", "## 읽지 못한 파일", ""] + [f"- `{n}`: {e}" for n, e in result["errors"]]
    ok_t = sum(1 for o in tail_eval if o[4])
    ok_b = sum(1 for o in blind if o[4])
    lines += ["", "## 자체 평가", "",
              f"- 한글 꼬리 ZIP {len(tail_eval)}개를 꼬리 없이(연도는 파일명 사용) 돌렸을 때 같은 행: **{ok_t}/{len(tail_eval)}**",
              f"- 정확 일치 XML 무작위 {len(blind)}건을 파일명 없이(연도 단서도 숨김) 돌렸을 때 같은 행: **{ok_b}/{len(blind)}** (보조 경로 정확도 {ok_b / len(blind):.0%})" if blind else "- (무작위 평가 대상 없음)", ""]
    for title, outs in (("꼬리 평가 실패", [o for o in tail_eval if not o[4]]), ("무작위 평가 전체", blind)):
        if outs:
            lines += [f"### {title}", "", "| 파일 | 정답 sn | 1순위 sn | 점수 | 일치 |", "|---|---|---|---|---|"]
            lines += [f"| {o[0]} | {','.join(map(str, o[1]))} | {o[2]} | {o[3]:.2f} | {'O' if o[4] else 'X'} |" for o in outs]
            lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="목록 <-> 파일 자동 연결기 (download-map 생성)")
    ap.add_argument("--list", required=True, help="목록 CSV")
    ap.add_argument("--raw", required=True, help="원본 파일 폴더(data/raw)")
    ap.add_argument("--out", required=True, help="download-map.csv 경로")
    args = ap.parse_args(argv)
    out = Path(args.out)

    result = link(args.list, args.raw, out)
    evals = self_eval(result)
    write_csv(out, result["out_rows"])
    (out.parent / "link-features.json").write_text(json.dumps(result["features"], ensure_ascii=False, indent=1), encoding="utf-8")
    text = report(result, evals)
    (out.parent / "link-report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"쓴 파일: {out}, {out.parent / 'link-report.md'}, {out.parent / 'link-features.json'}")


if __name__ == "__main__":
    main()
