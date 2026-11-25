"""CRM: заявка с сайта → сделка → автоматизация → заказ; звонки; аналитика; миграция БД."""
import os
import sqlite3
import tempfile

os.environ.setdefault("GLASSCAD_DATA", tempfile.mkdtemp(prefix="glasscad-crm-"))
os.environ["GLASSCAD_NO_POLLER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def stage_by_name(c, name):
    p = c.get("/api/crm/pipelines").json()[0]
    return next(s for s in p["stages"] if s["name"] == name)


def test_inbound_form_to_order():
    with TestClient(app) as c:
        ch = next(x for x in c.get("/api/crm/channels").json() if x["kind"] == "form")
        url = ch["webhook_url"].split("://", 1)[1].split("/", 1)[1]
        r = c.post("/" + url, json={"name": "Анна", "phone": "8 (999) 123-45-67", "message": "Душевая 1200×2000", "utm_source": "yandex"})
        assert r.status_code == 200, r.text
        deal_id = r.json()["deal_id"]
        # повторная заявка с тем же телефоном — тот же контакт и та же открытая сделка
        r2 = c.post("/" + url, data={"name": "Анна", "phone": "+79991234567", "message": "ещё вопрос"})
        assert r2.json()["deal_id"] == deal_id
        d = c.get(f"/api/crm/deals/{deal_id}").json()
        assert d["contact"]["phone_norm"] == "79991234567"
        assert any(t["kind"] == "call" for t in d["tasks"])                     # правило «новая заявка»
        assert sum(1 for e in d["events"] if e["kind"] == "message_in") == 2

        # перевод на «Замер назначен» → создаётся заказ и задача на замер
        st = stage_by_name(c, "Замер назначен")
        d = c.put(f"/api/crm/deals/{deal_id}", json={"stage_id": st["id"], "amount": 85000}).json()
        assert d["order_id"] and d["order_status"] == "measure"
        assert any(t["kind"] == "measure" for t in d["tasks"])
        order = c.get(f"/api/orders/{d['order_id']}").json()
        assert order["client"] == "Анна"

        # успешно → заказ «Завершён»
        won = stage_by_name(c, "Успешно реализовано")
        d = c.put(f"/api/crm/deals/{deal_id}", json={"stage_id": won["id"]}).json()
        assert d["stage_kind"] == "won" and d["closed_at"] and d["order_status"] == "done"

        a = c.get("/api/crm/analytics").json()
        assert a["summary"]["won"] >= 1 and a["summary"]["won_sum"] >= 85000
        assert a["funnel"][0]["count"] >= 1

        # задачи: выполнение с результатом
        t = c.get("/api/crm/tasks?scope=open").json()[0]
        assert c.post(f"/api/crm/tasks/{t['id']}/complete", json={"result": "дозвонился"}).json()["done"] == 1


def test_missed_call_creates_callback_task():
    with TestClient(app) as c:
        ch = c.post("/api/crm/channels", json={"kind": "telephony", "name": "АТС"}).json()
        path = "/" + ch["webhook_url"].split("://", 1)[1].split("/", 1)[1]
        r = c.post(path, json={"phone": "+7 912 000-11-22", "direction": "in", "status": "missed"}).json()
        tasks = c.get("/api/crm/tasks?scope=open").json()
        assert any(t["text"].startswith("Перезвонить") and t["deal_id"] == r["deal_id"] for t in tasks)
        assert c.post(path.replace(ch["token"], "wrong"), json={"phone": "1"}).status_code == 404


def test_crud_rename_duplicate_delete():
    with TestClient(app) as c:
        co = c.post("/api/crm/companies", json={"name": "ООО Ромашка"}).json()
        ct = c.post("/api/crm/contacts", json={"name": "Иван", "phone": "+79990000001", "company_id": co["id"]}).json()
        assert c.post("/api/crm/contacts", json={"name": "Иван2", "phone": "89990000001"}).status_code == 409
        d = c.post("/api/crm/deals", json={"name": "Зеркало", "contact_id": ct["id"]}).json()
        assert d["company_id"] == co["id"]
        assert c.put(f"/api/crm/deals/{d['id']}", json={"name": "Зеркало в ванную"}).json()["name"] == "Зеркало в ванную"
        assert c.post(f"/api/crm/deals/{d['id']}/duplicate").json()["name"].endswith("(копия)")
        c.post(f"/api/crm/deals/{d['id']}/notes", json={"text": "Клиент просит бронзу"})
        p = c.post("/api/crm/pipelines", json={"name": "Зеркала"}).json()[-1]
        assert len(p["stages"]) == 4
        c.post(f"/api/crm/pipelines/{p['id']}/duplicate")
        assert c.delete(f"/api/crm/deals/{d['id']}").json()["ok"]
        msg = c.post(f"/api/crm/contacts/{ct['id']}/message", json={"text": "Здравствуйте"})
        assert msg.status_code == 400  # нет настроенного канала — понятная ошибка, а не 500


def test_migration_keeps_v1_data(tmp_path):
    from app import config, db

    old = config.DB_PATH
    path = tmp_path / "v1.db"
    try:
        db.DB_PATH = path
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE schema_version(version INTEGER NOT NULL, applied_at TEXT NOT NULL, app_version TEXT NOT NULL DEFAULT '')")
        for stmt in db._split_sql(db.MIGRATIONS[0][2]):
            conn.execute(stmt)
        conn.execute("INSERT INTO schema_version VALUES (1, 'x', '0.1.0')")
        conn.execute("INSERT INTO orders(id, number, created_at, updated_at) VALUES ('o1', '77', 'x', 'x')")
        conn.commit()
        conn.close()
        assert db.migrate() == [2]
        conn = sqlite3.connect(path)
        assert conn.execute("SELECT number FROM orders WHERE id='o1'").fetchone()[0] == "77"
        assert conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 0
        conn.close()
        assert list(config.BACKUP_DIR.glob("*pre-migrate-v1*"))
    finally:
        db.DB_PATH = old
