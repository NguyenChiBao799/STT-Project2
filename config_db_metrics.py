import time
import json
import os

# --- CẤU HÌNH HỆ THỐNG (config_db.py) ---
SAMPLE_RATE = 16000
CHANNELS = 1
AUDIO_FILE = "data/temp_user_audio.wav"
TEMP_TTS_FILE = "data/temp_tts_response.mp3"
LOG_FILE_PATH = "training_log.jsonl"

# --- GIẢ LẬP KẾT NỐI DB/API (db_connector.py) ---
class DBConnector:
    """Giả lập kết nối đến hệ thống POS hoặc Database."""
    def __init__(self, log_callback):
        self.log = log_callback
        
    def get_price(self, product_name):
        """Giả lập truy vấn giá sản phẩm."""
        product_name_lower = product_name.lower()
        self.log(f"🔎 [DB] Đang tra cứu giá cho '{product_name}'...", color="orange")

        if "vision" in product_name_lower:
            price = "32,500,000 VND"
        elif "exciter" in product_name_lower:
            price = "48,000,000 VND"
        else:
            price = "không tìm thấy thông tin"
        
        db_response = {
            "product": product_name,
            "price_found": price
        }
        
        self.log(f"✅ [DB] Phản hồi: {db_response}", color="green")
        return db_response

# --- METRICS (metrics_layer.py) ---
PROMETHEUS_PORT = 8000
APP_SERVICE_NAME = "HybridVoiceBot"

def record_session_start(nlu_mode, db_mode):
    # Giả lập hàm ghi metric (cần thư viện prometheus_client thực tế)
    pass 

def record_session_error(nlu_mode, db_mode):
    # Giả lập hàm ghi metric (cần thư viện prometheus_client thực tế)
    pass

# --- KHỞI TẠO THƯ MỤC CẦN THIẾT ---
if not os.path.exists("data"):
    os.makedirs("data")