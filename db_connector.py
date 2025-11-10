# db_connector.py (Integration Layer - Tầng Tích Hợp)

import requests
import json
import time
import uuid # <-- BỔ SUNG: Dùng để tạo ID định danh cho Log
from typing import List, Dict, Any, Optional, Callable, Literal
from abc import ABC, abstractmethod

# --- Cấu hình API và Xác thực (Dành cho Real Impl.) ---
CRM_API_BASE_URL = "https://api.external-crm.com/v1"

# ==================== BASE INTERFACE ====================
class IDatabaseIntegration(ABC):
    """Interface cho các hệ thống tích hợp (thực hoặc mock)."""
    @abstractmethod
    def query_external_customer_data(self, customer_id: str, attempt: int = 1) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def query_internal_product_data(self, product_sku: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def log_interaction(self, session_id: str, transcript: str, response: str, nlu_result: Dict[str, Any]):
        """
        [YÊU CẦU 6] Ghi log toàn bộ tương tác vào bảng 'interactions'.
        """
        pass

# ==================== IMPLEMENTATION MOCK ====================
class MockIntegrationManager(IDatabaseIntegration):
    """Mock class cho tích hợp hệ thống POS/CRM."""
    def __init__(self, log_callback: Callable): 
        self._log = log_callback
        self._log("⚠️ [DB] Sử dụng SystemIntegrationManager MOCK.")

    def query_external_customer_data(self, customer_id: str, attempt: int = 1) -> Optional[Dict[str, Any]]:
        """Giả lập tra cứu dữ liệu khách hàng."""
        # Giả lập tra cứu thành công cho ID "007"
        if customer_id == "007":
            self._log("✅ [DB Mock] Trả về dữ liệu khách hàng '007' (thành công).")
            return {"customer_name": "Nguyễn Văn A", "last_order": "Đã giao hàng hôm qua"}
        self._log("❌ [DB Mock] Không tìm thấy dữ liệu khách hàng.")
        return None
            
    def query_internal_product_data(self, product_sku: str) -> Optional[Dict[str, Any]]:
        """
        Giả lập trả về dữ liệu sản phẩm, bao gồm giá và khuyến mãi.
        Logic: Nếu có "A" hoặc "B" trong SKU, trả về dữ liệu.
        """
        sku_upper = product_sku.upper().strip()
        if "A" in sku_upper:
            self._log(f"✅ [DB Mock] Trả về dữ liệu sản phẩm '{product_sku}' (thành công).")
            return {
                "product_name": "Sản phẩm A (điện thoại)", 
                "price": "5,000,000 VNĐ",
                "discount": "10" 
            }
        elif "B" in sku_upper:
            self._log(f"✅ [DB Mock] Trả về dữ liệu sản phẩm '{product_sku}' (thành công).")
            return {
                "product_name": "Sản phẩm B (laptop)",
                "price": "25,000,000 VNĐ",
                "discount": "0" 
            }
        self._log(f"❌ [DB Mock] Không tìm thấy dữ liệu sản phẩm '{product_sku}'.")
        return None

    # ==================== PHƯƠNG THỨC MỚI (YÊU CẦU 6) ====================
    def log_interaction(self, session_id: str, transcript: str, response: str, nlu_result: Dict[str, Any]):
        """
        Mô phỏng việc ghi log vào bảng 'interactions' (Yêu cầu 6).
        Dữ liệu này được dùng để huấn luyện mô hình.
        """
        log_entry = {
            "interaction_id": str(uuid.uuid4()), # Ghi log với ID duy nhất
            "session_id": session_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "user_transcript": transcript,
            "bot_response_text": response,
            "nlu_result": json.dumps(nlu_result)
        }
        # In log ra console (mô phỏng thao tác ghi vào DB/Log API)
        self._log(f"📝 [DB Mock] Ghi log tương tác Session ID {session_id} (Intent: {nlu_result.get('intent', 'N/A')}) thành công.", "blue")


# ==================== LỚP DÙNG CHUNG (DB Connector) ===================
class SystemIntegrationManager:
    """Chọn giữa Real và Mock Integration."""
    def __init__(self, mode: Literal['MOCK', 'REAL'], log_callback: Callable):
        self.mode = mode
        if self.mode == 'MOCK':
            self.manager = MockIntegrationManager(log_callback)
        else:
            # Lớp thực tế (Real) cần được triển khai ở đây
            raise NotImplementedError("Chế độ 'REAL' chưa được triển khai.")
            
    # Proxy các phương thức
    def query_external_customer_data(self, *args, **kwargs):
        return self.manager.query_external_customer_data(*args, **kwargs)

    def query_internal_product_data(self, *args, **kwargs):
        return self.manager.query_internal_product_data(*args, **kwargs)

    # Proxy phương thức ghi Log mới
    def log_interaction(self, *args, **kwargs):
        return self.manager.log_interaction(*args, **kwargs)