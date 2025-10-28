# db_connector.py (Integration Layer - Tầng Tích Hợp)

import requests
import json
import time
from typing import List, Dict, Any, Optional

# --- Cấu hình API và Xác thực ---

# Cấu hình API Nội bộ (Giả định là một dịch vụ Microservice)
INTERNAL_API_BASE_URL = "http://localhost:8080/internal-data"

# Cấu hình API POS/CRM Bên ngoài (Cần OAuth2)
CRM_API_BASE_URL = "https://api.external-crm.com/v1"
CRM_TOKEN_URL = "https://auth.external-crm.com/oauth/token" 
CRM_CLIENT_ID = "YOUR_CRM_CLIENT_ID_HERE"      # ⬅️ Thông tin định danh công khai
CRM_CLIENT_SECRET = "YOUR_CRM_CLIENT_SECRET_HERE" # ⬅️ Thông tin xác thực bí mật

# --- Class Tích Hợp Hệ Thống ---

class SystemIntegrationManager:
    """
    Quản lý kết nối và giao tiếp với các dịch vụ API Nội bộ và Ngoại bộ (POS/CRM).
    Đóng vai trò là Tầng Tích Hợp (Integration Layer) cho ứng dụng Voice AI.
    """
    
    def __init__(self, log_callback: Optional[callable] = None):
        # State để lưu trữ Token CRM và thời gian hết hạn
        self._crm_access_token: Optional[str] = None
        self._token_expiry_time: float = 0
        self._log = log_callback if log_callback else print
        self._session = requests.Session() # Dùng Session để tái sử dụng kết nối

    def _log_error(self, message: str, color: str = "red"):
        """Ghi log an toàn."""
        self._log(f"❌ [INTEGRATION] {message}", color)
        
    # =====================================================
    # === PHẦN 1: QUẢN LÝ XÁC THỰC OAUTH2 (API NGOÀI) ===
    # =====================================================

    def _get_crm_access_token(self) -> Optional[str]:
        """Lấy hoặc làm mới token OAuth2 cho CRM/POS."""
        current_time = time.time()
        # Nếu token còn hiệu lực hơn 60 giây, sử dụng lại
        if self._crm_access_token and self._token_expiry_time > current_time + 60:
            return self._crm_access_token

        self._log("[INTEGRATION] Đang lấy/làm mới CRM Access Token...", "yellow")
        try:
            # Dùng grant_type 'client_credentials'
            auth_data = {
                'grant_type': 'client_credentials',
                'client_id': CRM_CLIENT_ID,
                'client_secret': CRM_CLIENT_SECRET
            }
            # Yêu cầu lấy Token
            response = self._session.post(CRM_TOKEN_URL, data=auth_data, timeout=5)
            response.raise_for_status() # Báo lỗi nếu status code là 4xx hoặc 5xx
            
            token_info = response.json()
            
            self._crm_access_token = token_info['access_token']
            # Thiết lập thời gian hết hạn
            expires_in = token_info.get('expires_in', 3600)
            self._token_expiry_time = current_time + expires_in
            
            self._log("✅ [INTEGRATION] Lấy CRM Token thành công.", "green")
            return self._crm_access_token
        
        except requests.exceptions.RequestException as e:
            self._log_error(f"Lỗi kết nối hoặc xác thực OAuth2: {e}")
            self._crm_access_token = None
            self._token_expiry_time = 0
            return None

    # =====================================================
    # === PHẦN 2: NHẬP API NỘI BỘ (Data từ DB) ===
    # =====================================================

    def get_products(self) -> List[Dict[str, Any]]:
        """Nhập API nội bộ: GET /api/products để lấy danh sách sản phẩm."""
        url = f"{INTERNAL_API_BASE_URL}/api/products"
        try:
            response = self._session.get(url, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self._log_error(f"Lỗi gọi API nội bộ /products: {e}")
            return []

    def post_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Nhập API nội bộ: POST /api/orders để gửi dữ liệu đơn hàng."""
        url = f"{INTERNAL_API_BASE_URL}/api/orders"
        headers = {'Content-Type': 'application/json'}
        try:
            response = self._session.post(url, headers=headers, json=order_data, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self._log_error(f"Lỗi gọi API nội bộ /orders: {e}")
            return {"success": False, "message": "Internal API error."}

    def get_promotions(self) -> List[Dict[str, Any]]:
        """Nhập API nội bộ: GET /api/promotions để lấy danh sách khuyến mãi."""
        url = f"{INTERNAL_API_BASE_URL}/api/promotions"
        try:
            response = self._session.get(url, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self._log_error(f"Lỗi gọi API nội bộ /promotions: {e}")
            return []
            
    # =====================================================
    # === PHẦN 3: NHẬP API POS/CRM BÊN NGOÀI ===
    # =====================================================

    def query_external_customer_data(self, customer_id: str, attempt: int = 1) -> Optional[Dict[str, Any]]:
        """
        Nhập API POS/CRM ngoài (đã xác thực OAuth2) để lấy dữ liệu khách hàng.
        Bao gồm cơ chế tự động làm mới token.
        """
        token = self._get_crm_access_token()
        if not token:
            return None

        url = f"{CRM_API_BASE_URL}/customers/{customer_id}"
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json'
        }

        try:
            response = self._session.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.HTTPError as e:
            if response.status_code == 401 and attempt < 2:
                self._log_error("CRM Token hết hạn (401). Đang thử làm mới và thử lại...", "orange")
                # Xóa token cũ để buộc lấy token mới trong lần gọi sau
                self._crm_access_token = None
                self._token_expiry_time = 0
                # Thử lại
                return self.query_external_customer_data(customer_id, attempt=attempt + 1) 
            
            self._log_error(f"Lỗi HTTP gọi API CRM ({response.status_code}): {e}")
            return None
            
        except requests.exceptions.RequestException as e:
            self._log_error(f"Lỗi kết nối gọi API CRM: {e}")
            return None