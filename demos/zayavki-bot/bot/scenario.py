"""Движок диалога: сценарий описывается в YAML, а не в коде.

Это главное решение всего проекта. Новый клиент — это новый
scenario.yaml, а не новая разработка: час работы вместо трёх дней.
Отсюда берётся маржа на втором и последующих заказах.

Конфиг проверяется целиком при загрузке. Опечатка в сценарии должна
падать при запуске, а не ночью, когда её найдёт клиент клиента.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from .validators import (
    looks_like_junk, match_choice, normalize_phone, parse_number, validate_email,
)

STEP_TYPES = ("text", "phone", "email", "number", "choice")

SKIP_WORDS = {"-", "нет", "пропустить", "/skip", "skip"}


class ScenarioError(ValueError):
    """Сценарий описан неверно. Бросается при загрузке, не в рантайме."""


@dataclass(frozen=True)
class Step:
    id: str
    question: str
    type: str = "text"
    options: List[str] = field(default_factory=list)
    required: bool = True
    error: str = ""
    label: str = ""

    @property
    def title(self) -> str:
        """Как поле называется в готовой заявке."""
        return self.label or self.id


@dataclass
class Scenario:
    steps: List[Step]
    greeting: str = "Здравствуйте! Задам несколько вопросов и передам заявку."
    completion: str = "Спасибо, заявка принята. Мы свяжемся с вами."
    cancelled: str = "Заявка отменена. Наберите /start, чтобы начать заново."

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Scenario":
        if not isinstance(data, dict):
            raise ScenarioError("сценарий должен быть словарём с ключом steps")

        raw_steps = data.get("steps")
        if not raw_steps:
            raise ScenarioError("в сценарии нет ни одного шага (ключ steps)")
        if not isinstance(raw_steps, list):
            raise ScenarioError("steps должен быть списком")

        steps: List[Step] = []
        seen: set = set()
        for i, raw in enumerate(raw_steps, 1):
            if not isinstance(raw, dict):
                raise ScenarioError(f"шаг {i}: должен быть словарём")

            step_id = raw.get("id")
            if not step_id:
                raise ScenarioError(f"шаг {i}: не указан id")
            if step_id in seen:
                raise ScenarioError(f"шаг {i}: id '{step_id}' уже использован")
            seen.add(step_id)

            question = raw.get("question")
            if not question:
                raise ScenarioError(f"шаг '{step_id}': не указан question")

            step_type = raw.get("type", "text")
            if step_type not in STEP_TYPES:
                raise ScenarioError(
                    f"шаг '{step_id}': неизвестный тип '{step_type}'. "
                    f"Доступные: {', '.join(STEP_TYPES)}"
                )

            options = raw.get("options") or []
            if step_type == "choice" and not options:
                raise ScenarioError(f"шаг '{step_id}': тип choice требует options")
            if options and step_type != "choice":
                raise ScenarioError(
                    f"шаг '{step_id}': options имеют смысл только для типа choice"
                )

            steps.append(Step(
                id=str(step_id),
                question=str(question),
                type=step_type,
                options=[str(o) for o in options],
                required=bool(raw.get("required", True)),
                error=str(raw.get("error", "")),
                label=str(raw.get("label", "")),
            ))

        return cls(
            steps=steps,
            greeting=str(data.get("greeting", cls.greeting)),
            completion=str(data.get("completion", cls.completion)),
            cancelled=str(data.get("cancelled", cls.cancelled)),
        )

    @classmethod
    def from_yaml(cls, path: str) -> "Scenario":
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except FileNotFoundError:
            raise ScenarioError(f"файл сценария не найден: {path}") from None
        except yaml.YAMLError as exc:
            raise ScenarioError(f"{path}: не разобрался YAML: {exc}") from None
        return cls.from_dict(data)

    def step(self, index: int) -> Optional[Step]:
        return self.steps[index] if 0 <= index < len(self.steps) else None


@dataclass
class Session:
    """Состояние одного пользователя в диалоге."""

    index: int = 0
    answers: Dict[str, Any] = field(default_factory=dict)
    done: bool = False

    def reset(self) -> None:
        self.index = 0
        self.answers = {}
        self.done = False


@dataclass(frozen=True)
class Reply:
    """Что бот отвечает и что показывает на клавиатуре."""

    text: str
    options: List[str] = field(default_factory=list)
    finished: bool = False
    lead: Optional[Dict[str, Any]] = None
    progress: str = ""


_DEFAULT_ERRORS = {
    "phone": "Не похоже на телефон. Например: +7 916 123-45-67",
    "email": "Не похоже на почту. Например: ivan@mail.ru",
    "number": "Нужно число. Например: 1500",
    "choice": "Выберите один из вариантов ниже.",
    "text": "Слишком короткий ответ — напишите чуть подробнее.",
}


def _validate(step: Step, raw: str):
    """Вернуть (значение, ошибка). Ровно одно из двух непусто."""
    if step.type == "phone":
        value = normalize_phone(raw)
    elif step.type == "email":
        value = validate_email(raw)
    elif step.type == "number":
        value = parse_number(raw)
    elif step.type == "choice":
        value = match_choice(raw, step.options)
    else:
        value = None if looks_like_junk(raw) else raw.strip()

    if value is None:
        return None, step.error or _DEFAULT_ERRORS[step.type]
    return value, ""


class Engine:
    """Ведёт пользователя по сценарию. Ничего не знает о телеграме."""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario

    def _progress(self, index: int) -> str:
        return f"Вопрос {index + 1} из {len(self.scenario.steps)}"

    def _ask(self, session: Session) -> Reply:
        step = self.scenario.step(session.index)
        if step is None:
            return self._finish(session)
        question = step.question
        if not step.required:
            question += "\n\nЕсли неактуально — отправьте «-»."
        return Reply(question, list(step.options), progress=self._progress(session.index))

    def _finish(self, session: Session) -> Reply:
        session.done = True
        lead = {
            step.title: session.answers.get(step.id)
            for step in self.scenario.steps
            if session.answers.get(step.id) is not None
        }
        return Reply(self.scenario.completion, finished=True, lead=lead)

    def start(self, session: Session) -> List[Reply]:
        """Начать диалог заново."""
        session.reset()
        return [Reply(self.scenario.greeting), self._ask(session)]

    def answer(self, session: Session, raw: str) -> Reply:
        """Обработать ответ и вернуть следующую реплику."""
        if session.done:
            return Reply("Заявка уже отправлена. Наберите /start для новой.")

        step = self.scenario.step(session.index)
        if step is None:
            return self._finish(session)

        text = (raw or "").strip()

        if text.lower() in ("/back", "назад"):
            # Навигация обрабатывается всегда, даже на первом вопросе.
            # Иначе «назад» записывается как ответ — и клиент получает
            # заявку, в которой имя клиента «назад».
            if session.index > 0:
                session.index -= 1
                previous = self.scenario.step(session.index)
                if previous is not None:
                    session.answers.pop(previous.id, None)
            return self._ask(session)

        if not step.required and text.lower() in SKIP_WORDS:
            session.answers[step.id] = None
            session.index += 1
            return self._ask(session)

        value, error = _validate(step, text)
        if error:
            return Reply(
                error,
                list(step.options),
                progress=self._progress(session.index),
            )

        session.answers[step.id] = value
        session.index += 1
        return self._ask(session)
