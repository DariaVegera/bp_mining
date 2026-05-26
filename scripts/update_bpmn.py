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

    prompt = f"""У тебя есть JSON описание бизнес-процесса. Внеси в него изменение согласно запросу пользователя.
Верни ТОЛЬКО обновлённый валидный JSON без пояснений, без markdown, без ```json.

Правила:
- Сохраняй все существующие id, не меняй их без необходимости
- Новые элементы должны иметь уникальные id (латиница, без пробелов)
- type может быть только: startEvent, task, exclusiveGateway, endEvent
- Обновляй потоки (flows) если добавляешь/удаляешь элементы
- Сохраняй структуру JSON без изменений схемы

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
    # Убираем markdown-обёртки если есть
    response_text = re.sub(r'^```json\s*', '', response_text)
    response_text = re.sub(r'\s*```$', '', response_text)

    updated_json = json.loads(response_text)

    # Сохраняем обновлённый JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(updated_json, f, ensure_ascii=False, indent=2)

    print(f"JSON обновлён: {json_path}")

    # Перегенерируем BPMN
    print("Перегенерирую BPMN диаграмму...")
    generate_script = PROJECT_ROOT / "scripts" / "generate_bpmn.py"
    subprocess.run([sys.executable, str(generate_script)], check=True)


def main():
    if len(sys.argv) < 2:
        print("Использование: python update_bpmn.py \"описание изменения\"")
        print("Пример: python update_bpmn.py \"добавь шаг проверки качества после задачи X\"")
        sys.exit(1)

    change_request = " ".join(sys.argv[1:])
    update_process(change_request)


if __name__ == "__main__":
    main()
