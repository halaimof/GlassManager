"""Аналитика продаж: воронка и конверсия, выручка, источники, менеджеры, задачи."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from .service import rows


def _in(s: str | None, a: str, b: str) -> bool:
    return bool(s) and a <= s[:10] <= b


def analytics(c, pipeline_id: str | None, date_from: str, date_to: str) -> dict:
    if not pipeline_id:
        p = c.execute("SELECT id FROM pipelines ORDER BY position, created_at LIMIT 1").fetchone()
        pipeline_id = p["id"] if p else None
    stages = rows(c.execute("SELECT * FROM stages WHERE pipeline_id=? ORDER BY position", (pipeline_id,)).fetchall())
    skind = {s["id"]: s["kind"] for s in stages}
    open_stages = [s for s in stages if s["kind"] == "open"]
    pos = {s["id"]: i for i, s in enumerate(open_stages)}
    deals = rows(c.execute("SELECT * FROM deals WHERE pipeline_id=?", (pipeline_id,)).fetchall())
    ids = [d["id"] for d in deals]

    # текущая раскладка по этапам
    current = []
    for s in stages:
        ds = [d for d in deals if d["stage_id"] == s["id"]]
        current.append({"stage_id": s["id"], "name": s["name"], "kind": s["kind"], "color": s["color"],
                        "count": len(ds), "amount": sum(d["amount"] or 0 for d in ds)})

    # воронка: какие этапы сделка прошла (по ленте событий)
    reached: dict[str, int] = defaultdict(lambda: -1)
    if ids:
        q = ",".join("?" * len(ids))
        for e in rows(c.execute(f"SELECT deal_id, data FROM events WHERE kind IN ('created','stage') AND deal_id IN ({q})", ids)):
            st = (e["data"] or {}).get("to_stage")
            if st in pos:
                reached[e["deal_id"]] = max(reached[e["deal_id"]], pos[st])
    period = [d for d in deals if _in(d["created_at"], date_from, date_to)]
    funnel = []
    for i, s in enumerate(open_stages):
        n = sum(1 for d in period if skind.get(d["stage_id"]) == "won" or reached[d["id"]] >= i or pos.get(d["stage_id"], -1) >= i)
        funnel.append({"stage_id": s["id"], "name": s["name"], "count": n})
    base = funnel[0]["count"] if funnel and funnel[0]["count"] else 0
    for f in funnel:
        f["conversion"] = round(100 * f["count"] / base, 1) if base else 0.0

    closed = [d for d in deals if _in(d["closed_at"], date_from, date_to)]
    won = [d for d in closed if skind.get(d["stage_id"]) == "won"]
    lost = [d for d in closed if skind.get(d["stage_id"]) == "lost"]
    cycles = []
    for d in won:
        try:
            cycles.append((datetime.fromisoformat(d["closed_at"]) - datetime.fromisoformat(d["created_at"])).days)
        except ValueError:
            pass
    won_sum = sum(d["amount"] or 0 for d in won)
    summary = {
        "created": len(period), "won": len(won), "lost": len(lost), "won_sum": won_sum,
        "avg_check": round(won_sum / len(won)) if won else 0,
        "win_rate": round(100 * len(won) / (len(won) + len(lost)), 1) if (won or lost) else 0.0,
        "avg_cycle_days": round(sum(cycles) / len(cycles), 1) if cycles else None,
        "open_sum": sum(d["amount"] or 0 for d in deals if skind.get(d["stage_id"]) == "open"),
        "open_count": sum(1 for d in deals if skind.get(d["stage_id"]) == "open"),
    }

    src: dict[str, dict] = defaultdict(lambda: {"count": 0, "won": 0, "won_sum": 0.0})
    for d in period:
        s = src[d["source"] or "Не указан"]
        s["count"] += 1
    for d in won:
        s = src[d["source"] or "Не указан"]
        s["won"] += 1
        s["won_sum"] += d["amount"] or 0
    sources = sorted(({"source": k, **v} for k, v in src.items()), key=lambda x: -x["count"])

    reasons: dict[str, int] = defaultdict(int)
    for d in lost:
        reasons[(d["data"] or {}).get("lost_reason") or "Не указана"] += 1

    users = {u["id"]: u for u in rows(c.execute("SELECT * FROM crm_users").fetchall())}
    today = date.today().isoformat()
    mgr: dict[str, dict] = defaultdict(lambda: {"open": 0, "won": 0, "won_sum": 0.0, "tasks_overdue": 0, "tasks_done": 0})
    for d in deals:
        if skind.get(d["stage_id"]) == "open":
            mgr[d["responsible_id"] or ""]["open"] += 1
    for d in won:
        m = mgr[d["responsible_id"] or ""]
        m["won"] += 1
        m["won_sum"] += d["amount"] or 0
    for t in rows(c.execute("SELECT * FROM tasks").fetchall()):
        m = mgr[t["responsible_id"] or ""]
        if not t["done"] and t["due_at"] and t["due_at"][:10] < today:
            m["tasks_overdue"] += 1
        if t["done"] and _in(t["done_at"], date_from, date_to):
            m["tasks_done"] += 1
    managers = [{"user_id": k, "name": (users.get(k) or {}).get("name") or "Без ответственного", **v} for k, v in mgr.items()]
    managers.sort(key=lambda x: -x["won_sum"])

    # помесячно за 12 месяцев
    months = []
    y, mth = date.today().year, date.today().month
    for i in range(11, -1, -1):
        mm = (mth - i - 1) % 12 + 1
        yy = y + (mth - i - 1) // 12
        key = f"{yy:04d}-{mm:02d}"
        months.append({"month": key,
                       "created": sum(1 for d in deals if d["created_at"][:7] == key),
                       "won": sum(1 for d in deals if skind.get(d["stage_id"]) == "won" and (d["closed_at"] or "")[:7] == key),
                       "won_sum": sum(d["amount"] or 0 for d in deals if skind.get(d["stage_id"]) == "won" and (d["closed_at"] or "")[:7] == key)})

    tasks = {
        "overdue": c.execute("SELECT COUNT(*) n FROM tasks WHERE done=0 AND due_at < ?", (today,)).fetchone()["n"],
        "today": c.execute("SELECT COUNT(*) n FROM tasks WHERE done=0 AND substr(due_at,1,10)=?", (today,)).fetchone()["n"],
        "done": sum(1 for t in rows(c.execute("SELECT done_at FROM tasks WHERE done=1").fetchall()) if _in(t["done_at"], date_from, date_to)),
    }
    return {"pipeline_id": pipeline_id, "from": date_from, "to": date_to, "summary": summary, "current": current,
            "funnel": funnel, "sources": sources, "lost_reasons": [{"reason": k, "count": v} for k, v in reasons.items()],
            "managers": managers, "months": months, "tasks": tasks}
