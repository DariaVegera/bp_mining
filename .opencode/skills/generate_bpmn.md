# Скилл: generate_bpmn

## Когда использовать
Когда пользователь:
- Просит "сгенерировать BPMN", "создать диаграмму", "построить схему процесса"
- Уже запустил parse_process и хочет увидеть результат
- Просит "показать диаграмму"

## Предусловие
Файл `output/process.json` должен существовать.
Если не существует — сначала запусти скилл `parse_process`.

## Шаги выполнения

1. Проверь наличие файла `output/process.json`

2. Запусти команду:
```
python scripts/generate_bpmn.py
```

3. Скрипт сохранит BPMN в `output/process.bpmn`

4. Сообщи пользователю как открыть диаграмму:

**Вариант 1 — онлайн (рекомендуется):**
- Перейдите на https://bpmn.io/
- Нажмите иконку папки (Open diagram)
- Выберите файл `output/process.bpmn`

**Вариант 2 — Camunda Modeler (десктоп):**
- Скачайте с https://camunda.com/download/modeler/
- Откройте файл `output/process.bpmn`

## Возможные ошибки

- **process.json не найден** — сначала запусти parse_process
- **Ошибка шаблона** — проверь наличие файла `templates/process.bpmn.j2`
