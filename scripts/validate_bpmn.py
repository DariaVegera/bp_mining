"""
validate_bpmn.py
Валидирует сгенерированный BPMN через Claude API, используя эталонный файл как образец.
Запускается автоматически после generate_bpmn.py или вручную.
Использование: python scripts/validate_bpmn.py [--fix]
  --fix  автоматически попробовать перегенерировать при ошибках (до 3 раз)
"""

import json
import sys
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
EXAMPLES_DIR = PROJECT_ROOT / "examples"

MAX_RETRIES = 2

# Эталонный BPMN — берём ключевые структурные паттерны (не весь файл,
# чтобы не перегружать контекст). Показывает модели что считается правильным.
REFERENCE_BPMN_FRAGMENT = """
<!-- ЭТАЛОННЫЙ BPMN на основе проверенного процесса - обратить внимание на паттерны-->

<!-- 1. Правильный exclusiveGateway с несколькими исходящими потоками -->
<!-- 2. Правильная задача с входящим и исходящим потоком -->
<!-- 3. Правильное startEvent -->
<!-- 4. Правильное endEvent -->
<!-- 5. Правильная структура lane с flowNodeRef -->

process id="Process_1" isExecutable="false">
    <laneSet id="LaneSet_1">
      <lane id="lane_finance_director" name="Финансовый директор">
        <flowNodeRef>end_pricelist</flowNodeRef>
        <flowNodeRef>gw_fd_approved</flowNodeRef>
        <flowNodeRef>task_make_changes</flowNodeRef>
        <flowNodeRef>end_approved</flowNodeRef>
      </lane>
      <lane id="lane_economist" name="Экономист">
        <flowNodeRef>start_1</flowNodeRef>
        <flowNodeRef>task_view_docs</flowNodeRef>
        <flowNodeRef>gw_price_list</flowNodeRef>
        <flowNodeRef>task_take_price</flowNodeRef>
        <flowNodeRef>task_fill_calc</flowNodeRef>
        <flowNodeRef>task_send_fd</flowNodeRef>
        <flowNodeRef>task_attach_final</flowNodeRef>
        <flowNodeRef>task_transfer_task</flowNodeRef>
      </lane>
    </laneSet>
    <startEvent id="start_1" name="Появилась новая задача по заявке в Битрикс">
      <outgoing>flow_1</outgoing>
    </startEvent>
    <task id="task_view_docs" name="Просмотреть документы заявки">
      <incoming>flow_1</incoming>
      <outgoing>flow_2</outgoing>
    </task>
    <exclusiveGateway id="gw_price_list" name="Изделие из прайса?">
      <incoming>flow_2</incoming>
      <outgoing>flow_6_yes</outgoing>
      <outgoing>flow_6_no</outgoing>
    </exclusiveGateway>
    <endEvent id="end_pricelist">
      <incoming>flow_7</incoming>
    </endEvent>
    <task id="task_take_price" name="Взять цену из прайса и прикрепить в Битрикс">
      <incoming>flow_6_yes</incoming>
      <outgoing>flow_7</outgoing>
    </task>
    <exclusiveGateway id="gw_fd_approved" name="Финдиректор согласовал?">
      <incoming>flow_19</incoming>
      <outgoing>flow_20_yes</outgoing>
      <outgoing>flow_20_no</outgoing>
    </exclusiveGateway>
    <task id="task_fill_calc" name="Заполнить калькуляцию">
      <incoming>flow_6_no</incoming>
      <outgoing>Flow_1kmpkkx</outgoing>
    </task>
    <task id="task_send_fd" name="Отправить расчет финдиректору на согласование (по e-mail)">
      <incoming>Flow_1kmpkkx</incoming>
      <outgoing>flow_19</outgoing>
    </task>
    <task id="task_attach_final" name="Прикрепить финальный расчет в Битрикс и отметить согласование">
      <incoming>flow_20_yes</incoming>
      <incoming>flow_21</incoming>
      <outgoing>flow_22</outgoing>
    </task>
    <task id="task_make_changes" name="Внести изменения в калькуляцию и отправить исправленный файл">
      <incoming>flow_20_no</incoming>
      <outgoing>flow_21</outgoing>
    </task>
    <task id="task_transfer_task" name="Перевести задачу на финдиректора и завершить свою задачу">
      <incoming>flow_22</incoming>
      <outgoing>flow_23</outgoing>
    </task>
    <endEvent id="end_approved">
      <incoming>flow_23</incoming>
    </endEvent>
    <sequenceFlow id="flow_1" sourceRef="start_1" targetRef="task_view_docs" />
    <sequenceFlow id="flow_2" sourceRef="task_view_docs" targetRef="gw_price_list" />
    <sequenceFlow id="flow_6_yes" name="Да" sourceRef="gw_price_list" targetRef="task_take_price" />
    <sequenceFlow id="flow_6_no" name="Нет" sourceRef="gw_price_list" targetRef="task_fill_calc" />
    <sequenceFlow id="flow_7" sourceRef="task_take_price" targetRef="end_pricelist" />
    <sequenceFlow id="flow_19" name="" sourceRef="task_send_fd" targetRef="gw_fd_approved" />
    <sequenceFlow id="flow_20_yes" name="Да" sourceRef="gw_fd_approved" targetRef="task_attach_final" />
    <sequenceFlow id="flow_20_no" name="Нет (правки)" sourceRef="gw_fd_approved" targetRef="task_make_changes" />
    <sequenceFlow id="Flow_1kmpkkx" sourceRef="task_fill_calc" targetRef="task_send_fd" />
    <sequenceFlow id="flow_21" sourceRef="task_make_changes" targetRef="task_attach_final" />
    <sequenceFlow id="flow_22" sourceRef="task_attach_final" targetRef="task_transfer_task" />
    <sequenceFlow id="flow_23" sourceRef="task_transfer_task" targetRef="end_approved" />
  </process>
"""


