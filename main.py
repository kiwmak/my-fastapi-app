from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Demo FastAPI App for Render")

# Dữ liệu lưu tạm trong memory
fake_db = []

# Model dữ liệu
class Item(BaseModel):
    id: int
    name: str
    description: str = None

@app.get("/")
def read_root():
    return {"message": "Hello, Render! This is a demo FastAPI app."}

@app.get("/items", response_model=List[Item])
def get_items():
    """Lấy danh sách tất cả item"""
    return fake_db

@app.get("/items/{item_id}", response_model=Item)
def get_item(item_id: int):
    """Lấy item theo id"""
    for item in fake_db:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Item not found")

@app.post("/items", response_model=Item)
def create_item(item: Item):
    """Thêm item mới"""
    # Kiểm tra trùng ID
    for existing_item in fake_db:
        if existing_item["id"] == item.id:
            raise HTTPException(status_code=400, detail="Item with this ID already exists")
    fake_db.append(item.dict())
    return item
