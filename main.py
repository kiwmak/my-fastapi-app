from fastapi import FastAPI, File, UploadFile, HTTPException
import pandas as pd
from io import BytesIO

app = FastAPI(title="Excel Upload + Pandas Demo")

@app.get("/")
def read_root():
    return {"message": "Upload an Excel file at /upload_excel"}

@app.post("/upload_excel")
async def upload_excel(file: UploadFile = File(...)):
    # Kiểm tra file có phải Excel không
    if not file.filename.endswith((".xls", ".xlsx")):
        raise HTTPException(status_code=400, detail="File must be Excel (.xls or .xlsx)")

    # Đọc file Excel vào pandas
    try:
        contents = await file.read()
        df = pd.read_excel(BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading Excel file: {e}")

    # Xử lý demo: tính tổng mỗi cột số
    summary = {}
    for col in df.select_dtypes(include="number").columns:
        summary[col] = df[col].sum()

    # Trả dữ liệu JSON
    return {
        "filename": file.filename,
        "rows": len(df),
        "columns": list(df.columns),
        "numeric_summary": summary,
        "preview": df.head(5).to_dict(orient="records")
    }
