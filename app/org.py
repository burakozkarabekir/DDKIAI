"""Departmanlar ve markalar.

Departmanlar ve markalar iki ayrı kırılımdır: her marka bir departmana bağlıdır (ör. Scania →
"VW Ticari Araç - Scania - Thermo King - Meiller - Wielton"), bir proje bir departmana ve birden çok
markaya ait olabilir. Markası seçilen ama departmanı boş olan projenin departmanı markadan gelir.
"""
from . import db
from .domain import LEGACY_DEPARTMENTS, ORG, match_brands


def ensure_org() -> None:
    """İlk kurulumda 10 departmanı ve markaları yükler; eski sürümden gelen veriyi yeni yapıya taşır (bir kez)."""
    if db.setting("org_v3") == "1":
        return
    dept_ids = {}
    for i, (name, brands) in enumerate(ORG):
        did = db.scalar("SELECT id FROM departments WHERE name = ?", (name,))
        if not did:
            did = db.insert("departments", {"name": name, "sort": i, "active": 1})
        else:
            db.update("departments", did, {"sort": i, "active": 1})
        dept_ids[name] = did
        for j, b in enumerate(brands):
            if not db.scalar("SELECT 1 FROM brands WHERE name = ?", (b,)):
                db.insert("brands", {"name": b, "department_id": did, "sort": j, "active": 1})
    # eski departmanlardaki projeleri yeni karşılıklarına taşı
    for old_name, new_name in LEGACY_DEPARTMENTS.items():
        old = db.scalar("SELECT id FROM departments WHERE name = ?", (old_name,))
        if old and old != dept_ids[new_name]:
            db.execute("UPDATE projects SET department_id = ? WHERE department_id = ?", (dept_ids[new_name], old))
    # serbest metin marka alanını marka kayıtlarına çevir
    brand_ids = {r["name"]: r["id"] for r in db.rows("SELECT id, name FROM brands")}
    for p in db.rows("SELECT id, brands, business_unit, name FROM projects"):
        names = match_brands(p["brands"]) or match_brands(p["business_unit"])
        if names:
            set_project_brands(p["id"], [brand_ids[n] for n in names if n in brand_ids])
    # yeni listede olmayan departmanları kaldır (projelerin departmanı boşalır, Ayarlar'dan atanır)
    keep = tuple(dept_ids.values())
    db.execute(f"UPDATE projects SET department_id = NULL WHERE department_id NOT IN ({','.join('?' * len(keep))})", keep)
    db.execute(f"DELETE FROM departments WHERE id NOT IN ({','.join('?' * len(keep))})", keep)
    db.set_setting("org_v3", "1")


def departments(active_only: bool = True) -> list[dict]:
    return db.rows("SELECT * FROM departments" + (" WHERE active = 1" if active_only else "") + " ORDER BY sort, name")


def brands(active_only: bool = True) -> list[dict]:
    return db.rows("SELECT b.*, d.name AS dept FROM brands b LEFT JOIN departments d ON d.id = b.department_id"
                   + (" WHERE b.active = 1" if active_only else "") + " ORDER BY d.sort, b.sort, b.name")


def grouped_brands() -> list[dict]:
    """Departman başına marka listesi (formlarda gruplu seçim için)."""
    out = []
    bs = brands()
    for d in departments():
        items = [b for b in bs if b["department_id"] == d["id"]]
        if items:
            out.append({"dept": d, "brands": items})
    orphans = [b for b in bs if not b["department_id"]]
    if orphans:
        out.append({"dept": {"id": None, "name": "Departmansız"}, "brands": orphans})
    return out


def project_brand_ids(pid: int) -> list[int]:
    return [r["brand_id"] for r in db.rows("SELECT brand_id FROM project_brands WHERE project_id = ?", (pid,))]


def set_project_brands(pid: int, brand_ids: list[int], infer_department: bool = True) -> None:
    """Proje markalarını kaydeder; projects.brands metnini (arama ve AI bağlamı için) eşitler."""
    with db.tx() as c:
        c.execute("DELETE FROM project_brands WHERE project_id = ?", (pid,))
        for bid in dict.fromkeys(brand_ids):
            c.execute("INSERT OR IGNORE INTO project_brands (project_id, brand_id) VALUES (?, ?)", (pid, bid))
    rows = db.rows("SELECT b.name, b.department_id FROM project_brands pb JOIN brands b ON b.id = pb.brand_id "
                   "WHERE pb.project_id = ? ORDER BY b.sort", (pid,))
    data = {"brands": ", ".join(r["name"] for r in rows) or None}
    if infer_department and rows:
        depts = {r["department_id"] for r in rows if r["department_id"]}
        current = db.scalar("SELECT department_id FROM projects WHERE id = ?", (pid,))
        if not current and len(depts) == 1:
            data["department_id"] = depts.pop()
    db.update("projects", pid, data)


def brand_ids_from_text(text: str | None) -> list[int]:
    ids = {r["name"]: r["id"] for r in db.rows("SELECT id, name FROM brands")}
    return [ids[n] for n in match_brands(text) if n in ids]


def brands_by_project() -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for r in db.rows("SELECT pb.project_id, b.name FROM project_brands pb JOIN brands b ON b.id = pb.brand_id ORDER BY b.sort"):
        out.setdefault(r["project_id"], []).append(r["name"])
    return out
