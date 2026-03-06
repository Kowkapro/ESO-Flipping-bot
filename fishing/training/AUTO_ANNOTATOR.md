# Auto-Annotator — Автоматическая разметка скриншотов ESO для обучения YOLO

## Проблема

Ручная разметка 500+ скриншотов в CVAT занимает дни. Нужно на каждом скриншоте выделить
квадратиками все объекты (крючки, маркеры, промпты, врагов и т.д.) — это 680+ аннотаций.

## Решение — гибридный подход

Два инструмента авто-разметки, каждый для своего типа объектов:

| Инструмент | Для чего | Почему |
|-----------|----------|--------|
| **Claude Vision** (polza.ai) | Крупные объекты: prompts, bubbles, enemy, hp_bar | Хорошо понимает контекст, текст, UI элементы |
| **YOLO-World** (zero-shot) | Мелкие объекты: fishing_hook, player_icon | Точная пиксельная локализация без обучения |

После авто-разметки — быстрая ревизия в CVAT (поправить ошибки, а не размечать с нуля).

## Результаты тестирования (06.03.26)

### YOLO-World (yolo_world_annotate.py)

**Лучшая конфигурация:** `yolov8s-worldv2` + промпт `"blue pin icon"` + conf=0.05 + imgsz=1280

- **262 карт обработано**, 151 с детекциями, **885 аннотаций fishing_hook**
- Recall ~50% (часть крючков пропускает), но те что находит — точно размечены
- Превью с боксами: `yolo_world_preview/map/`
- CVAT-ready zip: `exports/map_yolo_world_annotations.zip`

**Тест моделей и промптов (10 карт, 73 крючка GT):**

| Модель | Промпт | Детекции |
|--------|--------|----------|
| **yolov8s-worldv2 (small)** | **blue pin icon** | **73/73** |
| yolov8s-worldv2 | 5 других промптов | 0 |
| yolov8m-worldv2 (medium) | blue pin icon | 0 |
| yolov8l-worldv2 (large) | blue pin icon | 1 |

**Вывод:** маленькая модель (small) парадоксально лучше всех. Medium/Large слишком "осторожные" для мелких иконок. Только промпт "blue pin icon" работает.

### Claude Vision (auto_annotate.py)
- **Крупные объекты (bubbles, prompts)**: ХОРОШО — находит и размечает корректно
- **Мелкие объекты (fishing_hook ~20px)**: ПЛОХО — выдумывает равномерную сетку вместо реальных позиций
- Координаты на карте были идеально ровной диагональю с одинаковым шагом = галлюцинация

### Компасные маркеры
- YOLO-World **не находит** компасные маркеры (0 детекций для всех промптов)
- Claude Vision **не тестировался** на компасе
- **Решение:** ручная разметка в CVAT

## Классы модели v3 (10 штук)

| ID | Класс | Описание | Авто-разметка | Где встречается |
|----|-------|----------|---------------|-----------------|
| 0 | fishing_hook | Синий крючок HarvestMap на карте | YOLO-World (~50% recall) | Скриншоты карты |
| 1 | player_icon | Синий треугольник игрока на карте | Ручная (CVAT) | Скриншоты карты |
| 2 | waypoint_pin | Ромб метки на карте | Ручная (CVAT) | Скриншоты карты |
| 3 | waypoint_marker | Маркер нашей метки на компасе | Ручная (CVAT) | Компас/бег |
| 4 | quest_marker | Маркер квеста/POI на компасе | Ручная (CVAT) | Компас/бег |
| 5 | fishing_prompt | "[E] Место рыбалки..." | Claude Vision | Рядом с лункой |
| 6 | npc_prompt | "[E] Поговорить" и т.д. | Claude Vision | Рядом с NPC |
| 7 | bubbles | Пузыри рыбной лунки | Claude Vision | Рядом с лункой |
| 8 | enemy | Враждебный NPC | Claude Vision | Игровой мир |
| 9 | hp_bar | Полоска HP (своя или врага) | Claude Vision | Бой |

