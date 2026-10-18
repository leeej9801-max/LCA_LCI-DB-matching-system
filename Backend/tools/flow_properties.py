"""ILCD 흐름 속성 표: data/raw 의 모든 ZIP 에서 흐름 속성 UUID → (이름, 단위 그룹 이름, 기준 단위, 정의가 있던 꾸러미)를 모은다.

실행(Backend에서): uv run python -m tools.flow_properties --raw ../data/raw [--out app/data/ilcd_flow_properties.csv]

어떤 꾸러미는 기준 흐름이 가리키는 흐름 속성 파일을 담고 있지 않다(예: LCI-2024-314 SPOT 용접). 같은 국가 DB 의 다른 꾸러미에 정의가
있으면 그 정의를 쓰려고 표를 만든다(link_files 가 ① 꾸러미 안 → ② 이 표 순으로 찾는다). 값은 모두 원본 XML 에서 읽는다(손으로 쓰지 않는다).
같은 UUID 가 여러 꾸러미에 있으면 파일 이름순 첫 꾸러미를 출처로 적고, 정의가 서로 다르면 멈춘다.
"""
import argparse
import csv
import re
import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "ilcd_flow_properties.csv"
COLUMNS = ["flow_property_uuid", "flow_property_name", "unit_group_name", "reference_unit", "source_file"]


def _name(xml):
    m = re.search(r"<common:name[^>]*>([^<]*)</common:name>", xml)
    return m[1].strip() if m else None


def parse_flow_property(xml):
    """(흐름 속성 이름, 단위 그룹 UUID)."""
    ug = re.search(r'referenceToReferenceUnitGroup[^>]*refObjectId="([^"]+)"', xml)
    return _name(xml), ug[1] if ug else None


def parse_unit_group(xml):
    """(단위 그룹 이름, 기준 단위 이름)."""
    idx = re.search(r"<referenceToReferenceUnit>(\d+)<", xml)
    unit = re.search(r'<unit dataSetInternalID="%s">.*?<name>([^<]*)</name>' % idx[1], xml, re.S) if idx else None
    return _name(xml), unit[1].strip() if unit else None


def uuid_of(entry_name):
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", entry_name.rsplit("/", 1)[-1])
    return m[1] if m else None


def scan(raw):
    """[표 행 dict] (흐름 속성 UUID 순). 단위 그룹은 다른 꾸러미에 있어도 찾는다."""
    props, groups = {}, {}  # uuid → (이름, ug uuid, 꾸러미) / uuid → (이름, 기준 단위)
    for path in sorted(Path(raw).glob("*.zip")):
        with zipfile.ZipFile(path) as zf:
            for entry in zf.infolist():
                if entry.file_size == 0 or not entry.filename.endswith(".xml"):
                    continue
                folder = entry.filename.rsplit("/", 2)[-2] if entry.filename.count("/") >= 1 else ""
                if folder not in ("flowproperties", "unitgroups"):
                    continue
                u = uuid_of(entry.filename)
                xml = zf.read(entry).decode("utf-8", "replace")
                if folder == "flowproperties":
                    name, ug = parse_flow_property(xml)
                    if u in props and props[u][:2] != (name, ug):
                        raise SystemExit(f"흐름 속성 {u} 의 정의가 꾸러미마다 다릅니다: {props[u]} / {(name, ug, path.name)}")
                    props.setdefault(u, (name, ug, path.name))
                else:
                    g = parse_unit_group(xml)
                    if u in groups and groups[u] != g:
                        raise SystemExit(f"단위 그룹 {u} 의 정의가 꾸러미마다 다릅니다: {groups[u]} / {g}")
                    groups.setdefault(u, g)
    rows = []
    for u, (name, ug, source) in sorted(props.items()):
        ug_name, unit = groups.get(ug, (None, None))
        rows.append({"flow_property_uuid": u, "flow_property_name": name, "unit_group_name": ug_name, "reference_unit": unit,
                     "source_file": source})
    return rows


def load_table(path=OUT):
    """{흐름 속성 UUID: 표 행}. 기준 단위가 비어 있는 행은 넣지 않는다(풀린 것으로 치지 않는다)."""
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["flow_property_uuid"]: r for r in csv.DictReader(f) if r["reference_unit"]}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="ILCD 흐름 속성 표 만들기")
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    rows = scan(args.raw)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"흐름 속성 {len(rows)}개 → {args.out} (기준 단위 없음 {sum(1 for r in rows if not r['reference_unit'])}개)")


if __name__ == "__main__":
    main()
