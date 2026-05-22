"""Pydantic-модели для канбана.

Используются:
  - Внутри MCP-tools для валидации входящих параметров и сериализации результата.
  - Flask-дашбордом для рендера задач.
  - Тестами для конструирования тестовых данных.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# === Константы статусов и ролей ===

STATUSES = ("todo", "wip", "needs_approval", "review", "done", "blocked")
PRIORITIES = ("P0", "P1", "P2", "P3")

# Идентификатор отдела по умолчанию (legacy-миграция с v1.x).
DEFAULT_DEPARTMENT_ID: str = "dev"

ROLES = (
    "тимлид",
    "бэкенд",
    "qa",
    "архитектор",
    "frontend",
    "devops",
    "техписатель",
    "пользователь",
)


class Task(BaseModel):
    """Задача канбана. Соответствует строке таблицы tasks."""

    id: str
    title: str
    description: str = ""
    status: str = "todo"
    assignee: Optional[str] = None
    reporter: Optional[str] = None
    priority: str = "P2"
    labels: list[str] = Field(default_factory=list)
    parent_id: Optional[str] = None
    requires_approval: bool = False
    created_at: int
    updated_at: int
    due_at: Optional[int] = None
    completed_at: Optional[int] = None
    result: Optional[dict[str, Any]] = None


class Comment(BaseModel):
    """Запись истории задачи. Строка таблицы task_comments."""

    id: int
    task_id: str
    author: str
    text: str
    created_at: int


class Role(BaseModel):
    """Виртуальная роль команды. Соответствует строке таблицы roles."""

    name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