def validate_bpmn(bpmn_path: Path = None, json_path: Path = None, auto_fix: bool = False) -> bool:
    """
    Валидирует BPMN файл через Claude API.
    Возвращает True если валидация прошла успешно.
    """
    try:
        import anthropic
    except ImportError:
        print("Ошибка: установите anthropic: pip install anthropic")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Ошибка: не найден ANTHROPIC_API_KEY в .env файле")
        sys.exit(1)

    if bpmn_path is None:
        bpmn_path = OUTPUT_DIR / "process.bpmn"
    if json_path is None:
        json_path = OUTPUT_DIR / "process.json"

    if not bpmn_path.exists():
        print(f"Ошибка: BPMN файл не найден: {bpmn_path}")
        sys.exit(1)

    bpmn_content = bpmn_path.read_text(encoding="utf-8")
    json_content = json_path.read_text(encoding="utf-8") if json_path.exists() else ""

    print(f"Валидирую: {bpmn_path.name}")
    print("Отправляю в Claude API для проверки...")

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""Ты — эксперт по BPMN 2.0. Проверь корректность BPMN XML файла.

{REFERENCE_BPMN_FRAGMENT}

КРИТЕРИИ ПРОВЕРКИ:
1. У каждого элемента есть <incoming> и <outgoing> потоки (кроме startEvent и endEvent)
2. startEvent имеет только <outgoing>, endEvent — только <incoming>
3. Каждый exclusiveGateway имеет минимум 2 <outgoing> потока
4. Все id в <flowNodeRef> внутри lanes соответствуют реальным элементам
5. Все sourceRef и targetRef в потоках указывают на существующие элементы
6. Есть ровно один startEvent
7. Есть минимум один endEvent
8. Нет "висячих" элементов — у каждого есть хотя бы один поток
9. XML синтаксически корректен (все теги закрыты)

Верни ТОЛЬКО JSON без пояснений:
{{
  "valid": true или false,
  "errors": ["описание ошибки 1", "описание ошибки 2"],
  "warnings": ["предупреждение 1"],
  "summary": "краткое резюме одной строкой"
}}

BPMN ДЛЯ ПРОВЕРКИ:
{bpmn_content}

ИСХОДНЫЙ JSON ПРОЦЕССА (для сверки):
{json_content[:2000] if json_content else "недоступен"}
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()
    # Убираем markdown если есть
    import re
    response_text = re.sub(r'^```json\s*', '', response_text)
    response_text = re.sub(r'\s*```$', '', response_text)

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        print(f"Ошибка парсинга ответа валидатора: {response_text}")
        return False

    # Выводим результат
    print(f"\n{'='*50}")
    print(f"РЕЗУЛЬТАТ ВАЛИДАЦИИ: {'УСПЕШНО' if result.get('valid') else 'ОШИБКИ'}")
    print(f"{'='*50}")
    print(f"Резюме: {result.get('summary', '')}")

    if result.get("errors"):
        print("\nОшибки:")
        for err in result["errors"]:
            print(f"  ✗ {err}")

    if result.get("warnings"):
        print("\nПредупреждения:")
        for warn in result["warnings"]:
            print(f"  ⚠ {warn}")

    print()

    # Автоматическое исправление
    if not result.get("valid") and auto_fix and result.get("errors"):
        return attempt_fix(result["errors"], json_path)

    return result.get("valid", False)


def attempt_fix(errors: list, json_path: Path, attempt: int = 1) -> bool:
    """Пытается исправить ошибки перегенерацией через update_bpmn."""
    if attempt > MAX_RETRIES:
        print(f"Достигнут лимит попыток исправления ({MAX_RETRIES}). Требуется ручная правка.")
        return False

    print(f"Попытка автоматического исправления ({attempt}/{MAX_RETRIES})...")

    errors_text = "\n".join(f"- {e}" for e in errors)
    fix_request = f"Исправь следующие ошибки в процессе:\n{errors_text}"

    update_script = PROJECT_ROOT / "scripts" / "update_bpmn.py"
    result = subprocess.run(
        [sys.executable, str(update_script), fix_request],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"Ошибка при исправлении: {result.stderr}")
        return False

    print("Перегенерировано. Повторная валидация...")
    return validate_bpmn(auto_fix=True)


def main():
    auto_fix = "--fix" in sys.argv
    if auto_fix:
        print("Режим: автоматическое исправление включено")

    success = validate_bpmn(auto_fix=auto_fix)

    if success:
        print("Диаграмма готова к использованию.")
        print("Откройте output/process.bpmn на https://bpmn.io/")
    else:
        print("Диаграмма содержит ошибки.")
        if not auto_fix:
            print("Подсказка: запустите с флагом --fix для автоматического исправления:")
            print("  python scripts/validate_bpmn.py --fix")
        sys.exit(1)


if __name__ == "__main__":
    main()
