# Скилл: generate_bpmn

## Когда использовать
Когда пользователь просит сгенерировать BPMN, создать диаграмму, показать схему процесса.

## Референсные файлы (прочитай перед запуском)
- `examples/bpmn_example.bpmn` — эталонный корректный BPMN (структура, паттерны)
- `output/process.json` — исходные данные для генерации

## Предусловие
`output/process.json` должен существовать. Если нет — сначала скилл parse_process.

## Шаги выполнения (все обязательны)

1. Генерация:
```
python scripts/generate_bpmn.py
```

2. Валидация — **всегда**, без исключений:
```
python scripts/validate_bpmn.py
```

3. Прочитай JSON-отчёт валидации из stdout:
   - Если `"valid": true` — сообщи пользователю успех
   - Если `"valid": false` — покажи ошибки, предложи запустить скилл update_bpmn с описанием исправлений

4. Как открыть диаграмму:
   - Онлайн: https://bpmn.io/ → Open diagram → выбрать `output/process.bpmn`
   - Десктоп: Camunda Modeler → открыть `output/process.bpmn`

## Критерии корректного BPMN (сверяй с эталоном bpmn_example.bpmn)
- У каждой задачи есть incoming и outgoing
- У шлюза минимум 2 outgoing с условиями (Да/Нет)
- startEvent имеет только outgoing, endEvent только incoming
- Все элементы внутри своей lane
- Нет висячих блоков
