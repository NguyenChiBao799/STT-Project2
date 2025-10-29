# config_db.py
import os
import uuid
# Optional imports used for TTS-check
try:
    import pyttsx3
except Exception:
    pyttsx3 = None

# ======================================================
# CLASS CẤU HÌNH TỔNG HỢP: ConfigDB
# ======================================================
class ConfigDB:
    # --- API KEYS & MODES ---
    API_KEY = os.environ.get("YOUR_API_KEY_ENV_VAR", "MOCK_API_KEY") 
    
    # CHẾ ĐỘ XỬ LÝ (ĐÃ CẬP NHẬT ASR MODE sang WHISPER)
    NLU_MODE_DEFAULT = "MOCK"      
    ASR_MODE_DEFAULT = "WHISPER"   
    LLM_MODE_DEFAULT = "MOCK"   
    DB_MODE_DEFAULT = "MOCK"
    TTS_MODE_DEFAULT = "MOCK"     
    
    # Cài đặt LLM
    GEMINI_MODEL = "gemini-2.5-flash" # ⬅️ Cần export
    
    TTS_VOICE_NAME_DEFAULT = "vi-VN-Standard-A"

    # --- CONFIG ASR/NLU ---
    WHISPER_MODEL_NAME = "small" # ⬅️ Mô hình 'small' theo yêu cầu.
    NLU_CONFIDENCE_THRESHOLD = 0.6 
    
    # --- CONFIG AUDIO IO ---
    SAMPLE_RATE = 16000     
    CHANNELS = 1
    CHUNK_SIZE = 1024       

    # --- FILE PATHS & PORTS ---
    AUDIO_FILE = "temp/asr_input.wav"
    TEMP_TTS_FILE = "temp/tts_response.wav" 
    LOG_FILE_PATH = "logs/app_log.txt"
    PROMETHEUS_PORT = 8000 

    # --- CONFIG SCENARIOS (Dữ liệu Mock/Template) ---
    SCENARIOS_CONFIG = {
        "intents": [
            {"intent_name": "query_order", "responses": ["Đã tìm thấy yêu cầu đặt đơn hàng. Bạn muốn sản phẩm nào?"], "products": []},
            {"intent_name": "query_weather", "responses": ["Thời tiết tại Hà Nội hôm nay là 25 độ, có mưa rào."], "products": []}
        ],
        "products": [
            {"name": "Sản phẩm A", "id": "A123", "price": "100.000 VNĐ"},
        ]
    }
    
    STATE_CONFIG = {"START": {"transitions": []}}
    PRIORITY_RULES = []


# ======================================================
# HẰNG SỐ DỰ ÁN (EXPORTING FOR DIRECT IMPORT)
# ======================================================
# Sử dụng ConfigDB để export các hằng số
API_KEY = ConfigDB.API_KEY 
GEMINI_MODEL = ConfigDB.GEMINI_MODEL # ⬅️ ĐÃ THÊM: Export GEMINI_MODEL
LLM_MODE_DEFAULT = ConfigDB.LLM_MODE_DEFAULT 
NLU_MODE_DEFAULT = ConfigDB.NLU_MODE_DEFAULT
DB_MODE_DEFAULT = ConfigDB.DB_MODE_DEFAULT
ASR_MODE_DEFAULT = ConfigDB.ASR_MODE_DEFAULT
TTS_MODE_DEFAULT = ConfigDB.TTS_MODE_DEFAULT
TTS_VOICE_NAME_DEFAULT = ConfigDB.TTS_VOICE_NAME_DEFAULT

# FIX LỖI IMPORT: Export STATE_CONFIG, PRIORITY_RULES và SCENARIOS_CONFIG
SCENARIOS_CONFIG = ConfigDB.SCENARIOS_CONFIG
STATE_CONFIG = ConfigDB.STATE_CONFIG
PRIORITY_RULES = ConfigDB.PRIORITY_RULES

# Lists for UI
LLM_MODES = ["API", "MOCK"]
NLU_MODES = ["LLM", "LOCAL", "MOCK"]
DB_MODES = ["CORPORATE_API", "MOCK"]
ASR_MODES = ["WHISPER", "SR_GOOGLE", "MOCK"]

# Paths & Thresholds
AUDIO_FILE = ConfigDB.AUDIO_FILE
TEMP_TTS_FILE = ConfigDB.TEMP_TTS_FILE
LOG_FILE_PATH = ConfigDB.LOG_FILE_PATH
NLU_CONFIDENCE_THRESHOLD = ConfigDB.NLU_CONFIDENCE_THRESHOLD
WHISPER_MODEL_NAME = ConfigDB.WHISPER_MODEL_NAME
SAMPLE_RATE = ConfigDB.SAMPLE_RATE
CHANNELS = ConfigDB.CHANNELS
CHUNK_SIZE = ConfigDB.CHUNK_SIZE
PROMETHEUS_PORT = ConfigDB.PROMETHEUS_PORT