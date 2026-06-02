"""
update_bpmn.py
Принимает текстовое описание изменения, обновляет process.json через Claude API,
затем перегенерирует BPMN.
Использование: python scripts/update_bpmn.py "добавь шаг согласования после задачи X"
"""

import json
import re
import sys
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

# Эталонный пример изменения JSON (few-shot).
# Показывает модели: какая структура считается правильной,
# и как корректно вносить изменения не ломая схему.
FEW_SHOT_EXAMPLE = """
ПРИМЕР ПРАВИЛЬНОГО ИЗМЕНЕНИЯ JSON:

Запрос: "добавь шаг 'Проверить договор' после задачи 'Отправить на согласование'"

Было в elements:
  {"id": "task_4", "type": "task", "name": "Отправить на согласование", "lane": "lane_economist"},
  {"id": "gw_2",   "type": "exclusiveGateway", "name": "Финдиректор согласовал?", "lane": "lane_finance_director"}

Было в flows:
  {"id": "flow_7", "from": "task_4", "to": "gw_2", "condition": ""}

Стало в elements (добавили новый task):
  {"id": "task_4",    "type": "task", "name": "Отправить на согласование", "lane": "lane_economist"},
  {"id": "task_new1", "type": "task", "name": "Проверить договор",         "lane": "lane_economist"},
  {"id": "gw_2",      "type": "exclusiveGateway", "name": "Финдиректор согласовал?", "lane": "lane_finance_director"}

Стало в flows (старый поток заменили двумя новыми):
  {"id": "flow_7",    "from": "task_4",    "to": "task_new1", "condition": ""},
  {"id": "flow_new1", "from": "task_new1", "to": "gw_2",      "condition": ""}

Правила которые соблюдены:
- Старые id не изменились
- Новый элемент получил уникальный id (task_new1)
- Старый поток flow_7 переподключён к новому элементу
- Добавлен новый поток от нового элемента к следующему
- Схема JSON не изменилась
"""


def update_process(change_request: str) -> None:
    """Обновляет process.json согласно запросу пользователя через Claude API."""
    try:
        import anthropic
    except ImportError:
        print("Ошибка: установите anthropic: pip install anthropic")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Ошибка: не найден ANTHROPIC_API_KEY в .env файле")
        sys.exit(1)

    json_path = OUTPUT_DIR / "process.json"
    if not json_path.exists():
        print(f"Ошибка: файл не найден: {json_path}")
        print("Сначала запустите парсинг: python scripts/parse_process.py <файл.txt>")
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        current_json = json.load(f)

    print(f"Запрос на изменение: {change_request}")
    print("Отправляю запрос в Claude API...")

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""У тебя есть JSON описание бизнес-процесса. Внеси изменение согласно запросу.
Верни ТОЛЬКО обновлённый валидный JSON без пояснений, без markdown, без ```json.

{FEW_SHOT_EXAMPLE}

ПРАВИЛА:
- Сохраняй все существующие id, не меняй их без необходимости
- Новые элементы: уникальные id (латиница, без пробелов, например task_new1)
- type только: startEvent, task, exclusiveGateway, endEvent
- Обновляй потоки (flows) если добавляешь/удаляешь элементы
- Не меняй структуру схемы JSON

ТЕКУЩИЙ JSON:
{json.dumps(current_json, ensure_ascii=False, indent=2)}

ЗАПРОС НА ИЗМЕНЕНИЕ:
{change_request}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()
    response_text = re.sub(r'^```json\s*', '', response_text)
    response_text = re.sub(r'\s*```$', '', response_text)

    updated_json = json.loads(response_text)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(updated_json, f, ensure_ascii=False, indent=2)

    print(f"JSON обновлён: {json_path}")

    print("Перегенерирую BPMN диаграмму...")
    generate_script = PROJECT_ROOT / "scripts" / "generate_bpmn.py"
    subprocess.run([sys.executable, str(generate_script)], check=True)


def main():
    if len(sys.argv) < 2:
        print("Использование: python update_bpmn.py \"описание изменения\"")
        sys.exit(1)

    change_request = " ".join(sys.argv[1:])
    update_process(change_request)


if __name__ == "__main__":
    main()
