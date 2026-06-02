"""
validate_bpmn.py
Валидирует BPMN файл — без API, чистый код.
Выдаёт JSON-отчёт, который OpenCode читает и интерпретирует.

Проверяет:
  1. XML синтаксис
  2. Логика: JSON ↔ BPMN соответствие
  3. Связность: висячие элементы, шлюзы без условий
  4. Координаты: перекрытия, элементы вне пула/lane, waypoints

Использование:
  python scripts/validate_bpmn.py
  python scripts/validate_bpmn.py --bpmn output/process.bpmn --json output/process.json
"""

import json
import sys
import argparse
from pathlib import Path
from xml.etree import ElementTree as ET

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

NS = {
    "bpmn":   "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc":     "http://www.omg.org/spec/DD/20100524/DC",
    "di":     "http://www.omg.org/spec/DD/20100524/DI",
}

WAYPOINT_TOLERANCE = 25  # px — допустимое отклонение waypoint от края элемента


def parse_bounds(shape_el):
    b = shape_el.find("dc:Bounds", NS)
    if b is None:
        return None
    return {
        "x": float(b.get("x", 0)),
        "y": float(b.get("y", 0)),
        "w": float(b.get("width", 0)),
        "h": float(b.get("height", 0)),
    }


def bounds_overlap(a, b, margin=5):
    return not (
        a["x"] + a["w"] <= b["x"] + margin or
        b["x"] + b["w"] <= a["x"] + margin or
        a["y"] + a["h"] <= b["y"] + margin or
        b["y"] + b["h"] <= a["y"] + margin
    )


def point_near_element(px, py, b):
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    t = WAYPOINT_TOLERANCE
    near_left   = abs(px - x)       <= t and y - t <= py <= y + h + t
    near_right  = abs(px - (x + w)) <= t and y - t <= py <= y + h + t
    near_top    = abs(py - y)       <= t and x - t <= px <= x + w + t
    near_bottom = abs(py - (y + h)) <= t and x - t <= px <= x + w + t
    return near_left or near_right or near_top or near_bottom


