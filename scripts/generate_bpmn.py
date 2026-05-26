"""
generate_bpmn.py
Читает output/process.json и генерирует валидный BPMN 2.0 XML файл.
Автоматически рассчитывает координаты элементов по сетке.
"""

import json
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

# Корень проекта
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Размеры элементов (px)
TASK_W, TASK_H = 160, 60
GATEWAY_W, GATEWAY_H = 50, 50
EVENT_W, EVENT_H = 36, 36

# Отступы сетки
LANE_HEADER_W = 160       # ширина заголовка lane слева
POOL_HEADER_W = 30        # ширина заголовка пула
START_X = 230             # X первого элемента
STEP_X = 200              # горизонтальный шаг между элементами
LANE_H = 140              # высота одного lane
POOL_START_Y = 80         # Y начала пула
LANE_START_Y = POOL_START_Y  # Y первого lane


def get_element_size(elem_type: str) -> tuple:
    """Возвращает (width, height) для типа элемента."""
    if elem_type in ("startEvent", "endEvent"):
        return EVENT_W, EVENT_H
    elif elem_type == "exclusiveGateway":
        return GATEWAY_W, GATEWAY_H
    else:
        return TASK_W, TASK_H


def calculate_layout(process: dict) -> dict:
    """
    Рассчитывает координаты всех элементов.
    Логика: элементы каждого lane выкладываются горизонтально.
    Порядок определяется порядком потоков (топологическая сортировка).
    """
    lanes = process["lanes"]
    elements = process["elements"]
    flows = process["flows"]

    # Индекс элементов по id
    elem_by_id = {e["id"]: e for e in elements}

    # Строим граф потоков для топологической сортировки
    in_degree = {e["id"]: 0 for e in elements}
    adjacency = {e["id"]: [] for e in elements}
    for flow in flows:
        if flow["source_id"] in adjacency and flow["target_id"] in in_degree:
            adjacency[flow["source_id"]].append(flow["target_id"])
            in_degree[flow["target_id"]] += 1

    # Топологическая сортировка (Kahn's algorithm)
    queue = [eid for eid, deg in in_degree.items() if deg == 0]
    topo_order = []
    while queue:
        node = queue.pop(0)
        topo_order.append(node)
        for neighbor in adjacency.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Добавляем элементы, не попавшие в сортировку (несвязанные)
    for e in elements:
        if e["id"] not in topo_order:
            topo_order.append(e["id"])

    # Назначаем порядковый номер (колонку) каждому элементу
    elem_column = {eid: i for i, eid in enumerate(topo_order)}

    # Назначаем Y каждому lane
    lane_index = {lane["id"]: i for i, lane in enumerate(lanes)}
    lane_y = {lane["id"]: LANE_START_Y + i * LANE_H for i, lane in enumerate(lanes)}

    # Рассчитываем X для каждого элемента
    # Группируем по lane, чтобы не перекрывались
    lane_col_counter = {lane["id"]: {} for lane in lanes}

    for elem in elements:
        lid = elem.get("lane_id", "")
        col = elem_column.get(elem["id"], 0)
        w, h = get_element_size(elem["type"])

        # X: стартовая позиция + колонка * шаг
        x = START_X + col * STEP_X
        # Центрируем по вертикали в lane
        ly = lane_y.get(lid, LANE_START_Y)
        y = ly + (LANE_H - h) // 2

        elem["x"] = x
        elem["y"] = y
        elem["width"] = w
        elem["height"] = h

    # Ширина пула = максимальная X + ширина элемента + отступ
    max_x = max((e["x"] + e["width"] for e in elements), default=400)
    pool_width = max_x - POOL_HEADER_W + 80
    pool_height = len(lanes) * LANE_H

    # Обновляем Y для lanes
    for lane in lanes:
        lane["y"] = lane_y.get(lane["id"], LANE_START_Y)

    # Рассчитываем точки соединения потоков (центры элементов)
    for flow in flows:
        src = elem_by_id.get(flow["source_id"])
        tgt = elem_by_id.get(flow["target_id"])
        if src and tgt:
            flow["source_x"] = src["x"] + src["width"]
            flow["source_y"] = src["y"] + src["height"] // 2
            flow["target_x"] = tgt["x"]
            flow["target_y"] = tgt["y"] + tgt["height"] // 2
        else:
            # Заглушка для несвязанных потоков
            flow["source_x"] = 0
            flow["source_y"] = 0
            flow["target_x"] = 100
            flow["target_y"] = 100

    return {
        "pool_width": pool_width,
        "pool_height": pool_height,
        "lane_height": LANE_H
    }


def generate_bpmn(json_path: Path = None) -> Path:
    """Основная функция генерации BPMN."""
    if json_path is None:
        json_path = OUTPUT_DIR / "process.json"

    if not json_path.exists():
        print(f"Ошибка: файл не найден: {json_path}")
        print("Сначала запустите: python scripts/parse_process.py <файл.txt>")
        sys.exit(1)

    print(f"Читаю JSON: {json_path}")
    with open(json_path, encoding="utf-8") as f:
        process = json.load(f)

    # Рассчитываем координаты
    print("Рассчитываю координаты элементов...")
    layout = calculate_layout(process)

    # Рендерим шаблон
    print("Генерирую BPMN XML...")
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        trim_blocks=True,
        lstrip_blocks=True
    )
    template = env.get_template("process.bpmn.j2")

    bpmn_xml = template.render(
        process=process,
        pool_width=layout["pool_width"],
        pool_height=layout["pool_height"],
        lane_height=layout["lane_height"]
    )

    # Сохраняем
    output_path = OUTPUT_DIR / "process.bpmn"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(bpmn_xml)

    print(f"\nГотово! BPMN сохранён: {output_path}")
    print(f"\nОткройте диаграмму:")
    print(f"  1. Перейдите на https://bpmn.io/")
    print(f"  2. Нажмите 'Open diagram'")
    print(f"  3. Загрузите файл: {output_path.resolve()}")

    return output_path


if __name__ == "__main__":
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    generate_bpmn(json_path)
