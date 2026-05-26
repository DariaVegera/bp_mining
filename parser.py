import os
import json
import anthropic
from pathlib import Path


def load_system_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompts" / "parse_process.txt"
    return prompt_path.read_text(encoding="utf-8")


def parse_process(text: str) -> dict:
    """
    Sends process text to Claude API.
    Returns parsed JSON with participants, elements, flows.
    """
    print("  → Отправляю текст в Claude API...")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = load_system_prompt()

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Разбери следующее описание бизнес-процесса:\n\n{text}"
            }
        ]
    )

    raw = message.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if lines[-1] == "```" else "\n".join(lines[1:])

    print("  → Получен ответ, парсю JSON...")
    parsed = json.loads(raw)

    # Validate required keys
    required = {"process_name", "participants", "elements", "flows"}
    missing = required - set(parsed.keys())
    if missing:
        raise ValueError(f"В ответе Claude отсутствуют поля: {missing}")

    print(f"  → Найдено участников: {len(parsed['participants'])}")
    print(f"  → Найдено элементов: {len(parsed['elements'])}")
    print(f"  → Найдено потоков: {len(parsed['flows'])}")

    return parsed
