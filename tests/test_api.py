"""Сквозной сценарий через API: заказ → изделие по замеру → комплект → PDF/DXF."""
import os
import tempfile
import zipfile
import io

os.environ["GLASSCAD_DATA"] = tempfile.mkdtemp(prefix="glasscad-api-")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_full_flow():
    with TestClient(app) as c:
        v = c.get("/api/version").json()
        assert v["schema"] >= 1
        tm = {t["data"].get("builtin_key"): t["id"] for t in c.get("/api/lib/construction_templates").json()}
        kit = c.get("/api/lib/kits").json()[0]
        o = c.post("/api/orders", json={"client": "Тест"}).json()
        r = c.post(f"/api/orders/{o['id']}/products", json={
            "measurement": {"width_top": 1200, "height_left": 2200}, "template_id": tm["door_fixed"], "kit_id": kit["id"]}).json()
        res = r["resolved"]
        assert not res["errors"]
        assert len(res["glasses"]) == 2
        assert res["bom"]["hardware"]
        pid = r["product"]["id"]

        # редактирование: ручная ширина двери
        data = r["product"]["data"]
        data["panels"][0]["width"] = {"mode": "value", "value": 700, "formula": ""}
        r2 = c.put(f"/api/products/{pid}", json={"data": data}).json()
        assert r2["resolved"]["glasses"][0]["w"] == 700

        # переименование и дублирование
        c.put(f"/api/products/{pid}", json={"name": "Ванная"})
        dup = c.post(f"/api/products/{pid}/duplicate").json()
        assert dup["product"]["name"] == "Ванная (копия)"
        assert dup["product"]["data"]["panels"][0]["id"] != data["panels"][0]["id"]

        # PDF и DXF
        for mode in ("client", "production", "full"):
            p = c.get(f"/api/orders/{o['id']}/pdf?mode={mode}")
            assert p.status_code == 200 and p.content[:4] == b"%PDF"
        z = c.get(f"/api/products/{pid}/dxf")
        names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
        assert len(names) == 3

        # шаблон из изделия
        t = c.post(f"/api/products/{pid}/save_as_template", json={"name": "Мой шаблон"}).json()
        assert t["collection"] == "construction_templates"

        # дублирование заказа
        o2 = c.post(f"/api/orders/{o['id']}/duplicate").json()
        assert len(o2["products"]) == 2 and o2["number"] != o["number"]

        # библиотека: CRUD
        m = c.post("/api/lib/manufacturers", json={"name": "Vetro", "data": {}}).json()
        c.put(f"/api/lib/manufacturers/{m['id']}", json={"name": "Vetro Glass"})
        assert c.get(f"/api/lib/manufacturers/{m['id']}").json()["name"] == "Vetro Glass"
        assert c.post(f"/api/lib/manufacturers/{m['id']}/duplicate").status_code == 200
        assert c.delete(f"/api/lib/manufacturers/{m['id']}").json()["ok"]
