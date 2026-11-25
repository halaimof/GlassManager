"""Стартовая настройка CRM (один раз): воронка для душевых, ответственный, правила, канал заявок."""
from __future__ import annotations

import secrets

from .. import repo
from ..db import session
from . import service as S

STAGES = [
    ("Новая заявка", "#d6eaf8", "open"), ("Замер назначен", "#fdebd0", "open"), ("Замер выполнен", "#fcf3cf", "open"),
    ("КП отправлено", "#e8daef", "open"), ("Согласование", "#fadbd8", "open"), ("В производстве", "#d1f2eb", "open"),
    ("Монтаж", "#d4e6f1", "open"), ("Успешно реализовано", "#d4efdf", "won"), ("Закрыто и не реализовано", "#e5e8e8", "lost"),
]


def seed_crm() -> None:
    if repo.settings_get().get("crm_seeded"):
        return
    with session() as c:
        S.insert(c, "crm_users", {"name": "Администратор", "color": "#1f6f8b", "active": 1})
        p = S.insert(c, "pipelines", {"name": "Душевые и стекло", "position": 0})
        ids = {}
        for i, (name, color, kind) in enumerate(STAGES):
            ids[name] = S.insert(c, "stages", {"pipeline_id": p["id"], "name": name, "color": color, "position": i, "kind": kind})["id"]
        rules = [
            ("Новая заявка → связаться с клиентом", "deal_created", None,
             [{"type": "create_task", "kind": "call", "text": "Связаться с клиентом {contact} {phone}", "due_hours": 1}]),
            ("Замер назначен → заказ и выезд", "stage_enter", ids["Замер назначен"],
             [{"type": "create_order"}, {"type": "set_order_status", "status": "measure"},
              {"type": "create_task", "kind": "measure", "text": "Замер: {contact}, {phone}", "due_days": 1, "at_time": "10:00"}]),
            ("Замер выполнен → подготовить КП", "stage_enter", ids["Замер выполнен"],
             [{"type": "create_task", "kind": "other", "text": "Рассчитать изделие и отправить КП (заказ №{order})", "due_days": 1}]),
            ("КП отправлено → согласование заказа", "stage_enter", ids["КП отправлено"],
             [{"type": "set_order_status", "status": "approval"},
              {"type": "create_task", "kind": "call", "text": "Уточнить решение по КП", "due_days": 2}]),
            ("В производстве → статус заказа", "stage_enter", ids["В производстве"],
             [{"type": "set_order_status", "status": "production"}]),
            ("Монтаж → задача монтажа", "stage_enter", ids["Монтаж"],
             [{"type": "set_order_status", "status": "install"},
              {"type": "create_task", "kind": "install", "text": "Монтаж у {contact}", "due_days": 3}]),
            ("Сделка успешна → заказ завершён", "deal_won", None, [{"type": "set_order_status", "status": "done"}]),
        ]
        for name, trig, stage_id, actions in rules:
            S.insert(c, "automations", {"name": name, "active": 1, "trigger": trig, "stage_id": stage_id,
                                        "data": {"actions": actions}})
        S.insert(c, "channels", {"name": "Заявки с сайта", "kind": "form", "active": 1, "token": secrets.token_urlsafe(18),
                                 "data": {"pipeline_id": p["id"], "stage_id": ids["Новая заявка"]}})
    repo.settings_set({"crm_seeded": True})
