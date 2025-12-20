from typing import List
from fastapi import FastAPI, HTTPException
from .db import init_db, get_conn
from .schemas import ItemCreate, ItemUpdate, ItemOut

app = FastAPI(title="TODO Service", version="1.0.0")

@app.on_event("startup")
def startup():
    init_db()

@app.post("/items", response_model=ItemOut, status_code=201)
def create_item(payload: ItemCreate):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO items (title, description, completed) VALUES (?, ?, ?)",
            (payload.title, payload.description, 0),
        )
        conn.commit()
        item_id = cur.lastrowid
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row)

@app.get("/items", response_model=List[ItemOut])
def list_items():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM items ORDER BY id DESC").fetchall()
        return [_row_to_item(r) for r in rows]

@app.get("/items/{item_id}", response_model=ItemOut)
def get_item(item_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        return _row_to_item(row)

@app.put("/items/{item_id}", response_model=ItemOut)
def update_item(item_id: int, payload: ItemUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        
        current = dict(row)
        new_title = payload.title if payload.title is not None else current["title"]
        new_desc = payload.description if payload.description is not None else current["description"]
        new_completed = payload.completed if payload.completed is not None else bool(current["completed"])
        
        conn.execute(
            "UPDATE items SET title = ?, description = ?, completed = ? WHERE id = ?",
            (new_title, new_desc, 1 if new_completed else 0, item_id),
        )
        conn.commit()
        
        row2 = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row2)

@app.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()
        return None

def _row_to_item(row) -> ItemOut:
    return ItemOut(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        completed=bool(row["completed"]),
        created_at=row["created_at"],
    )