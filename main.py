from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from openpyxl.drawing.image import Image as OpenpyxlImage
import os
import shutil
from datetime import datetime
import uuid
import logging
import re
import glob

# Import thư viện mới cho MySQL
from sqlalchemy import create_engine, text
import pymysql




# --- Cấu hình logging, app, CORS (Giữ nguyên) ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Quản lý Test Đốt", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/templates", StaticFiles(directory="templates"), name="templates")

@app.get("/nhietdo")
def nhiet_do():
    return FileResponse("nhiet_do_do_sap_web.html")
@app.get("/muoi")
def muoi():
    return FileResponse("muoi.html") 
@app.get("/status")
def status():
    return FileResponse("status_candel.html")  
# --- Thư mục và File paths (Giữ nguyên) ---
UPLOAD_DIR = "uploads"
EXPORT_DIR = "exports"
DATA_DIR = "data"
TEMPLATE_DIR = "templates"

for directory in [UPLOAD_DIR, EXPORT_DIR, DATA_DIR, TEMPLATE_DIR]:
    os.makedirs(directory, exist_ok=True)

TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "MAU.xlsx")
LOGO_FILE = os.path.join(TEMPLATE_DIR, "logo.png")

# --- Hàm chuyển đổi cột (Giữ nguyên) ---
def excel_col_to_index(col):
    """Chuyển chữ Excel (A, B, C...) thành index (0, 1, 2...)"""
    col = col.upper()
    index = 0
    for i, char in enumerate(reversed(col)):
        index += (ord(char) - ord('A') + 1) * (26 ** i)
    return index - 1  # Vì index bắt đầu từ 0

# =======================================================================
# === PHẦN THAY THẾ: DataManager -> DatabaseManager ===
# =======================================================================

