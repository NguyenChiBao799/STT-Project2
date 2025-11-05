# config_db.py
import os
import uuid

try:
    import pyttsx3
except Exception:
    pyttsx3 = None

# ======================================================
# CLASS CẤU HÌNH TỔNG HỢP: ConfigDB
# ======================================================
class ConfigDB:
    # --- API KEYS & MODES ---
    # API Key mặc định, sẽ được ghi đè bằng giá trị từ Frontend (WebRTC)
    API_KEY = os.environ.get("YOUR_API_KEY_ENV_VAR", "MOCK_API_KEY") 
    
    # CHẾ ĐỘ XỬ LÝ (MOCK/LLM/WHISPER/API)
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
    NLU_CONFIDENCE_THRESHOLD = 0.6 
    
    # --- CONFIG AUDIO IO ---
    SAMPLE_RATE = 16000 # 16kHz
    
    # --- CONFIG DIALOG MANAGER ---
    INITIAL_STATE = "START" 
    SCENARIOS_CONFIG = { 
        "rules": [
            {"intent": "chao_hoi", "responses": ["Chào bạn, tôi là trợ lý ảo. Bạn cần hỗ trợ gì?", "Xin chào! Tôi có thể giúp gì cho bạn hôm nay?"]},
            {"intent": "no_match", "response": "Xin lỗi, tôi chưa hiểu rõ ý bạn. Bạn có thể nói rõ hơn không?"}
        ]
    }
    
    # Giả lập dữ liệu DB / State
    STATE_CONFIG = {"START": {"transitions": []}}
    PRIORITY_RULES = []


# ======================================================
# HẰNG SỐ DỰ ÁN (EXPORTING FOR DIRECT IMPORT)
# ======================================================
API_KEY = ConfigDB.API_KEY 
GEMINI_MODEL = ConfigDB.GEMINI_MODEL
LLM_MODE_DEFAULT = ConfigDB.LLM_MODE_DEFAULT 
NLU_MODE_DEFAULT = ConfigDB.NLU_MODE_DEFAULT
DB_MODE_DEFAULT = ConfigDB.DB_MODE_DEFAULT
ASR_MODE_DEFAULT = ConfigDB.ASR_MODE_DEFAULT
TTS_MODE_DEFAULT = ConfigDB.TTS_MODE_DEFAULT
TTS_VOICE_NAME_DEFAULT = ConfigDB.TTS_VOICE_NAME_DEFAULT

NLU_CONFIDENCE_THRESHOLD = ConfigDB.NLU_CONFIDENCE_THRESHOLD
WHISPER_MODEL_NAME = ConfigDB.WHISPER_MODEL_NAME
SAMPLE_RATE = ConfigDB.SAMPLE_RATE

SCENARIOS_CONFIG = ConfigDB.SCENARIOS_CONFIG
INITIAL_STATE = ConfigDB.INITIAL_STATE