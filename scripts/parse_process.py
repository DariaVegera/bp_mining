"""
parse_process.py
Парсит структурированный текстовый файл бизнес-процесса в JSON.
Для структурированного текста — парсинг через regex без API.
Для неструктурированного — через Claude API.
"""

import re
import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Корень проекта
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Маппинг участников → id lane (из текста)
def slugify(name: str) -> str:
    """Извлекает lane_id из строки вида 'Имя (lane_id)' или генерирует из имени."""
    match = re.search(r'\(([^)]+)\)', name)
    if match:
        return match.group(1).strip()
    # Генерируем id из имени
    return "lane_" + re.sub(r'[^a-zA-Zа-яА-Я0-9]', '_', name.strip().lower())[:20]


def extract_lane_name(name: str) -> str:
    """Убирает (lane_id) из имени участника."""
    return re.sub(r'\s*\([^)]+\)', '', name).strip()


def is_structured(text: str) -> bool:
    """Проверяет, является ли текст структурированным."""
    return "УЧАСТНИКИ:" in text and "ЭЛЕМЕНТЫ ПРОЦЕССА:" in text and "ПОТОКИ:" in text


def parse_structured(text: str) -> dict:
    """Парсит структурированный текст через regex."""
    result = {
        "process_name": "",
        "lanes": [],
        "elements": [],
        "flows": []
    }

    # Название процесса
    name_match = re.search(r'БИЗНЕС-ПРОЦЕСС:\s*(.+)', text)
    if name_match:
        result["process_name"] = name_match.group(1).strip()

    # Участники
    participants_block = re.search(r'УЧАСТНИКИ:(.*?)(?=СТАТИСТИКА:|ЭЛЕМЕНТЫ ПРОЦЕССА:)', text, re.DOTALL)
    if participants_block:
        for line in participants_block.group(1).splitlines():
            line = line.strip().lstrip('- ').strip()
            if line:
                lane_id = slugify(line)
                lane_name = extract_lane_name(line)
                result["lanes"].append({"id": lane_id, "name": lane_name})

    # Элементы процесса
    elements_block = re.search(r'ЭЛЕМЕНТЫ ПРОЦЕССА:(.*?)(?=ПОТОКИ:|$)', text, re.DOTALL)
    lane_name_to_id = {l["name"]: l["id"] for l in result["lanes"]}
    # Также маппинг по исходному тексту (с lane_id в скобках)
    lane_text_to_id = {}
    if participants_block:
        for line in participants_block.group(1).splitlines():
            line = line.strip().lstrip('- ').strip()
            if line:
                lane_id = slugify(line)
                lane_name = extract_lane_name(line)
                lane_text_to_id[line] = lane_id
                lane_text_to_id[lane_name] = lane_id

    element_counter = {}

    if elements_block:
        for line in elements_block.group(1).splitlines():
            line = line.strip()
            # Формат: [type] Название → Участник
            match = re.match(r'\[(\w+)\]\s*(.+?)\s*→\s*(.+)', line)
            if match:
                elem_type = match.group(1).strip()
                elem_name = match.group(2).strip()
                participant = match.group(3).strip()

                # Определяем lane_id
                lane_id = lane_text_to_id.get(participant, "")
                if not lane_id:
                    # Попробуем найти по части имени
                    for key, val in lane_text_to_id.items():
                        if participant.lower() in key.lower() or key.lower() in participant.lower():
                            lane_id = val
                            break

                # Генерируем уникальный id элемента
                base_id = elem_type + "_" + re.sub(r'[^a-zA-Zа-яА-Я0-9]', '_', elem_name)[:20]
                element_counter[base_id] = element_counter.get(base_id, 0) + 1
                elem_id = base_id if element_counter[base_id] == 1 else f"{base_id}_{element_counter[base_id]}"

                result["elements"].append({
                    "id": elem_id,
                    "type": elem_type,
                    "name": elem_name,
                    "lane_id": lane_id
                })

    # Потоки
    flows_block = re.search(r'ПОТОКИ:(.*?)$', text, re.DOTALL)
    # Маппинг имя элемента → id
    name_to_id = {e["name"]: e["id"] for e in result["elements"]}

    flow_counter = 0
    if flows_block:
        for line in flows_block.group(1).splitlines():
            line = line.strip()
            if '-->' not in line:
                continue
            # Формат: Источник --> Цель (условие)
            match = re.match(r'(.+?)\s*-->\s*(.+?)(?:\s*\((.+)\))?\s*$', line)
            if match:
                source_name = match.group(1).strip()
                target_name = match.group(2).strip()
                condition = match.group(3).strip() if match.group(3) else None

                source_id = name_to_id.get(source_name, "")
                target_id = name_to_id.get(target_name, "")

                if not source_id or not target_id:
                    # Ищем по частичному совпадению
                    for name, eid in name_to_id.items():
                        if source_name.lower() in name.lower() and not source_id:
                            source_id = eid
                        if target_name.lower() in name.lower() and not target_id:
                            target_id = eid

                flow_counter += 1
                result["flows"].append({
                    "id": f"flow_{flow_counter}",
                    "source_id": source_id,
                    "target_id": target_id,
                    "condition": condition
                })

    return result