## Workflow: от скриншотов до датасета

### 1. Сбор скриншотов
```bash
python fishing/tools/screenshot_collector.py
# Num1=MAP, Num2=COMPASS, Num3=FISHING, Num4=NPC, Num5=COMBAT, Num6=RUNNING, Num7=GENERAL
# Num0=STOP
```
Скриншоты сохраняются в: `fishing/training/screenshots/{category}/`

### 2. Авто-разметка карты (YOLO-World)
```bash
python fishing/training/yolo_world_annotate.py --preview
# Вход:  screenshots/map/*.png
# Выход: annotations/map/*.txt (YOLO format)
# Превью: yolo_world_preview/map/*.png
```

### 3. Импорт в CVAT для ревизии
1. Создать задачу → загрузить скриншоты из `screenshots/map/`
2. `Actions → Upload annotations → YOLO 1.1`
3. Файл: `exports/map_yolo_world_annotations.zip`
4. Поправить: добавить пропущенные крючки, убрать false positives
5. Добавить вручную: player_icon, waypoint_pin
6. Экспорт: `YOLO 1.1` → сохранить в `exports/`

### 4. Авто-разметка крупных объектов (Claude Vision)
```bash
python fishing/training/auto_annotate.py --category fishing --preview
python fishing/training/auto_annotate.py --category combat --preview
```

### 5. Сборка датасета
```bash
python fishing/training/build_dataset.py
# Объединяет все экспорты из exports/ + аннотации
```

### 6. Обучение
```bash
python fishing/training/train.py
# YOLO11l, imgsz=1280, batch=2, patience=25
```

## Скрипты

### yolo_world_annotate.py — YOLO-World массовый аннотатор
- Модель: `yolov8s-worldv2.pt`
- Промпт: `"blue pin icon"` (единственный рабочий для крючков)
- Результат: YOLO .txt + опциональные превью PNG
- `--conf 0.05`, `--preview`, `--input <dir>`

### test_yolo_world_prompts.py — Тест промптов и моделей
- Сравнивает small/medium/large модели и 6 промптов
- Работает на CPU (device="cpu") чтобы не конфликтовать с обучением на GPU

### auto_annotate.py — Claude Vision
- API через polza.ai (OpenAI-совместимый формат)
- Модель: `anthropic/claude-sonnet-4`
- Режимы: `--test`, `--category`, `--all`, `--image`

### screenshot_collector.py — Сбор скриншотов
- 7 категорий: map, compass, fishing, npc, combat, running, general
- Горячие клавиши: **Num1-Num7** (нумпад), **Num0** — стоп
- Скриншоты: `fishing/training/screenshots/{category}/`

## API (Claude Vision)

- Провайдер: polza.ai (прокси для Claude API, OpenAI-совместимый формат)
- Модель: `anthropic/claude-sonnet-4`
- Ключ: из `.env` файла (`POLZA_API_KEY`, `POLZA_BASE_URL`)
- Rate limit: ~10 запросов/мин

## Оценка затрат

- ~100 скриншотов через Claude (крупные объекты) x ~4000 tokens = ~400K tokens ≈ $1-2
- YOLO-World — бесплатно (локальный inference)
- CVAT ревизия: ~2-4 часа (vs 2-3 дня полностью вручную)

## Известные ограничения

1. **Claude Vision**: не подходит для мелких объектов (~20px) — галлюцинирует координаты
2. **Claude Vision**: может давать неточные координаты (±10-20px) даже для крупных объектов
3. **YOLO-World**: работает ТОЛЬКО с `yolov8s-worldv2` и промптом `"blue pin icon"` для крючков
4. **YOLO-World**: medium и large модели дают 0 детекций — не использовать
5. **YOLO-World**: не находит компасные маркеры, промпты, врагов — только карточные иконки
6. Баланс polza.ai ограничен — нужно пополнение для массовой разметки
