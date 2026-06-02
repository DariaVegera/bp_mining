"""
parse_process.py
Парсит структурированный текстовый файл бизнес-процесса в JSON.
Структурированный текст — парсинг через regex без API.
ID элементов — только латиница (транслитерация).
"""

import re
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Таблица транслитерации кириллицы → латиница
TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
    'и':'i','й':'j','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch',
    'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'Yo','Ж':'Zh','З':'Z',
    'И':'I','Й':'J','К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R',
    'С':'S','Т':'T','У':'U','Ф':'F','Х':'H','Ц':'Ts','Ч':'Ch','Ш':'Sh','Щ':'Sch',
    'Ъ':'','Ы':'Y','Ь':'','Э':'E','Ю':'Yu','Я':'Ya',
}

def translit(text: str) -> str:
    """Транслитерирует кириллицу в латиницу."""
    return ''.join(TRANSLIT.get(c, c) for c in text)

def to_latin_id(text: str, max_len: int = 24) -> str:
    """Превращает произвольный текст в валидный латинский id."""
    t = translit(text)
    t = re.sub(r'[^a-zA-Z0-9]+', '_', t)
    t = t.strip('_')
    return t[:max_len].lower()

def slugify(name: str) -> str:
    """Извлекает lane_id из строки вида 'Имя (lane_id)' или генерирует из имени."""
    match = re.search(r'\(([^)]+)\)', name)
    if match:
        return match.group(1).strip()
    return "lane_" + to_latin_id(name)

def extract_lane_name(name: str) -> str:
    """Убирает (lane_id) из имени участника."""
    return re.sub(r'\s*\([^)]+\)', '', name).strip()

def is_structured(text: str) -> bool:
    return "УЧАСТНИКИ:" in text and "ЭЛЕМЕНТЫ ПРОЦЕССА:" in text and "ПОТОКИ:" in text

def parse_structured(text: str) -> dict:
    result = {"process_name": "", "lanes": [], "elements": [], "flows": []}

    name_match = re.search(r'БИЗНЕС-ПРОЦЕСС:\s*(.+)', text)
    if name_match:
        result["process_name"] = name_match.group(1).strip()

    participants_block = re.search(r'УЧАСТНИКИ:(.*?)(?=СТАТИСТИКА:|ЭЛЕМЕНТЫ ПРОЦЕССА:)', text, re.DOTALL)
    lane_text_to_id = {}
    if participants_block:
        for line in participants_block.group(1).splitlines():
            line = line.strip().lstrip('- ').strip()
            if line:
                lane_id = slugify(line)
                lane_name = extract_lane_name(line)
                result["lanes"].append({"id": lane_id, "name": lane_name})
                lane_text_to_id[line] = lane_id
                lane_text_to_id[lane_name] = lane_id

    elements_block = re.search(r'ЭЛЕМЕНТЫ ПРОЦЕССА:(.*?)(?=ПОТОКИ:|$)', text, re.DOTALL)
    element_counter = {}

    # Префиксы типов для ID
    TYPE_PREFIX = {
        "startEvent": "start",
        "endEvent": "end",
        "task": "task",
        "exclusiveGateway": "gw",
    }

    if elements_block:
        for line in elements_block.group(1).splitlines():
            line = line.strip()
            match = re.match(r'\[(\w+)\]\s*(.+?)\s*→\s*(.+)', line)
            if match:
                elem_type = match.group(1).strip()
                elem_name = match.group(2).strip()
                participant = match.group(3).strip()

                lane_id = lane_text_to_id.get(participant, "")
                if not lane_id:
                    for key, val in lane_text_to_id.items():
                        if participant.lower() in key.lower() or key.lower() in participant.lower():
                            lane_id = val
                            break

                # Генерируем id только из латиницы
                prefix = TYPE_PREFIX.get(elem_type, elem_type)
                name_part = to_latin_id(elem_name, max_len=20)
                base_id = f"{prefix}_{name_part}"
                element_counter[base_id] = element_counter.get(base_id, 0) + 1
                count = element_counter[base_id]
                elem_id = base_id if count == 1 else f"{base_id}_{count}"

                result["elements"].append({
                    "id": elem_id,
                    "type": elem_type,
                    "name": elem_name,
                    "lane_id": lane_id
                })

    flows_block = re.search(r'ПОТОКИ:(.*?)$', text, re.DOTALL)
    name_to_id = {e["name"]: e["id"] for e in result["elements"]}
    flow_counter = 0

    if flows_block:
        for line in flows_block.group(1).splitlines():
            line = line.strip()
            if '-->' not in line:
                continue
            match = re.match(r'(.+?)\s*-->\s*(.+?)(?:\s*\((.+)\))?\s*$', line)
            if match:
                source_name = match.group(1).strip()
                target_name = match.group(2).strip()
                condition = match.group(3).strip() if match.group(3) else None

                source_id = name_to_id.get(source_name, "")
                target_id = name_to_id.get(target_name, "")

                if not source_id or not target_id:
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

    if not is_structured(text):
        print("Ошибка: текст не структурирован. Нужны секции УЧАСТНИКИ:, ЭЛЕМЕНТЫ ПРОЦЕССА:, ПОТОКИ:")
        print("Для неструктурированного текста — используй OpenCode напрямую.")
        sys.exit(1)

    print("Парсинг через regex...")
    result = parse_structured(text)

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
