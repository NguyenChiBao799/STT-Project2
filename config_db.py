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
    
    # CHẾ ĐỘ XỬ LÝ
    NLU_MODE_DEFAULT = "MOCK"      
    ASR_MODE_DEFAULT = "WHISPER"   
    LLM_MODE_DEFAULT = "MOCK"   
    DB_MODE_DEFAULT = "MOCK"
    TTS_MODE_DEFAULT = "MOCK"     
    
    # Cài đặt LLM
    GEMINI_MODEL = "gemini-2.5-flash" 
    
    TTS_VOICE_NAME_DEFAULT = "vi-VN-Standard-A"

    # --- CONFIG ASR/NLU ---
    WHISPER_MODEL_NAME = "small"
    NLU_CONFIDENCE_THRESHOLD = 0.6 # ✅ HẰNG SỐ CẦN THIẾT
    
    # --- CONFIG AUDIO IO ---
    SAMPLE_RATE = 16000 # 16kHz
    
    # --- CONFIG DIALOG MANAGER ---
    INITIAL_STATE = "START" 
    SCENARIOS_CONFIG = { 
        "rules": [
            {"intent": "chao_hoi", "response": "Chào bạn, tôi là trợ lý ảo. Bạn cần hỗ trợ gì?"}
        ]
    }
    
    # Giả lập dữ liệu DB / State
    STATE_CONFIG = {"START": {"transitions": []}}
    PRIORITY_RULES = []


# ======================================================
# HẰNG SỐ DỰ ÁN (EXPORTING FOR DIRECT IMPORT)
# ======================================================
# Sử dụng ConfigDB để export TẤT CẢ các hằng số cần thiết
API_KEY = ConfigDB.API_KEY 
GEMINI_MODEL = ConfigDB.GEMINI_MODEL
LLM_MODE_DEFAULT = ConfigDB.LLM_MODE_DEFAULT 
NLU_MODE_DEFAULT = ConfigDB.NLU_MODE_DEFAULT
DB_MODE_DEFAULT = ConfigDB.DB_MODE_DEFAULT
ASR_MODE_DEFAULT = ConfigDB.ASR_MODE_DEFAULT
TTS_MODE_DEFAULT = ConfigDB.TTS_MODE_DEFAULT
TTS_VOICE_NAME_DEFAULT = ConfigDB.TTS_VOICE_NAME_DEFAULT

# ✅ FIX LỖI: Export NLU_CONFIDENCE_THRESHOLD
NLU_CONFIDENCE_THRESHOLD = ConfigDB.NLU_CONFIDENCE_THRESHOLD

SCENARIOS_CONFIG = ConfigDB.SCENARIOS_CONFIG
STATE_CONFIG = ConfigDB.STATE_CONFIG
PRIORITY_RULES = ConfigDB.PRIORITY_RULES
INITIAL_STATE = ConfigDB.INITIAL_STATE 

# Lists for UI
LLM_MODES = ["API", "MOCK"]
NLU_MODES = ["LLM", "LOCAL", "MOCK"]
DB_MODES = ["CORPORATE_..."]