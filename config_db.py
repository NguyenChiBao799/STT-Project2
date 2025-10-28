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
    NLU_MODE_DEFAULT = "LLM"      
    ASR_MODE_DEFAULT = "WHISPER"  
    LLM_MODE_DEFAULT = "GEMINI"   
    DB_MODE_DEFAULT = "CORPORATE_API"
    TTS_MODE_DEFAULT = "MOCK"     
    TTS_VOICE_NAME_DEFAULT = "vi-VN-Standard-A"

    # --- CONFIG ASR/NLU ---
    WHISPER_MODEL_NAME = "small" 
    NLU_CONFIDENCE_THRESHOLD = 0.6 
    
    # --- CONFIG AUDIO IO ---
    SAMPLE_RATE = 16000     
    CHANNELS = 1
    CHUNK_SIZE = 1024       

    # --- FILE PATHS ---
    AUDIO_FILE = "temp/asr_input.wav"
    TEMP_TTS_FILE = "temp/tts_response.wav" 
    LOG_FILE_PATH = "logs/application.log"
    CONFIG_FILE = "config.json"

    # --- DIALOG & STATE ---
    INITIAL_STATE = "START"
    PROMETHEUS_PORT = 8000
    
    # --- MOCK DATA FOR STATS/SALES ---
    MOCK_STATS = {
        "total_requests": 1540,
        "conversion_rate": 0.125,
        "products_mentioned": {"Product A (Phone)": 320, "Product B (Laptop)": 250, "Product C (Service)": 180, "Product D (Accessory)": 100},
        "sales_data": [
            {"date": "2025-10-01", "sales": 15000000, "conversion_rate": 0.10},
            {"date": "2025-10-02", "sales": 18000000, "conversion_rate": 0.12},
            {"date": "2025-10-03", "sales": 14000000, "conversion_rate": 0.09}
        ]
    }
    
    # --- SCENARIO CONFIGS (UPDATED FOR CRUD) ---
    SCENARIOS_CONFIG = {
        "intents": [
            {"intent_name": "query_weather", "responses": ["Thời tiết tại Hà Nội hôm nay là 25 độ, có mưa rào."], "products": []},
            {"intent_name": "order_product", "responses": ["Xin quý khách cho biết mã sản phẩm muốn đặt. Sản phẩm A và B đang được khuyến mãi."], "products": ["Product A (Phone)", "Product B (Laptop)"]},
            {"intent_name": "query_promotion", "responses": ["Khuyến mãi tháng này là giảm 20% cho Product C."], "products": ["Product C (Service)"]}
        ]
    }
    
    STATE_CONFIG = {"START": {"transitions": []}}
    PRIORITY_RULES = []


# ======================================================
# HẰNG SỐ DỰ ÁN (EXPORTING FOR DIRECT IMPORT)
# ======================================================
# ... (Phần export giữ nguyên)
API_KEY = ConfigDB.API_KEY 
LLM_MODE_DEFAULT = ConfigDB.LLM_MODE_DEFAULT 
NLU_MODE_DEFAULT = ConfigDB.NLU_MODE_DEFAULT
DB_MODE_DEFAULT = ConfigDB.DB_MODE_DEFAULT
ASR_MODE_DEFAULT = ConfigDB.ASR_MODE_DEFAULT
TTS_MODE_DEFAULT = ConfigDB.TTS_MODE_DEFAULT
TTS_VOICE_NAME_DEFAULT = ConfigDB.TTS_VOICE_NAME_DEFAULT

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
PROMETHEUS_PORT = ConfigDB.PROMETHEUS_PORT
CONFIG_FILE = ConfigDB.CONFIG_FILE

# Audio IO Configs
SAMPLE_RATE = ConfigDB.SAMPLE_RATE
CHANNELS = ConfigDB.CHANNELS
CHUNK_SIZE = ConfigDB.CHUNK_SIZE

# Dialog/State
INITIAL_STATE = ConfigDB.INITIAL_STATE 
SCENARIOS_CONFIG = ConfigDB.SCENARIOS_CONFIG # ✅ EXPORT MỚI
STATE_CONFIG = ConfigDB.STATE_CONFIG
PRIORITY_RULES = ConfigDB.PRIORITY_RULES

# MOCK STATS
MOCK_STATS = ConfigDB.MOCK_STATS # ✅ EXPORT MỚI