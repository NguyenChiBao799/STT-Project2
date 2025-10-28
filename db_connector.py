# db_connector.py
import time
import random
from typing import Dict, Any, Tuple, Callable

# --- SAFE IMPORT/FALLBACK cho config_db ---
try:
    # Cần DB_MODE_DEFAULT cho giá trị mặc định của __init__
    from config_db import ConfigDB, DB_MODE_DEFAULT
except ImportError:
    class ConfigDB: # Minimal Mock
        MOCK_DATABASE = {}
        INTERACTION_HISTORY = []
        DB_MODE_DEFAULT = "MOCK"
    print("❌ [DB] Lỗi import ConfigDB. Sử dụng ConfigDB Mock cấu trúc.")
    DB_MODE_DEFAULT = "MOCK" # Đảm bảo fallback tồn tại

class CorporateAPIConnector:
    """Kết nối API doanh nghiệp/DB thực tế."""
    # 🔥 FIX: Thêm db_mode vào __init__ với giá trị mặc định
    def __init__(self, log_callback: Callable[[str, str], None], db_mode: str = DB_MODE_DEFAULT):
        self.log = log_callback
        self.db_mode = db_mode # Lưu mode
        self.log(f"🔗 [API/DB] Khởi tạo CorporateAPIConnector (Mode: {self.db_mode}).", color="orange")
        # Khởi tạo kết nối DB thực tế ở đây nếu self.db_mode == "CORPORATE_API"
        # self.connection = self._connect_real_db() if self.db_mode == "CORPORATE_API" else None

    def _connect_real_db(self):
        # Placeholder for real connection logic
        self.log("🔗 [DB] (Simulated) Connecting to real database...", "blue")
        return None # Return None in simulation

    def _simulate_api_call(self, mode: str) -> bool:
        """Giả lập độ trễ API."""
        if mode == "CORPORATE_API": time.sleep(random.uniform(1.0, 2.0))
        else: time.sleep(random.uniform(0.1, 0.3))
        return True

    # --- Các hàm API (Trả về lỗi khi không có dữ liệu/API) ---

    def get_product_price(self, product_name: str, mode: str, **kwargs) -> Tuple[Dict[str, Any], str]: # Thêm **kwargs
        self.log(f"🔗 [API/DB] Tra cứu giá sản phẩm {product_name} (Mode: {mode})...", color="orange")
        self._simulate_api_call(mode)
        # --- LOGIC GỌI API/DB THỰC TẾ ---
        return {"error": "PRODUCT_NOT_FOUND"}, f"Xin lỗi, tôi không có thông tin về giá của sản phẩm **{product_name}**."

    def get_order_status(self, order_id: str, mode: str, **kwargs) -> Tuple[Dict[str, Any], str]: # Thêm **kwargs
        self.log(f"🔗 [API/DB] Tra cứu trạng thái đơn hàng {order_id} (Mode: {mode})...", color="orange")
        self._simulate_api_call(mode)
        # --- LOGIC GỌI API/DB THỰC TẾ ---
        return {"error": "ORDER_NOT_FOUND"}, f"Xin lỗi, tôi không tìm thấy đơn hàng **{order_id}**."

    def place_order(self, product_name: str, color: str, mode: str, **kwargs) -> Tuple[Dict[str, Any], str]: # Thêm **kwargs
        self.log(f"🔗 [API/DB] Đặt hàng {product_name} màu {color} (Mode: {mode})...", color="orange")
        self._simulate_api_call(mode)
        # --- LOGIC GỌI API ĐẶT HÀNG THỰC TẾ ---
        return { "status": "pending_info", "required_field": "phone_number"}, f"Xe **{product_name.capitalize()}** màu **{color}** có sẵn. Vui lòng cung cấp **số điện thoại**."

    def insert_interaction(self, user_input: str, response_text: str, intent: str):
        # Logic ghi log vào DB thực tế
        self.log(f"📝 [DB/History] (Simulated) Ghi lại: Intent='{intent}'.", color="purple")

    # Các hàm khác
    def get_product_features(self, product_name, mode, **kwargs): return {"error": "Not Implemented"}, f"Chức năng tính năng chưa có."
    def get_script_content(self, script_name, **kwargs):
         if script_name == "welcome_script": return {}, "Chào mừng."
         return {"error": "Not Found"}, "Không tìm thấy kịch bản."
    def get_state(self): return {"status": "ok", "db_mode": self.db_mode}