def parse_with_api(text: str) -> dict:
    """Парсит неструктурированный текст через Claude API."""
    try:
        import anthropic
    except ImportError:
        print("Ошибка: установите anthropic: pip install anthropic")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Ошибка: не найден ANTHROPIC_API_KEY в .env файле")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""Ты эксперт по бизнес-процессам. Прочитай текст ниже и извлеки из него структуру бизнес-процесса.
Верни ТОЛЬКО валидный JSON без пояснений, без markdown, без ```json.

JSON должен строго соответствовать схеме:
{{
  "process_name": "название процесса",
  "lanes": [
    {{"id": "lane_уникальный_id", "name": "Имя участника/отдела"}}
  ],
  "elements": [
    {{
      "id": "уникальный_id_элемента",
      "type": "startEvent|task|exclusiveGateway|endEvent",
      "name": "название элемента",
      "lane_id": "id lane участника"
    }}
  ],
  "flows": [
    {{
      "id": "flow_1",
      "source_id": "id_источника",
      "target_id": "id_цели",
      "condition": "условие или null"
    }}
  ]
}}

Правила:
- type может быть только: startEvent, task, exclusiveGateway, endEvent
- Каждый элемент должен принадлежать lane (lane_id)
- id должны быть уникальными латинскими строками без пробелов
- В процессе должен быть ровно 1 startEvent и минимум 1 endEvent
- exclusiveGateway используется для ветвлений (если/или)

ТЕКСТ ПРОЦЕССА:
{text}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()
    # Убираем возможные markdown-обёртки
    response_text = re.sub(r'^```json\s*', '', response_text)
    response_text = re.sub(r'\s*```$', '', response_text)

    return json.loads(response_text)


def main():
    if len(sys.argv) < 2:
        print("Использование: python parse_process.py <путь_к_файлу.txt>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Ошибка: файл не найден: {input_path}")
        sys.exit(1)

    print(f"Читаю файл: {input_path}")
    text = input_path.read_text(encoding="utf-8")

    if is_structured(text):
        print("Обнаружен структурированный формат — парсинг через regex...")
        result = parse_structured(text)
    else:
        print("Неструктурированный текст — парсинг через Claude API...")
        result = parse_with_api(text)

    output_path = OUTPUT_DIR / "process.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nГотово! JSON сохранён: {output_path}")
    print(f"  Участников: {len(result['lanes'])}")
    print(f"  Элементов:  {len(result['elements'])}")
    print(f"  Потоков:    {len(result['flows'])}")
    print(f"\nСледующий шаг: python scripts/generate_bpmn.py")


if __name__ == "__main__":
    main()