def validate(bpmn_path: Path, json_path: Path) -> dict:
    errors, warnings = [], []
    stats = {}

    # 1. XML синтаксис
    try:
        tree = ET.parse(bpmn_path)
        root = tree.getroot()
    except ET.ParseError as e:
        return {"valid": False, "errors": [f"XML ошибка: {e}"], "warnings": [], "stats": {}}

    # 2. Загружаем JSON
    process_json = {}
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            process_json = json.load(f)
    else:
        warnings.append(f"JSON не найден: {json_path} — пропускаю сверку")

    # 3. Элементы и потоки из BPMN
    process_el = root.find("bpmn:process", NS)
    if process_el is None:
        errors.append("Не найден элемент <process>")
        process_el = ET.Element("stub")

    bpmn_elements = {}
    for tag in ("startEvent", "endEvent", "task", "exclusiveGateway", "parallelGateway"):
        for el in process_el.findall(f"bpmn:{tag}", NS):
            bpmn_elements[el.get("id")] = {"tag": tag, "el": el}

    bpmn_flows = {}
    for flow in process_el.findall("bpmn:sequenceFlow", NS):
        bpmn_flows[flow.get("id")] = {
            "source": flow.get("sourceRef"),
            "target": flow.get("targetRef"),
            "name":   flow.get("name", ""),
        }

    stats["elements_in_bpmn"] = len(bpmn_elements)
    stats["flows_in_bpmn"]    = len(bpmn_flows)

    # 4. startEvent / endEvent
    starts = [eid for eid, e in bpmn_elements.items() if e["tag"] == "startEvent"]
    ends   = [eid for eid, e in bpmn_elements.items() if e["tag"] == "endEvent"]
    if len(starts) == 0:
        errors.append("Нет startEvent")
    elif len(starts) > 1:
        errors.append(f"Несколько startEvent ({len(starts)}): {starts}")
    if len(ends) == 0:
        errors.append("Нет endEvent")
    stats["start_events"] = len(starts)
    stats["end_events"]   = len(ends)

    # 5. Сверка JSON ↔ BPMN
    if process_json:
        json_elements = process_json.get("elements") or []
        json_flows    = process_json.get("flows") or []
        stats["elements_in_json"] = len(json_elements)
        stats["flows_in_json"]    = len(json_flows)

        for je in json_elements:
            if je["id"] not in bpmn_elements:
                errors.append(f"Элемент из JSON отсутствует в BPMN: '{je['id']}' ({je.get('name','')})")

        for jf in json_flows:
            if jf["id"] not in bpmn_flows:
                errors.append(f"Поток из JSON отсутствует в BPMN: '{jf['id']}'")
            else:
                bf  = bpmn_flows[jf["id"]]
                src = jf.get("from") or jf.get("source_id")
                tgt = jf.get("to")   or jf.get("target_id")
                if bf["source"] != src:
                    errors.append(f"Поток '{jf['id']}': source в BPMN='{bf['source']}' ≠ JSON='{src}'")
                if bf["target"] != tgt:
                    errors.append(f"Поток '{jf['id']}': target в BPMN='{bf['target']}' ≠ JSON='{tgt}'")

    # 6. Lanes — flowNodeRef
    lane_set = process_el.find("bpmn:laneSet", NS)
    if lane_set is None:
        warnings.append("Нет laneSet — диаграмма без дорожек участников")
    else:
        all_refs = []
        for lane in lane_set.findall("bpmn:lane", NS):
            lane_id = lane.get("id")
            for ref in lane.findall("bpmn:flowNodeRef", NS):
                ref_id = (ref.text or "").strip()
                all_refs.append(ref_id)
                if ref_id not in bpmn_elements:
                    errors.append(f"Lane '{lane_id}': flowNodeRef '{ref_id}' не существует")
        for eid in bpmn_elements:
            if eid not in all_refs:
                warnings.append(f"Элемент '{eid}' не привязан ни к одной lane")

    # 7. sourceRef / targetRef потоков
    for fid, flow in bpmn_flows.items():
        if flow["source"] not in bpmn_elements:
            errors.append(f"Поток '{fid}': sourceRef='{flow['source']}' не существует")
        if flow["target"] not in bpmn_elements:
            errors.append(f"Поток '{fid}': targetRef='{flow['target']}' не существует")

    # 8. Связность
    incoming = {eid: [] for eid in bpmn_elements}
    outgoing = {eid: [] for eid in bpmn_elements}
    for fid, flow in bpmn_flows.items():
        if flow["source"] in outgoing: outgoing[flow["source"]].append(fid)
        if flow["target"] in incoming: incoming[flow["target"]].append(fid)

    for eid, info in bpmn_elements.items():
        tag = info["tag"]
        if tag == "startEvent":
            if not outgoing[eid]:
                errors.append(f"startEvent '{eid}': нет исходящих потоков")
        elif tag == "endEvent":
            if not incoming[eid]:
                errors.append(f"endEvent '{eid}': нет входящих потоков")
        else:
            if not incoming[eid]:
                errors.append(f"'{eid}' ({tag}): нет входящих потоков — висячий блок")
            if not outgoing[eid]:
                errors.append(f"'{eid}' ({tag}): нет исходящих потоков — висячий блок")

        if tag == "exclusiveGateway":
            if len(outgoing[eid]) < 2:
                errors.append(f"Шлюз '{eid}': только {len(outgoing[eid])} исходящих потока, нужно ≥ 2")
            for fid in outgoing[eid]:
                if not bpmn_flows[fid].get("name"):
                    warnings.append(f"Поток '{fid}' из шлюза '{eid}': нет условия (Да/Нет)")

    # 9. Координаты
    diagram = root.find("bpmndi:BPMNDiagram", NS)
    if diagram is None:
        warnings.append("Нет BPMNDiagram — проверка координат невозможна")
    else:
        plane = diagram.find("bpmndi:BPMNPlane", NS)
        shape_bounds = {}
        pool_bounds  = None

        for shape in plane.findall("bpmndi:BPMNShape", NS):
            el_id = shape.get("bpmnElement")
            b = parse_bounds(shape)
            if b:
                shape_bounds[el_id] = b
                if b["w"] > 500 and (pool_bounds is None or b["w"] > pool_bounds["w"]):
                    pool_bounds = b

        # Элементы без координат
        for eid in bpmn_elements:
            if eid not in shape_bounds:
                errors.append(f"'{eid}': нет координат в BPMNDiagram")

        # Элементы вне пула
        if pool_bounds:
            px, py, pw, ph = pool_bounds["x"], pool_bounds["y"], pool_bounds["w"], pool_bounds["h"]
            for eid, b in shape_bounds.items():
                if eid not in bpmn_elements:
                    continue
                if not (px <= b["x"] and b["x"] + b["w"] <= px + pw and
                        py <= b["y"] and b["y"] + b["h"] <= py + ph):
                    errors.append(
                        f"'{eid}' выходит за границы пула: "
                        f"элемент=({b['x']:.0f},{b['y']:.0f}), пул=({px:.0f},{py:.0f},{pw:.0f}x{ph:.0f})"
                    )

        # Элементы вне своей lane
        if lane_set is not None:
            for lane in lane_set.findall("bpmn:lane", NS):
                lane_id = lane.get("id")
                lb = shape_bounds.get(lane_id)
                if not lb:
                    continue
                for ref in lane.findall("bpmn:flowNodeRef", NS):
                    ref_id = (ref.text or "").strip()
                    eb = shape_bounds.get(ref_id)
                    if not eb:
                        continue
                    cy = eb["y"] + eb["h"] / 2
                    if not (lb["y"] - 5 <= cy <= lb["y"] + lb["h"] + 5):
                        errors.append(
                            f"'{ref_id}' в lane '{lane_id}', но центр Y={cy:.0f} "
                            f"вне диапазона [{lb['y']:.0f}..{lb['y']+lb['h']:.0f}]"
                        )

        # Перекрытия между элементами
        elem_ids = [eid for eid in shape_bounds if eid in bpmn_elements]
        overlaps = 0
        for i in range(len(elem_ids)):
            for j in range(i + 1, len(elem_ids)):
                a, b = elem_ids[i], elem_ids[j]
                if bounds_overlap(shape_bounds[a], shape_bounds[b]):
                    overlaps += 1
                    errors.append(f"Перекрытие блоков: '{a}' и '{b}'")
        stats["overlapping_pairs"] = overlaps

        # Waypoints
        disconnected = 0
        for edge in plane.findall("bpmndi:BPMNEdge", NS):
            fid = edge.get("bpmnElement")
            wps = edge.findall("di:waypoint", NS)
            if len(wps) < 2:
                errors.append(f"Поток '{fid}': менее 2 waypoints — стрелка без начала или конца")
                continue
            if fid not in bpmn_flows:
                continue
            flow = bpmn_flows[fid]
            sb = shape_bounds.get(flow["source"])
            tb = shape_bounds.get(flow["target"])
            if sb:
                fx, fy = float(wps[0].get("x", 0)), float(wps[0].get("y", 0))
                if not point_near_element(fx, fy, sb):
                    disconnected += 1
                    warnings.append(
                        f"Поток '{fid}': первый waypoint ({fx:.0f},{fy:.0f}) "
                        f"далеко от источника '{flow['source']}'"
                    )
            if tb:
                lx, ly = float(wps[-1].get("x", 0)), float(wps[-1].get("y", 0))
                if not point_near_element(lx, ly, tb):
                    disconnected += 1
                    warnings.append(
                        f"Поток '{fid}': последний waypoint ({lx:.0f},{ly:.0f}) "
                        f"далеко от цели '{flow['target']}'"
                    )
        stats["disconnected_waypoints"] = disconnected

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings, "stats": stats}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bpmn", default=str(OUTPUT_DIR / "process.bpmn"))
    parser.add_argument("--json", default=str(OUTPUT_DIR / "process.json"))
    args = parser.parse_args()

    result = validate(Path(args.bpmn), Path(args.json))

    # stdout — машиночитаемый JSON для OpenCode
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # stderr — человекочитаемое резюме
    status = "✅ ВАЛИДНО" if result["valid"] else "❌ ЕСТЬ ОШИБКИ"
    print(f"\n{status} | ошибок: {len(result['errors'])} | предупреждений: {len(result['warnings'])}", file=sys.stderr)
    for e in result["errors"]:
        print(f"  ✗ {e}", file=sys.stderr)
    for w in result["warnings"]:
        print(f"  ⚠ {w}", file=sys.stderr)

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
