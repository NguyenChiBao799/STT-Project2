# db_connector.py (Integration Layer - Tầng Tích Hợp)

import requests
import json
import time
from typing import List, Dict, Any, Optional, Callable
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
                "price": "12,000,000 VNĐ",
                "discount": "0" 
            }
        self._log(f"❌ [DB Mock] Không tìm thấy dữ liệu sản phẩm SKU: {product_sku}.")
        return None

# ==================== MAIN CLASS (Chọn Real/Mock) ====================
SystemIntegrationManager = MockIntegrationManager