class DatabaseManager:
    def __init__(self):
        # 1. Đọc chuỗi kết nối từ biến môi trường
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            logger.error("DATABASE_URL không được set!")
            raise ValueError("DATABASE_URL không được set!")

        # 2. SQLAlchemy cần driver 'mysql+pymysql' thay vì 'mysql'
        if db_url.startswith("mysql://"):
            db_url = db_url.replace("mysql://", "mysql+pymysql://", 1)
        
        self.engine = create_engine(db_url)
        logger.info("Đã kết nối tới MySQL Database.")
        
        # 3. Đảm bảo bảng dữ liệu tồn tại
        self.ensure_table_exists()

    def ensure_table_exists(self):
        """
        Tạo bảng 'data' nếu nó chưa tồn tại.
        Sử dụng backticks (`) cho tên cột tiếng Việt/có dấu cách.
        """
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
            logger.info("Bảng 'data' đã được đảm bảo tồn tại.")
        except Exception as e:
            logger.error(f"Lỗi khi tạo bảng: {e}")

    def import_data(self, file_path):
        """
        Đọc file Excel và import vào MySQL.
        Sử dụng logic "INSERT ... ON DUPLICATE KEY UPDATE" để mimic `drop_duplicates(keep='last')`.
        """
        try:
            # --- Phần đọc và xử lý Pandas (Giữ nguyên logic của bạn) ---
            df_new = pd.read_excel(file_path, header=None, skiprows=1).fillna("")
            logger.info(f"Đọc được {len(df_new)} dòng dữ liệu từ file import (bắt đầu từ dòng thứ 2)")

            cotNguon_Index = [excel_col_to_index(c) for c in ["A", "B", "G", "M", "Y", "AB"]]
            cotDich_Name = ["KHÁCH HÀNG", "ĐƠN HÀNG", "MÃ HÀNG", "KÍCH THƯỚC", "MÀU", "HƯƠNG LIỆU"]

            df_result = pd.DataFrame()
            for src_idx, dst_col in zip(cotNguon_Index, cotDich_Name):
                if src_idx < len(df_new.columns):
                    df_result[dst_col] = df_new.iloc[:, src_idx]
                else:
                    df_result[dst_col] = ""
                    logger.warning(f"Không tìm thấy cột index {src_idx} trong file import")

            additional_cols = {"BẤC": ""}
            for col, default_value in additional_cols.items():
                if col not in df_result.columns:
                    df_result[col] = default_value

            df_result["NGÀY_TẠO"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            required_cols = ["KHÁCH HÀNG", "ĐƠN HÀNG", "MÃ HÀNG"]
            missing_data_mask = pd.Series([False] * len(df_result))
            for col in required_cols:
                if col in df_result.columns:
                    missing_data_mask = missing_data_mask | df_result[col].isnull() | (df_result[col] == "")
            
            invalid_rows_count = 0
            if missing_data_mask.any():
                invalid_rows_count = len(df_result[missing_data_mask])
                logger.warning(f"Phát hiện {invalid_rows_count} dòng thiếu dữ liệu bắt buộc")
                df_result = df_result[~missing_data_mask]

            if df_result.empty:
                return {"success": False, "message": "Không có dữ liệu hợp lệ để import sau khi lọc"}

            # --- Phần ghi vào Database (Mới) ---
            
            # Câu lệnh SQL này sẽ Cập nhật (UPDATE) nếu (ĐƠN HÀNG, MÃ HÀNG) đã tồn tại,
            # hoặc Thêm mới (INSERT) nếu chưa có.
            insert_query = """
            INSERT INTO `data` (`KHÁCH HÀNG`, `ĐƠN HÀNG`, `MÃ HÀNG`, `KÍCH THƯỚC`, `MÀU`, `HƯƠNG LIỆU`, `BẤC`, `NGÀY_TẠO`)
            VALUES (:kh, :dh, :mh, :kt, :mau, :hl, :bac, :nt)
            ON DUPLICATE KEY UPDATE
                `KHÁCH HÀNG` = VALUES(`KHÁCH HÀNG`),
                `KÍCH THƯỚC` = VALUES(`KÍCH THƯỚC`),
                `MÀU` = VALUES(`MÀU`),
                `HƯƠNG LIỆU` = VALUES(`HƯƠNG LIỆU`),
                `BẤC` = VALUES(`BẤC`),
                `NGÀY_TẠO` = VALUES(`NGÀY_TẠO`);
            """

            # Chuyển DataFrame thành list of dicts để thực thi
            data_to_insert = df_result.to_dict('records')
            
            # Mở một transaction để insert hàng loạt
            with self.engine.begin() as conn:
                conn.execute(text(insert_query), data_to_insert)

            # Lấy tổng số dòng hiện có
            total_rows_result = conn.execute(text("SELECT COUNT(*) FROM `data`"))
            total_rows = total_rows_result.scalar_one()

            return {
                "success": True,
                "message": f"Import thành công: {len(df_result)} dòng (đã bỏ qua {invalid_rows_count} dòng không hợp lệ)",
                "imported_rows": len(df_result),
                "skipped_rows": invalid_rows_count,
                "total_rows": total_rows
            }

        except Exception as e:
            logger.error(f"Lỗi import: {e}")
            return {"success": False, "message": f"Lỗi: {str(e)}"}

    def get_orders_list(self):
        """API Lấy danh sách các đơn hàng (ORDER NO) và tổng số dòng dữ liệu"""
        try:
            with self.engine.connect() as conn:
                # Lấy danh sách Đơn Hàng duy nhất
                query_orders = text("SELECT DISTINCT `ĐƠN HÀNG` FROM `data` WHERE `ĐƠN HÀNG` IS NOT NULL AND `ĐƠN HÀNG` != ''")
                orders_result = conn.execute(query_orders).fetchall()
                orders = [row[0] for row in orders_result]
                
                # Lấy tổng số dòng
                query_total = text("SELECT COUNT(*) FROM `data`")
                total_rows = conn.execute(query_total).scalar_one()
                
                return {"orders": orders, "total_rows": total_rows}
        except Exception as e:
            logger.error(f"Lỗi lấy danh sách đơn hàng: {e}")
            return {"orders": [], "total_rows": 0}

    def get_order_detail(self, order_no: str):
        """API Lấy chi tiết dữ liệu theo đơn hàng"""
        try:
            with self.engine.connect() as conn:
                query = text("SELECT * FROM `data` WHERE `ĐƠN HÀNG` = :order_no")
                # .mappings().fetchall() trả về list of dicts, chuẩn JSON
                result = conn.execute(query, {"order_no": order_no}).mappings().fetchall()
                
                if not result:
                    return None # Sẽ raise 404 ở API endpoint
                
                # Chuyển đổi các kiểu dữ liệu (nếu cần, ví dụ: datetime)
                data_list = []
                for row in result:
                    row_dict = dict(row)
                    if 'NGÀY_TẠO' in row_dict and isinstance(row_dict['NGÀY_TẠO'], datetime):
                        row_dict['NGÀY_TẠO'] = row_dict['NGÀY_TẠO'].strftime("%Y-%m-%d %H:%M:%S")
                    data_list.append(row_dict)

                return data_list
        except Exception as e:
            logger.error(f"Lỗi lấy chi tiết đơn hàng {order_no}: {e}")
            raise HTTPException(status_code=500, detail=f"Lỗi server khi truy vấn data: {e}")

# =======================================================================
# === ExportManager (KHÔNG THAY ĐỔI) ===
# =======================================================================

class ExportManager:
    def __init__(self):
        self.template_file = TEMPLATE_FILE
        self.logo_file = LOGO_FILE

    def get_reports_list(self):
        """Lấy danh sách các báo cáo đã tạo"""
        try:
            reports = []
            if os.path.exists(EXPORT_DIR):
                for file_path in glob.glob(os.path.join(EXPORT_DIR, "*.xlsx")):
                    file_name = os.path.basename(file_path)
                    file_size = os.path.getsize(file_path)
                    created_time = datetime.fromtimestamp(os.path.getctime(file_path))
                    parts = file_name.replace('.xlsx', '').split('_')
                    order_no = parts[0] if parts else "Unknown"
                    reports.append({
                        "filename": file_name,
                        "order_no": order_no,
                        "file_size": file_size,
                        "created_time": created_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "file_path": file_path
                    })
            reports.sort(key=lambda x: x["created_time"], reverse=True)
            return reports
        except Exception as e:
            logger.error(f"Lỗi lấy danh sách báo cáo: {e}")
            return []

    def delete_report(self, filename: str):
        """Xóa báo cáo"""
        try:
            file_path = os.path.join(EXPORT_DIR, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Đã xóa báo cáo: {filename}")
                return True
            return False
        except Exception as e:
            logger.error(f"Lỗi xóa báo cáo {filename}: {e}")
            return False

    def export_with_template(self, order_no: str, order_data: pd.DataFrame, output_path: str) -> dict:
        """Xuất báo cáo theo template MAU.xlsx"""
        try:
            if not os.path.exists(self.template_file):
                return {"success": False,
                        "message": f"Không tìm thấy file template: {os.path.basename(self.template_file)}"}

            logger.info(f"Bắt đầu xuất báo cáo cho đơn hàng: {order_no}")

            shutil.copy2(self.template_file, output_path)
            wb = load_workbook(output_path)
            template_sheet = wb.worksheets[0]
            template_sheet_name = template_sheet.title

            sheets_created = 0
            ma_hang_list = order_data["MÃ HÀNG"].dropna().unique()

            for ma_hang in ma_hang_list:
                ma_hang_str = str(ma_hang).strip()
                if not ma_hang_str:
                    continue

                try:
                    new_sheet = wb.copy_worksheet(template_sheet)
                    sheet_name = ma_hang_str[:31]
                    original_name = sheet_name
                    counter = 1

                    while sheet_name in wb.sheetnames:
                        sheet_name = f"{original_name}_{counter}"
                        if len(sheet_name) > 31:
                            sheet_name = sheet_name[:31]
                        counter += 1

                    new_sheet.title = sheet_name
                    sheets_created += 1

                    product_data = order_data[order_data["MÃ HÀNG"].astype(str) == ma_hang_str]
                    if product_data.empty:
                        continue

                    row_data = product_data.iloc[0]
                    mapping = self.get_cell_mapping(order_no, row_data)

                    for cell_ref, value in mapping.items():
                        try:
                            if value not in (None, ""):
                                # Chuyển đổi kiểu dữ liệu nếu là số
                                if isinstance(value, (int, float)):
                                    new_sheet[cell_ref] = float(value)
                                else:
                                    new_sheet[cell_ref] = value
                        except Exception as e:
                            logger.warning(f"Không thể ghi ô {cell_ref}: {e}")

                    self.insert_logo(new_sheet)
                    logger.info(f"Đã tạo sheet cho mã hàng: {ma_hang_str}")

                except Exception as e:
                    logger.error(f"Lỗi tạo sheet cho {ma_hang}: {e}")
                    continue

            if sheets_created > 0 and template_sheet_name in wb.sheetnames:
                try:
                    wb.remove(wb[template_sheet_name])
                except Exception as e:
                    logger.warning(f"Không thể xóa sheet template: {e}")

            wb.save(output_path)
            logger.info(f"Xuất báo cáo thành công: {sheets_created} sheets")

            return {
                "success": True,
                "message": f"Xuất báo cáo thành công: {sheets_created} mã hàng",
                "sheets_created": sheets_created,
                "file_path": output_path
            }

        except Exception as e:
            logger.error(f"Lỗi xuất báo cáo: {e}")
            return {"success": False, "message": f"Lỗi xuất báo cáo: {str(e)}"}

    def get_cell_mapping(self, order_no: str, row_data: pd.Series) -> dict:
        """Mapping dữ liệu vào các ô trong template"""
        mapping = {
            "C5": order_no,  # Đơn hàng
            "C6": row_data.get("KHÁCH HÀNG", ""),  # Khách hàng
            "C7": row_data.get("HƯƠNG LIỆU", ""),  # Hương liệu
            "C8": row_data.get("MÀU", ""),  # Màu
            "C9": row_data.get("BẤC", ""),  # Bấc
            "N5": row_data.get("MÃ HÀNG", ""),  # Mã hàng
            "N8": datetime.now().strftime("%Y-%m-%d")  # Ngày test
        }

        kich_thuoc = str(row_data.get("KÍCH THƯỚC", ""))
        duong_kinh, chieu_cao = self.parse_kich_thuoc(kich_thuoc)

        mapping["N6"] = duong_kinh  # Đường kính
        mapping["S6"] = chieu_cao  # Chiều cao

        return mapping

    def parse_kich_thuoc(self, kich_thuoc: str) -> tuple:
        """Phân tích chuỗi kích thước thành đường kính và chiều cao"""
        if not kich_thuoc:
            return "", ""

        try:
            kich_thuoc = str(kich_thuoc).lower().replace('×', 'x').replace('*', 'x').replace(' ', '')
            parts = re.findall(r'[\d.]+', kich_thuoc)

            if len(parts) >= 2:
                duong_kinh = float(parts[0])
                chieu_cao = float(parts[1])

                if 'cm' in kich_thuoc:
                    duong_kinh *= 10
                    chieu_cao *= 10

                return round(duong_kinh, 1), round(chieu_cao, 1)
            else:
                return "", ""

        except Exception as e:
            logger.warning(f"Lỗi phân tích kích thước '{kich_thuoc}': {e}")
            return "", ""

    def insert_logo(self, worksheet):
        """Chèn logo vào worksheet"""
        try:
            if os.path.exists(self.logo_file):
                img = OpenpyxlImage(self.logo_file)
                worksheet.add_image(img, 'A1')
                logger.info("Đã chèn logo vào báo cáo")
        except Exception as e:
            logger.warning(f"Không thể chèn logo: {e}")

# =======================================================================
# === KHỞI TẠO MANAGER VÀ API ENDPOINTS ===
# =======================================================================

# Khởi tạo các manager
try:
    db_manager = DatabaseManager()
except ValueError as e:
    logger.critical(f"KHÔNG THỂ KHỞI ĐỘNG ỨNG DỤNG: {e}")
    # Bạn có thể muốn exit(1) ở đây nếu không set DB_URL
    # For now, we let it crash if DB_URL is not set
    
export_manager = ExportManager()

# --- Hàm Tiện Ích (Mới) ---
def save_upload_file(upload_file: UploadFile, destination_path: str, filename: str):
    """Lưu file được upload vào thư mục chỉ định với tên file đã cho"""
    final_path = os.path.join(destination_path, filename)
    try:
        with open(final_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
        logger.info(f"Đã lưu file: {final_path}")
        return True
    except Exception as e:
        logger.error(f"Lỗi lưu file {filename}: {e}")
        return False


# --- Cập nhật API Endpoints ---

# Mount thư mục exports để client có thể tải xuống file
app.mount("/exports", StaticFiles(directory=EXPORT_DIR), name="exports")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Endpoint gốc trả về trang HTML"""
    return HTML_TEMPLATE

@app.post("/api/import")
async def import_data_endpoint(file: UploadFile = File(...)):
    """API Import dữ liệu từ file Excel (Đã cập nhật)"""
    # 1. Lưu file tạm thời
    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    if not save_upload_file(file, UPLOAD_DIR, unique_filename):
        raise HTTPException(status_code=500, detail="Không thể lưu file upload.")

    # 2. Xử lý Import bằng DatabaseManager
    result = db_manager.import_data(file_path)

    # 3. Xóa file tạm thời
    os.remove(file_path)

    if result["success"]:
        return JSONResponse(status_code=200, content=result)
    else:
        raise HTTPException(status_code=400, detail=result["message"])

@app.get("/api/orders")
async def get_orders_list():
    """API Lấy danh sách các đơn hàng (Đã cập nhật)"""
    result = db_manager.get_orders_list()
    return result

@app.get("/api/order/{order_no}")
async def get_order_detail(order_no: str):
    """API Lấy chi tiết dữ liệu theo đơn hàng (Đã cập nhật)"""
    data_list = db_manager.get_order_detail(order_no)
    
    if data_list is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy đơn hàng: {order_no}")

    return {"order_no": order_no, "total_items": len(data_list), "data": data_list}


@app.post("/api/export-template/{order_no}")
async def export_report_endpoint(order_no: str):
    """API Xuất báo cáo (Đã cập nhật)"""
    
    # 1. Lấy dữ liệu từ DB
    data_list = db_manager.get_order_detail(order_no)
    if not data_list:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy dữ liệu cho đơn hàng: {order_no}")

    # 2. Chuyển đổi lại thành DataFrame để ExportManager có thể xử lý
    #    (Điều này giữ cho ExportManager không cần thay đổi)
    order_data_df = pd.DataFrame(data_list)
    
    if order_data_df.empty:
        raise HTTPException(status_code=404, detail=f"Không có dữ liệu để xuất cho đơn hàng: {order_no}")

    # 3. Tạo tên file và gọi ExportManager
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:4]
    output_filename = f"{order_no}_{timestamp}_{unique_id}.xlsx"
    output_path = os.path.join(EXPORT_DIR, output_filename)

    # ExportManager giờ nhận DataFrame được tạo từ DB
    result = export_manager.export_with_template(order_no, order_data_df, output_path)

    if result["success"]:
        download_url = f"/exports/{output_filename}"
        return JSONResponse(status_code=200, content={
            "success": True,
            "message": result["message"],
            "download_url": download_url,
            "filename": output_filename
        })
    else:
        raise HTTPException(status_code=500, detail=result["message"])

@app.get("/api/reports")
async def get_reports():
    """API Lấy danh sách các báo cáo đã tạo (Giữ nguyên)"""
    reports = export_manager.get_reports_list()
    return {"reports": reports, "count": len(reports)}

@app.delete("/api/reports/{filename}")
async def delete_report_endpoint(filename: str):
    """API Xóa một báo cáo cụ thể (Giữ nguyên)"""
    if export_manager.delete_report(filename):
        return {"success": True, "message": f"Đã xóa báo cáo: {filename}"}
    raise HTTPException(status_code=404, detail=f"Không tìm thấy báo cáo: {filename}")

@app.delete("/api/reports")
async def clear_all_reports_endpoint():
    """API Xóa tất cả các báo cáo (Giữ nguyên)"""
    count = 0
    for report in export_manager.get_reports_list():
        if export_manager.delete_report(report["filename"]):
            count += 1
    return {"success": True, "message": f"Đã xóa thành công {count} báo cáo"}

@app.get("/api/download/{filename}")
async def download_report_endpoint(filename: str):
    """API Tải xuống báo cáo (Giữ nguyên)"""
    file_path = os.path.join(EXPORT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Không tìm thấy file")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.post("/api/upload-template")
async def upload_template_endpoint(file: UploadFile = File(...)):
    """API Tải lên file template MAU.xlsx mới (Mới)"""
    if not file.filename.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="File phải là định dạng Excel (.xlsx hoặc .xlsm)")
        
    if save_upload_file(file, TEMPLATE_DIR, "MAU.xlsx"):
        return {"success": True, "message": "Đã cập nhật Template (MAU.xlsx) thành công!"}
    raise HTTPException(status_code=500, detail="Lỗi khi lưu file template")


@app.post("/api/upload-logo")
async def upload_logo_endpoint(file: UploadFile = File(...)):
    """API Tải lên file logo mới (Mới)"""
    ext = file.filename.split('.')[-1].lower()
    if ext not in ["png", "jpg", "jpeg"]:
        raise HTTPException(status_code=400, detail="Logo phải là file PNG hoặc JPG/JPEG")
    
    if save_upload_file(file, TEMPLATE_DIR, "logo.png"): 
        return {"success": True, "message": "Đã cập nhật Logo thành công!"}
    raise HTTPException(status_code=500, detail="Lỗi khi lưu file logo")


# =======================================================================
# === HTML_TEMPLATE (Hoàn thiện phần JavaScript bị thiếu) ===
# =======================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quản lý Test Đốt</title>
    <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }
        .container { max-width: 1400px; }
        .card { border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); border: none; }
        .btn-export { background: linear-gradient(135deg, #28a745, #20c997); color: white; border: none; }
        .btn-export:hover { transform: translateY(-1px); box-shadow: 0 4px 8px rgba(40, 167, 69, 0.3); }
        .report-item { transition: all 0.3s ease; border-left: 4px solid #007bff; }
        .report-item:hover { transform: translateX(5px); background-color: #f8f9fa; }
        .nav-tabs .nav-link.active { font-weight: 600; border-bottom: 3px solid #007bff; }
        .file-size { font-size: 0.85rem; color: #6c757d; }
        .action-buttons .btn { padding: 0.25rem 0.5rem; font-size: 0.875rem; }
    </style>
</head>
<body>
    <div class="container mt-4">
        <h1 class="text-center mb-4">🏭 Quản lý Test Đốt (MySQL ver)</h1>

        <ul class="nav nav-tabs mb-4" id="mainTabs" role="tablist">
            <li class="nav-item" role="presentation">
                <button class="nav-link active" id="dashboard-tab" data-bs-toggle="tab" data-bs-target="#dashboard" type="button" role="tab">
                    <i class="fas fa-tachometer-alt me-2"></i>Dashboard
                </button>
            </li>
            <li class="nav-item" role="presentation">
                <button class="nav-link" id="reports-tab" data-bs-toggle="tab" data-bs-target="#reports" type="button" role="tab">
                    <i class="fas fa-file-alt me-2"></i>Báo cáo đã tạo
                </button>
            </li>
            <li class="nav-item" role="presentation">
                <button class="nav-link" id="templates-tab" data-bs-toggle="tab" data-bs-target="#templates" type="button" role="tab">
                    <i class="fas fa-cog me-2"></i>Quản lý Template
                </button>
            </li>
            <li class="nav-item" role="presentation">
                <a class="nav-link" href="/soot" target="_blank">
                    <i class="fas fa-fire-alt me-2"></i>Mức độ muội than
                </a>
            </li>
            <li class="nav-item" role="presentation">
                <a class="nav-link" href="/status" target="_blank">
                    <i class="fas fa-fire-alt me-2"></i>Hướng dấn đánh giá kết quả test đốt 
                </a>
            </li>
            </ul>

        <div class="tab-content" id="mainTabsContent">
            <div class="tab-pane fade show active" id="dashboard" role="tabpanel">
                <div class="row">
                    <div class="col-md-6">
                        <div class="card p-3 mb-4">
                            <h5><i class="fas fa-file-import me-2"></i>Import Dữ liệu (MySQL)</h5>
                            <input type="file" id="fileInput" class="form-control mb-2" accept=".xlsx">
                            <button class="btn btn-primary" onclick="importData()">
                                <i class="fas fa-upload me-2"></i>Import Excel
                            </button>
                            <div id="importResult" class="mt-2"></div>
                        </div>
                    </div>

                    <div class="col-md-6">
                        <div class="card p-3">
                            <h5><i class="fas fa-chart-bar me-2"></i>Thống kê (MySQL)</h5>
                            <p><i class="fas fa-boxes me-2"></i>Tổng đơn hàng: <span id="totalOrders" class="fw-bold">0</span></p>
                            <p><i class="fas fa-database me-2"></i>Tổng dòng dữ liệu: <span id="totalRows" class="fw-bold">0</span></p>
                            <button class="btn btn-info" onclick="loadStats()">
                                <i class="fas fa-sync-alt me-2"></i>Làm mới
                            </button>
                        </div>
                    </div>
                </div>

                <div class="card p-3 mt-4">
                    <h5><i class="fas fa-rocket me-2"></i>Xuất báo cáo theo template</h5>
                    <div class="row">
                        <div class="col-md-6">
                            <select id="orderSelect" class="form-select mb-2" onchange="loadOrderDetail()">
                                <option value="">-- Chọn đơn hàng --</option>
                            </select>
                        </div>
                        <div class="col-md-6">
                            <button class="btn btn-export w-100" onclick="exportWithTemplate()">
                                <i class="fas fa-file-export me-2"></i>Xuất báo cáo theo mẫu
                            </button>
                        </div>
                    </div>
                    <div id="orderDetail" class="mt-3"></div>
                </div>
            </div>

            <div class="tab-pane fade" id="reports" role="tabpanel">
                <div class="card p-3">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h5><i class="fas fa-history me-2"></i>Danh sách báo cáo đã tạo</h5>
                        <button class="btn btn-outline-primary" onclick="loadReports()">
                            <i class="fas fa-sync-alt me-2"></i>Làm mới
                        </button>
                    </div>

                    <div class="table-responsive">
                        <table class="table table-hover">
                            <thead class="table-light">
                                <tr>
                                    <th>Tên file</th>
                                    <th>Đơn hàng</th>
                                    <th>Kích thước</th>
                                    <th>Ngày tạo</th>
                                    <th>Thao tác</th>
                                </tr>
                            </thead>
                            <tbody id="reportsList">
                                <tr>
                                    <td colspan="5" class="text-center text-muted py-4">
                                        <i class="fas fa-spinner fa-spin me-2"></i>Đang tải...
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="d-flex justify-content-between align-items-center mt-3">
                        <small class="text-muted" id="reportsCount">Đang tải...</small>
                        <button class="btn btn-outline-danger btn-sm" onclick="clearAllReports()">
                            <i class="fas fa-trash me-2"></i>Xóa tất cả
                        </button>
                    </div>
                </div>
            </div>

            <div class="tab-pane fade" id="templates" role="tabpanel">
                <div class="card p-3">
                    <h5><i class="fas fa-cog me-2"></i>Quản lý Template</h5>
                    <div class="row">
                        <div class="col-md-6">
                            <div class="mb-3">
                                <label class="form-label">File template (MAU.xlsx):</label>
                                <input type="file" id="templateFile" class="form-control" accept=".xlsx,.xlsm">
                                <small class="form-text text-muted">Tải lên file template mới (Định dạng .xlsx)</small>
                            </div>
                            <button class="btn btn-warning" onclick="uploadTemplate()">
                                <i class="fas fa-upload me-2"></i>Tải lên Template
                            </button>
                        </div>
                        <div class="col-md-6">
                            <div class="mb-3">
                                <label class="form-label">Logo:</label>
                                <input type="file" id="logoFile" class="form-control" accept=".png,.jpg,.jpeg">
                                <small class="form-text text-muted">Tải lên logo mới (PNG/JPG)</small>
                            </div>
                            <button class="btn btn-warning" onclick="uploadLogo()">
                                <i class="fas fa-image me-2"></i>Tải lên Logo
                            </button>
                        </div>
                    </div>
                    <div id="templateResult" class="mt-2"></div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>

    <script>
        const API_BASE = '/api';

        // Khởi tạo khi trang load
        document.addEventListener('DOMContentLoaded', function() {
            loadStats();
            loadOrders();
            loadReports();
            
            // Lắng nghe sự kiện chuyển tab để làm mới danh sách báo cáo
            var reportsTab = document.getElementById('reports-tab')
            reportsTab.addEventListener('shown.bs.tab', function (event) {
                loadReports();
            })
        });

        async function loadStats() {
            try {
                const response = await axios.get(`${API_BASE}/orders`);
                document.getElementById('totalOrders').textContent = response.data.orders.length;
                // Lấy tổng số dòng trực tiếp từ API
                document.getElementById('totalRows').textContent = response.data.total_rows;
            } catch (error) {
                console.error('Lỗi tải thống kê:', error);
                document.getElementById('totalRows').textContent = "Lỗi";
                document.getElementById('totalOrders').textContent = "Lỗi";
            }
        }

        async function importData() {
            const file = document.getElementById('fileInput').files[0];
            const importResultDiv = document.getElementById('importResult');
            importResultDiv.innerHTML = `<div class="alert alert-info mt-2"><i class="fas fa-spinner fa-spin me-2"></i>Đang xử lý...</div>`;

            if (!file) {
                showAlert('importResult', false, 'Vui lòng chọn file trước!');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            try {
                const response = await axios.post(`${API_BASE}/import`, formData);
                showAlert('importResult', response.data.success, response.data.message);
                loadStats(); // Tải lại thống kê
                loadOrders(); // Tải lại danh sách đơn hàng
            } catch (error) {
                // Hiển thị lỗi từ server
                const errorMessage = error.response ? error.response.data.detail : 'Lỗi kết nối hoặc xử lý file';
                showAlert('importResult', false, errorMessage);
            }
        }

        async function loadOrders() {
            try {
                const response = await axios.get(`${API_BASE}/orders`);
                const select = document.getElementById('orderSelect');
                select.innerHTML = '<option value="">-- Chọn đơn hàng --</option>';
                response.data.orders.forEach(order => {
                    const option = document.createElement('option');
                    option.value = order;
                    option.textContent = order;
                    select.appendChild(option);
                });
            } catch (error) {
                console.error('Lỗi tải danh sách đơn hàng:', error);
            }
        }

        async function loadOrderDetail() {
            const orderNo = document.getElementById('orderSelect').value;
            const orderDetailDiv = document.getElementById('orderDetail');
            orderDetailDiv.innerHTML = ''; // Xóa chi tiết cũ
            if (!orderNo) return;

            orderDetailDiv.innerHTML = `<p class="text-center text-info"><i class="fas fa-spinner fa-spin me-2"></i>Đang tải chi tiết...</p>`;

            try {
                const response = await axios.get(`${API_BASE}/order/${orderNo}`);
                let html = '<div class="table-responsive"><table class="table table-striped table-sm"><thead><tr>';
                if (response.data.data.length > 0) {
                    // Lấy key từ bản ghi đầu tiên
                    Object.keys(response.data.data[0]).forEach(key => {
                        html += `<th>${key}</th>`;
                    });
                    html += '</tr></thead><tbody>';
                    response.data.data.forEach(row => {
                        html += '<tr>';
                        Object.values(row).forEach(value => {
                            html += `<td>${value || ''}</td>`;
                        });
                        html += '</tr>';
                    });
                    html += '</tbody></table></div>';
                } else {
                     html = '<div class="alert alert-warning mt-3">Không có chi tiết dữ liệu cho đơn hàng này.</div>';
                }
                document.getElementById('orderDetail').innerHTML = html;
            } catch (error) {
                 const errorMessage = error.response ? error.response.data.detail : 'Lỗi tải chi tiết đơn hàng';
                showAlert('orderDetail', false, errorMessage);
            }
        }

        async function exportWithTemplate() {
            const orderNo = document.getElementById('orderSelect').value;
            const orderDetailDiv = document.getElementById('orderDetail');
            orderDetailDiv.innerHTML = `<div class="alert alert-info mt-3"><i class="fas fa-rocket fa-bounce me-2"></i>Đang xuất báo cáo...</div>`;

            if (!orderNo) {
                showAlert('orderDetail', false, 'Vui lòng chọn đơn hàng!');
                return;
            }

            try {
                // Post request để tạo file
                const response = await axios.post(`${API_BASE}/export-template/${orderNo}`);
                if (response.data.success) {
                    showAlert('orderDetail', true, response.data.message);
                    
                    // Tự động download file
                    const downloadLink = document.createElement('a');
                    downloadLink.href = response.data.download_url;
                    downloadLink.download = response.data.filename; // Gán tên file đã tạo
                    document.body.appendChild(downloadLink);
                    downloadLink.click();
                    document.body.removeChild(downloadLink);

                    // Làm mới danh sách báo cáo
                    setTimeout(loadReports, 1000);
                } else {
                    showAlert('orderDetail', false, response.data.message);
                }
            } catch (error) {
                const errorMessage = error.response ? error.response.data.detail : 'Lỗi xuất báo cáo';
                showAlert('orderDetail', false, errorMessage);
            }
        }

        async function loadReports() {
            try {
                const tbody = document.getElementById('reportsList');
                tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin me-2"></i>Đang tải...</td></tr>`;
                
                const response = await axios.get(`${API_BASE}/reports`);
                const reports = response.data.reports || [];

                if (reports.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="5" class="text-center text-muted py-4">
                                <i class="fas fa-inbox me-2"></i>Chưa có báo cáo nào được tạo
                            </td>
                        </tr>
                    `;
                    document.getElementById('reportsCount').textContent = '0 báo cáo';
                    return;
                }

                let html = '';
                reports.forEach(report => {
                    const fileSize = (report.file_size / 1024).toFixed(1) + ' KB';
                    html += `
                        <tr class="report-item">
                            <td>
                                <i class="fas fa-file-excel text-success me-2"></i>
                                <strong>${report.filename}</strong>
                            </td>
                            <td>${report.order_no}</td>
                            <td><span class="file-size">${fileSize}</span></td>
                            <td>${report.created_time}</td>
                            <td class="action-buttons">
                                <button class="btn btn-success btn-sm me-1" onclick="downloadReport('${report.filename}')" title="Tải xuống">
                                    <i class="fas fa-download"></i>
                                </button>
                                <button class="btn btn-primary btn-sm me-1" onclick="viewReport('${report.filename}')" title="Xem trước">
                                    <i class="fas fa-eye"></i>
                                </button>
                                <button class="btn btn-danger btn-sm" onclick="deleteReport('${report.filename}')" title="Xóa">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    `;
                });

                tbody.innerHTML = html;
                document.getElementById('reportsCount').textContent = `${reports.length} báo cáo`;

            } catch (error) {
                console.error('Lỗi tải danh sách báo cáo:', error);
                document.getElementById('reportsList').innerHTML = `
                    <tr>
                        <td colspan="5" class="text-center text-danger py-4">
                            <i class="fas fa-exclamation-triangle me-2"></i>Lỗi tải danh sách báo cáo
                        </td>
                    </tr>
                `;
            }
        }

        async function downloadReport(filename) {
            // Đã có
            try {
                const downloadLink = document.createElement('a');
                downloadLink.href = `${API_BASE}/download/${filename}`;
                downloadLink.download = filename;
                document.body.appendChild(downloadLink);
                downloadLink.click();
                document.body.removeChild(downloadLink);
            } catch (error) {
                alert('Lỗi tải file: ' + error);
            }
        }

        async function viewReport(filename) {
            // Đã có
            window.open(`${API_BASE}/download/${filename}`, '_blank');
        }

        async function deleteReport(filename) {
            // Đã có
            if (!confirm(`Bạn có chắc muốn xóa báo cáo "${filename}"?`)) {
                return;
            }
            try {
                const response = await axios.delete(`${API_BASE}/reports/${filename}`);
                if (response.data.success) {
                    showAlert('reportsCount', true, 'Đã xóa báo cáo thành công');
                    loadReports();
                } else {
                    showAlert('reportsCount', false, response.data.message);
                }
            } catch (error) {
                showAlert('reportsCount', false, 'Lỗi xóa báo cáo');
            }
        }

        async function clearAllReports() {
            // Đã có
            if (!confirm('Bạn có chắc muốn xóa TẤT CẢ báo cáo? Hành động này không thể hoàn tác!')) {
                return;
            }
            try {
                const response = await axios.delete(`${API_BASE}/reports`);
                if (response.data.success) {
                    showAlert('reportsCount', true, response.data.message);
                    loadReports();
                } else {
                    showAlert('reportsCount', false, response.data.message);
                }
            } catch (error) {
                showAlert('reportsCount', false, 'Lỗi xóa báo cáo');
            }
        }

        // --- HÀM MỚI (Hoàn thiện phần JavaScript bị thiếu) ---

        async function uploadTemplate() {
            const file = document.getElementById('templateFile').files[0];
            const templateResultDiv = document.getElementById('templateResult');
            templateResultDiv.innerHTML = `<div class="alert alert-info mt-2"><i class="fas fa-spinner fa-spin me-2"></i>Đang tải lên...</div>`;
            
            if (!file) {
                showAlert('templateResult', false, 'Vui lòng chọn file template!');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            try {
                const response = await axios.post(`${API_BASE}/upload-template`, formData);
                showAlert('templateResult', response.data.success, response.data.message);
            } catch (error) {
                const errorMessage = error.response ? error.response.data.detail : 'Lỗi tải lên template';
                showAlert('templateResult', false, errorMessage);
            }
        }

        async function uploadLogo() {
            const file = document.getElementById('logoFile').files[0];
            const templateResultDiv = document.getElementById('templateResult');
            templateResultDiv.innerHTML = `<div class="alert alert-info mt-2"><i class="fas fa-spinner fa-spin me-2"></i>Đang tải lên...</div>`;
            
            if (!file) {
                showAlert('templateResult', false, 'Vui lòng chọn file logo!');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            try {
                const response = await axios.post(`${API_BASE}/upload-logo`, formData);
                showAlert('templateResult', response.data.success, response.data.message);
            } catch (error) {
                const errorMessage = error.response ? error.response.data.detail : 'Lỗi tải lên logo';
                showAlert('templateResult', false, errorMessage);
            }
        }

        function showAlert(containerId, success, message) {
            const alertClass = success ? 'alert-success' : 'alert-danger';
            const icon = success ? '✅' : '❌';
            const alertDiv = document.createElement('div');
            alertDiv.className = `alert ${alertClass} alert-dismissible fade show mt-2`;
            alertDiv.innerHTML = `
                ${icon} ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;

            const container = document.getElementById(containerId);
            // Xóa alert cũ
            const oldAlert = container.querySelector('.alert');
            if (oldAlert) {
                oldAlert.remove();
            }
            container.appendChild(alertDiv);
            
            // Tự động ẩn sau 5 giây nếu thành công
            if (success) {
                 setTimeout(() => {
                    if(alertDiv.parentNode) {
                        alertDiv.remove();
                    }
                 }, 5000);
            }
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
