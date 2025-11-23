import os
import shutil
import logging
import uuid
import re
import glob
import time
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

# =======================================================================
# === CẤU HÌNH HỆ THỐNG & LOGGING ===
# =======================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Quản lý Test Đốt (MySQL)", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Cấu hình Thư mục ---
UPLOAD_DIR = "uploads"
EXPORT_DIR = "exports"
TEMPLATE_DIR = "templates"

for directory in [UPLOAD_DIR, EXPORT_DIR, TEMPLATE_DIR]:
    os.makedirs(directory, exist_ok=True)

TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "MAU.xlsx")
LOGO_FILE = os.path.join(TEMPLATE_DIR, "logo.png")

# --- Hàm tiện ích ---
def excel_col_to_index(col):
    """Chuyển chữ Excel (A, B...) thành index (0, 1...)"""
    col = col.upper()
    index = 0
    for i, char in enumerate(reversed(col)):
        index += (ord(char) - ord('A') + 1) * (26 ** i)
    return index - 1

def save_upload_file(upload_file: UploadFile, destination_path: str, filename: str):
    """Lưu file upload"""
    final_path = os.path.join(destination_path, filename)
    try:
        with open(final_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
        logger.info(f"Đã lưu file: {final_path}")
        return True
    except Exception as e:
        logger.error(f"Lỗi lưu file {filename}: {e}")
        return False

# =======================================================================
# === QUẢN LÝ DATABASE (MySQL) ===
# =======================================================================

class DatabaseManager:
    def __init__(self):
        # Ưu tiên lấy từ ENV, nếu không có thì dùng chuỗi mặc định của bạn
        self.db_url = os.environ.get(
            "DATABASE_URL", 
            "mysql+pymysql://root:vnBZVyqPcxqHMFbmdehHNYDxIOdBWWBO@yamabiko.proxy.rlwy.net:28046/railway"
        )
        self.engine = self.init_engine()
        self.ensure_table_exists()

    def init_engine(self):
        max_retries = 10
        delay = 3
        
        for attempt in range(1, max_retries + 1):
            try:
                engine = create_engine(
                    self.db_url,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                    pool_size=10,
                    max_overflow=20,
                    connect_args={"connect_timeout": 10}
                )
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                logger.info("🎉 MySQL READY! Đã kết nối thành công.")
                return engine
            except OperationalError as e:
                logger.warning(f"MySQL chưa sẵn sàng (thử {attempt}/{max_retries})...")
                time.sleep(delay)
        
        raise RuntimeError("❌ Không thể kết nối MySQL sau nhiều lần thử!")

    def ensure_table_exists(self):
        create_table_query = """
        CREATE TABLE IF NOT EXISTS `data` (
            `KHÁCH HÀNG` VARCHAR(255),
            `ĐƠN HÀNG` VARCHAR(255),
            `MÃ HÀNG` VARCHAR(255),
            `KÍCH THƯỚC` VARCHAR(100),
            `BẤC` VARCHAR(100),
            `MÀU` VARCHAR(100),
            `HƯƠNG LIỆU` VARCHAR(255),
            `NGÀY_TẠO` DATETIME,
            PRIMARY KEY (`ĐƠN HÀNG`, `MÃ HÀNG`)
        );
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(text(create_table_query))
            logger.info("Bảng 'data' đã được kiểm tra/tạo.")
        except Exception as e:
            logger.error(f"Lỗi tạo bảng: {e}")

    def import_data(self, file_path):
        try:
            # 1. Đọc Excel
            df_new = pd.read_excel(file_path, header=None, skiprows=1).fillna("")
            
            # Mapping cột
            cotNguon_Index = [excel_col_to_index(c) for c in ["A", "B", "G", "M", "Y", "AB"]]
            cotDich_Name = ["KHÁCH HÀNG", "ĐƠN HÀNG", "MÃ HÀNG", "KÍCH THƯỚC", "MÀU", "HƯƠNG LIỆU"]
            
            df_result = pd.DataFrame()
            for src_idx, dst_col in zip(cotNguon_Index, cotDich_Name):
                if src_idx < len(df_new.columns):
                    df_result[dst_col] = df_new.iloc[:, src_idx].astype(str).str.strip()
                else:
                    df_result[dst_col] = ""

            if "BẤC" not in df_result.columns:
                df_result["BẤC"] = ""
            
            # Lọc dữ liệu rỗng
            required_cols = ["KHÁCH HÀNG", "ĐƠN HÀNG", "MÃ HÀNG"]
            df_result = df_result.replace(r'^\s*$', float('nan'), regex=True).dropna(subset=required_cols)
            
            if df_result.empty:
                return {"success": False, "message": "File không có dữ liệu hợp lệ (thiếu Khách/Đơn/Mã)"}

            # 2. Chuẩn bị Insert
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            insert_query = """
            INSERT INTO `data` 
            (`KHÁCH HÀNG`, `ĐƠN HÀNG`, `MÃ HÀNG`, `KÍCH THƯỚC`, `MÀU`, `HƯƠNG LIỆU`, `BẤC`, `NGÀY_TẠO`)
            VALUES (:kh, :dh, :mh, :kt, :mau, :hl, :bac, :nt)
            ON DUPLICATE KEY UPDATE
                `KHÁCH HÀNG` = VALUES(`KHÁCH HÀNG`),
                `KÍCH THƯỚC` = VALUES(`KÍCH THƯỚC`),
                `MÀU` = VALUES(`MÀU`),
                `HƯƠNG LIỆU` = VALUES(`HƯƠNG LIỆU`),
                `BẤC` = VALUES(`BẤC`),
                `NGÀY_TẠO` = VALUES(`NGÀY_TẠO`);
            """

            # Map dict keys từ DataFrame sang bind params của SQL (:kh, :dh...)
            data_to_insert = []
            for _, row in df_result.iterrows():
                data_to_insert.append({
                    "kh": row["KHÁCH HÀNG"],
                    "dh": row["ĐƠN HÀNG"],
                    "mh": row["MÃ HÀNG"],
                    "kt": row["KÍCH THƯỚC"],
                    "mau": row["MÀU"],
                    "hl": row["HƯƠNG LIỆU"],
                    "bac": row["BẤC"],
                    "nt": now_str
                })

            with self.engine.begin() as conn:
                conn.execute(text(insert_query), data_to_insert)

            # Đếm tổng dòng
            with self.engine.connect() as conn:
                total = conn.execute(text("SELECT COUNT(*) FROM `data`")).scalar()

            return {
                "success": True, 
                "message": f"Đã import {len(data_to_insert)} dòng.", 
                "total_rows": total
            }

        except Exception as e:
            logger.error(f"Lỗi Import: {e}")
            return {"success": False, "message": str(e)}

    def get_orders_list(self):
        try:
            with self.engine.connect() as conn:
                # Lấy danh sách đơn hàng và đếm số lượng mã hàng trong mỗi đơn
                query = """
                SELECT `ĐƠN HÀNG`, COUNT(*) as count 
                FROM `data` 
                WHERE `ĐƠN HÀNG` IS NOT NULL AND `ĐƠN HÀNG` != ''
                GROUP BY `ĐƠN HÀNG`
                ORDER BY `NGÀY_TẠO` DESC
                """
                rows = conn.execute(text(query)).fetchall()
                
                # Format kết quả
                orders = [{"order_no": row[0], "item_count": row[1]} for row in rows]
                
                total = conn.execute(text("SELECT COUNT(*) FROM `data`")).scalar()
                return {"orders": orders, "total_rows": total}
        except Exception as e:
            logger.error(f"Lỗi lấy DS đơn hàng: {e}")
            return {"orders": [], "total_rows": 0}

    def get_order_detail(self, order_no):
        try:
            with self.engine.connect() as conn:
                query = text("SELECT * FROM `data` WHERE `ĐƠN HÀNG` = :o")
                result = conn.execute(query, {"o": order_no}).mappings().fetchall()
                
                # Convert date objects to string if needed
                data = []
                for row in result:
                    r = dict(row)
                    if isinstance(r.get('NGÀY_TẠO'), datetime):
                        r['NGÀY_TẠO'] = r['NGÀY_TẠO'].strftime("%Y-%m-%d %H:%M:%S")
                    data.append(r)
                return data
        except Exception as e:
            logger.error(f"Lỗi chi tiết đơn {order_no}: {e}")
            return []

# =======================================================================
# === EXPORT MANAGER (Xử lý Excel Output) ===
# =======================================================================

class ExportManager:
    def __init__(self):
        self.template_file = TEMPLATE_FILE
        self.logo_file = LOGO_FILE

    def get_reports_list(self):
        reports = []
        if os.path.exists(EXPORT_DIR):
            for f in glob.glob(os.path.join(EXPORT_DIR, "*.xlsx")):
                fname = os.path.basename(f)
                ctime = datetime.fromtimestamp(os.path.getctime(f))
                reports.append({
                    "filename": fname,
                    "created_time": ctime.strftime("%Y-%m-%d %H:%M:%S"),
                    "order_no": fname.split('_')[0]
                })
        reports.sort(key=lambda x: x["created_time"], reverse=True)
        return reports

    def delete_report(self, filename):
        try:
            path = os.path.join(EXPORT_DIR, filename)
            if os.path.exists(path):
                os.remove(path)
                return True
            return False
        except Exception:
            return False

    def parse_kich_thuoc(self, kt_str):
        if not kt_str: return "", ""
        try:
            s = str(kt_str).lower().replace('×', 'x').replace('*', 'x').replace(',', '.')
            parts = re.findall(r"[\d.]+", s)
            if len(parts) >= 2:
                w, h = float(parts[0]), float(parts[1])
                if 'cm' in s: w, h = w*10, h*10
                return round(w, 1), round(h, 1)
        except:
            pass
        return "", ""

    def export_with_template(self, order_no, df_data, output_path):
        if not os.path.exists(self.template_file):
            return {"success": False, "message": "Chưa upload file Template (MAU.xlsx)"}
        
        try:
            shutil.copy2(self.template_file, output_path)
            wb = load_workbook(output_path)
            ws_temp = wb.worksheets[0]
            temp_name = ws_temp.title
            
            created_count = 0
            
            # Group by Mã Hàng để mỗi mã hàng là 1 sheet (nếu có trùng) hoặc mỗi dòng 1 sheet
            # Ở đây giả sử logic: Duyệt từng dòng sản phẩm
            for _, row in df_data.iterrows():
                ma_hang = str(row.get("MÃ HÀNG", "Unknown"))[:30].replace("/", "-")
                
                # Tạo sheet mới
                new_sheet = wb.copy_worksheet(ws_temp)
                
                # Đặt tên sheet (unique)
                base_name = ma_hang
                cnt = 1
                while base_name in wb.sheetnames:
                    base_name = f"{ma_hang}_{cnt}"
                    cnt += 1
                new_sheet.title = base_name
                
                # Điền dữ liệu
                mapping = {
                    "C5": order_no,
                    "C6": row.get("KHÁCH HÀNG"),
                    "C7": row.get("HƯƠNG LIỆU"),
                    "C8": row.get("MÀU"),
                    "C9": row.get("BẤC"),
                    "N5": row.get("MÃ HÀNG"),
                    "N8": datetime.now().strftime("%d/%m/%Y")
                }
                
                w, h = self.parse_kich_thuoc(row.get("KÍCH THƯỚC"))
                mapping["N6"] = w
                mapping["S6"] = h

                for cell, val in mapping.items():
                    if val is not None:
                        new_sheet[cell] = val
                
                # Chèn logo
                if os.path.exists(self.logo_file):
                    try:
                        img = OpenpyxlImage(self.logo_file)
                        new_sheet.add_image(img, 'A1')
                    except: pass
                
                created_count += 1

            # Xóa sheet mẫu
            if temp_name in wb.sheetnames and len(wb.sheetnames) > 1:
                del wb[temp_name]
            
            wb.save(output_path)
            return {"success": True, "message": "Thành công", "sheets": created_count}

        except Exception as e:
            logger.error(f"Lỗi Export: {e}")
            return {"success": False, "message": str(e)}

# =======================================================================
# === KHỞI TẠO SERVICES ===
# =======================================================================

try:
    db_manager = DatabaseManager()
    export_manager = ExportManager()
except Exception as e:
    logger.critical(f"Lỗi khởi tạo: {e}")

# =======================================================================
# === API ENDPOINTS ===
# =======================================================================

@app.mount("/exports", StaticFiles(directory=EXPORT_DIR), name="exports")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return HTML_TEMPLATE

@app.post("/api/import")
async def api_import(file: UploadFile = File(...)):
    tmp_name = f"import_{uuid.uuid4()}.xlsx"
    if not save_upload_file(file, UPLOAD_DIR, tmp_name):
        raise HTTPException(500, "Lỗi lưu file")
    
    path = os.path.join(UPLOAD_DIR, tmp_name)
    res = db_manager.import_data(path)
    os.remove(path)
    
    if res["success"]: return res
    raise HTTPException(400, res["message"])

@app.get("/api/orders")
async def api_get_orders():
    return db_manager.get_orders_list()

@app.get("/api/reports")
async def api_get_reports():
    rp = export_manager.get_reports_list()
    return {"reports": rp}

@app.post("/api/export-template/{order_no}")
async def api_export(order_no: str):
    data = db_manager.get_order_detail(order_no)
    if not data:
        raise HTTPException(404, "Không tìm thấy dữ liệu")
    
    df = pd.DataFrame(data)
    fname = f"{order_no}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    fpath = os.path.join(EXPORT_DIR, fname)
    
    res = export_manager.export_with_template(order_no, df, fpath)
    if res["success"]:
        return {"success": True, "download_url": f"/exports/{fname}", "filename": fname}
    raise HTTPException(500, res["message"])

@app.delete("/api/reports/{filename}")
async def api_del_report(filename: str):
    if export_manager.delete_report(filename):
        return {"success": True}
    raise HTTPException(404, "File không tồn tại")

@app.post("/api/upload-template")
async def api_up_template(file: UploadFile = File(...)):
    if save_upload_file(file, TEMPLATE_DIR, "MAU.xlsx"):
        return {"success": True}
    raise HTTPException(500, "Lỗi")

@app.post("/api/upload-logo")
async def api_up_logo(file: UploadFile = File(...)):
    if save_upload_file(file, TEMPLATE_DIR, "logo.png"):
        return {"success": True}
    raise HTTPException(500, "Lỗi")


# =======================================================================
# === GIAO DIỆN NGƯỜI DÙNG (HTML + JS Full) ===
# =======================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hệ thống Test Đốt (MySQL)</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
    <style>
        body { background-color: #f4f6f9; font-family: 'Segoe UI', sans-serif; }
        .card { border: none; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-radius: 12px; }
        .btn-custom { border-radius: 8px; font-weight: 500; }
        .table thead th { background-color: #e9ecef; border: none; }
        .status-badge { font-size: 0.8em; padding: 5px 10px; border-radius: 20px; background: #d1e7dd; color: #0f5132; }
    </style>
</head>
<body class="p-4">
    <div class="container-fluid" style="max-width: 1400px;">
        <h2 class="mb-4 text-primary"><i class="fas fa-fire me-2"></i>Quản lý Test Đốt</h2>

        <ul class="nav nav-pills mb-4" id="pills-tab" role="tablist">
            <li class="nav-item">
                <button class="nav-link active" data-bs-toggle="pill" data-bs-target="#tab-home">
                    <i class="fas fa-home me-2"></i>Trang chủ
                </button>
            </li>
            <li class="nav-item">
                <button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-reports" onclick="loadReports()">
                    <i class="fas fa-file-excel me-2"></i>Báo cáo đã tạo
                </button>
            </li>
            <li class="nav-item">
                <button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-settings">
                    <i class="fas fa-cog me-2"></i>Cài đặt
                </button>
            </li>
        </ul>

        <div class="tab-content">
            <div class="tab-pane fade show active" id="tab-home">
                <div class="row">
                    <div class="col-md-4">
                        <div class="card p-4 mb-4">
                            <h5><i class="fas fa-upload me-2 text-success"></i>Import Dữ liệu Mới</h5>
                            <p class="text-muted small">File Excel phải có các cột: Khách hàng, Đơn hàng, Mã hàng...</p>
                            <input type="file" id="importFile" class="form-control mb-3" accept=".xlsx">
                            <button class="btn btn-success w-100 btn-custom" onclick="importData()">
                                <i class="fas fa-cloud-upload-alt me-2"></i>Tải lên Database
                            </button>
                        </div>
                    </div>

                    <div class="col-md-8">
                        <div class="card p-4">
                            <div class="d-flex justify-content-between align-items-center mb-3">
                                <h5><i class="fas fa-list me-2 text-primary"></i>Danh sách Đơn hàng trong DB</h5>
                                <button class="btn btn-sm btn-outline-primary" onclick="loadOrders()">
                                    <i class="fas fa-sync"></i> Làm mới
                                </button>
                            </div>
                            <div class="table-responsive">
                                <table class="table table-hover align-middle">
                                    <thead>
                                        <tr>
                                            <th>Đơn hàng (Order No)</th>
                                            <th>Số lượng Mã</th>
                                            <th class="text-end">Hành động</th>
                                        </tr>
                                    </thead>
                                    <tbody id="ordersTableBody">
                                        </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="tab-pane fade" id="tab-reports">
                <div class="card p-4">
                    <div class="d-flex justify-content-between mb-3">
                        <h5>Lịch sử Xuất Báo Cáo</h5>
                        <button class="btn btn-sm btn-outline-secondary" onclick="loadReports()">Làm mới</button>
                    </div>
                    <table class="table">
                        <thead>
                            <tr>
                                <th>Tên File</th>
                                <th>Đơn hàng</th>
                                <th>Ngày tạo</th>
                                <th class="text-end">Thao tác</th>
                            </tr>
                        </thead>
                        <tbody id="reportsTableBody"></tbody>
                    </table>
                </div>
            </div>

            <div class="tab-pane fade" id="tab-settings">
                <div class="row">
                    <div class="col-md-6">
                        <div class="card p-4 mb-3">
                            <h6>File Mẫu (Template)</h6>
                            <input type="file" id="templateFile" class="form-control mb-2">
                            <button class="btn btn-primary btn-sm" onclick="uploadConfig('template')">Cập nhật MAU.xlsx</button>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card p-4 mb-3">
                            <h6>Logo Báo cáo</h6>
                            <input type="file" id="logoFile" class="form-control mb-2">
                            <button class="btn btn-info btn-sm text-white" onclick="uploadConfig('logo')">Cập nhật Logo</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // --- 1. Load Orders ---
        async function loadOrders() {
            try {
                const res = await axios.get('/api/orders');
                const list = res.data.orders;
                const tbody = document.getElementById('ordersTableBody');
                tbody.innerHTML = '';
                
                if(list.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Chưa có dữ liệu</td></tr>';
                    return;
                }

                list.forEach(item => {
                    const row = `
                        <tr>
                            <td class="fw-bold">${item.order_no}</td>
                            <td><span class="badge bg-secondary">${item.item_count} items</span></td>
                            <td class="text-end">
                                <button class="btn btn-sm btn-primary" onclick="exportReport('${item.order_no}')">
                                    <i class="fas fa-file-export me-1"></i> Xuất Excel
                                </button>
                            </td>
                        </tr>
                    `;
                    tbody.innerHTML += row;
                });
            } catch (err) {
                console.error(err);
                alert("Lỗi tải danh sách đơn hàng");
            }
        }

        // --- 2. Import Data ---
        async function importData() {
            const fileInput = document.getElementById('importFile');
            if(!fileInput.files[0]) return alert("Vui lòng chọn file!");

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);

            try {
                // Hiển thị trạng thái đang xử lý (có thể thêm spinner nếu muốn)
                const btn = document.querySelector('button[onclick="importData()"]');
                const originalText = btn.innerHTML;
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Đang xử lý...';
                btn.disabled = true;

                const res = await axios.post('/api/import', formData);
                alert(res.data.message);
                fileInput.value = '';
                loadOrders(); // Reload list
            } catch (err) {
                alert("Lỗi: " + (err.response?.data?.detail || err.message));
            } finally {
                // Reset nút bấm
                const btn = document.querySelector('button[onclick="importData()"]');
                btn.innerHTML = '<i class="fas fa-cloud-upload-alt me-2"></i>Tải lên Database';
                btn.disabled = false;
            }
        }

        // --- 3. Export Report ---
        async function exportReport(orderNo) {
            try {
                const res = await axios.post(`/api/export-template/${orderNo}`);
                if(res.data.success) {
                    // Tự động tải xuống
                    const link = document.createElement('a');
                    link.href = res.data.download_url;
                    link.download = res.data.filename;
                    link.click();
                    loadReports(); // Update tab reports
                }
            } catch (err) {
                alert("Lỗi xuất file: " + (err.response?.data?.detail || err.message));
            }
        }

        // --- 4. Load Reports History ---
        async function loadReports() {
            try {
                const res = await axios.get('/api/reports');
                const tbody = document.getElementById('reportsTableBody');
                tbody.innerHTML = '';
                
                res.data.reports.forEach(r => {
                    tbody.innerHTML += `
                        <tr>
                            <td><a href="/exports/${r.filename}">${r.filename}</a></td>
                            <td>${r.order_no}</td>
                            <td>${r.created_time}</td>
                            <td class="text-end">
                                <button class="btn btn-sm btn-danger" onclick="deleteReport('${r.filename}')">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    `;
                });
            } catch(e) { console.error(e); }
        }

        async function deleteReport(fname) {
            if(!confirm("Xóa file này?")) return;
            try {
                await axios.delete(`/api/reports/${fname}`);
                loadReports();
            } catch(e) { alert("Lỗi xóa file"); }
        }

        // --- 5. Upload Template/Logo ---
        async function uploadConfig(type) {
            const id = type === 'template' ? 'templateFile' : 'logoFile';
            const endpoint = type === 'template' ? '/api/upload-template' : '/api/upload-logo';
            const file = document.getElementById(id).files[0];
            
            if(!file) return alert("Chọn file trước!");
            const fd = new FormData();
            fd.append('file', file);
            
            try {
                await axios.post(endpoint, fd);
                alert("Cập nhật thành công!");
            } catch(e) { alert("Lỗi cập nhật"); }
        }

        // Init
        document.addEventListener('DOMContentLoaded', loadOrders);
    </script>
</body>
</html>
"""
