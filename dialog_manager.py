# dialog_manager.py
import time
import uuid
import random
import os
import threading
import traceback
from typing import Dict, Any, Tuple, List, Optional, Callable
import wave

# ----------------------------
# Safe import / config handling
# ----------------------------
# Khai báo các biến Fallback TRƯỚC khối try
_INITIAL_STATE = "START"
_NLU_CONFIDENCE_THRESHOLD = 0.7
_DB_MODE_DEFAULT = "MOCK"
_TTS_MODE_DEFAULT = "MOCK"
_LLM_MODE_DEFAULT = "API"
_ASR_MODE_DEFAULT = "WHISPER"
_NLU_MODE_DEFAULT = "MOCK"
_SCENARIOS_CONFIG = {"rules": []}
_TEMP_TTS_FILE = "tts_fallback.wav"
_AUDIO_FILE = "asr_input.wav"
_TTS_VOICE_NAME_DEFAULT = "vi"
_SCENARIOS_CONFIG = {"intents": [
    {"intent_name": "query_weather", "responses": ["Thời tiết tại Hà Nội hôm nay là 25 độ, có mưa rào. (Fallback)"], "products": []}
]}
SCENARIOS_CONFIG = _SCENARIOS_CONFIG

# Thử import các hằng số từ config_db và thư viện Whisper
try:
    from config_db import (
        ASR_MODE_DEFAULT, WHISPER_MODEL_NAME, 
        SAMPLE_RATE, CHANNELS,
        SCENARIOS_CONFIG # ✅ NEW: Import SCENARIOS_CONFIG
    )
    import whisper
    WHISPER_AVAILABLE = True
except ImportError as e:
    whisper = None
    WHISPER_AVAILABLE = False
    # Fallback configs nếu import lỗi
    ASR_MODE_DEFAULT = _ASR_MODE_DEFAULT
    WHISPER_MODEL_NAME = "small" 
    SAMPLE_RATE = 16000 # Fallback 
    CHANNELS = 1 # Fallback
    print(f"⚠️ [IMPORT ERROR] Không thể import thư viện/cấu hình: {e}. Whisper ASR sẽ dùng Mock.")

# ----------------------------
# MOCK & THỰC TẾ CLASSES
# ----------------------------

class _MockNLUASR:
# ... (Giữ nguyên)
    def __init__(self, log_callback): self.log = log_callback
    def process(self, audio_path):
        self.log("🎤 [Mock] Xử lý ASR/NLU...", "yellow")
        time.sleep(1) 
        return {"text": "hôm nay thời tiết thế nào", "intent": "query_weather", "entities": {}, "confidence": 0.9}
    def terminate(self): 
        self.log("🗑️ [Mock] NLU/ASR đã terminate.", "orange")

class WhisperASR:
# ... (Giữ nguyên)
    def __init__(self, log_callback, model_name: str):
        self.log = log_callback
        self.model_name = model_name
        self._is_ready = False
        self.model = None

        if not WHISPER_AVAILABLE:
            self.log("❌ [WHISPER] Thư viện Whisper không có. ASR không thể hoạt động.", "red")
            return

        try:
            self.log(f"🧠 [WHISPER] Đang tải mô hình: {self.model_name}...", "yellow")
            self.model = whisper.load_model(self.model_name)
            self._is_ready = True
            self.log(f"✅ [WHISPER] Mô hình '{self.model_name}' đã tải thành công.", "green")
        except Exception as e:
            self.log(f"❌ [WHISPER] Lỗi tải mô hình {self.model_name}: {e}", "red")

    def is_ready(self):
        return self._is_ready

    def process(self, audio_path: str) -> Dict[str, Any]:
        if not self.is_ready():
             self.log("❌ [WHISPER] Mô hình chưa sẵn sàng.", "red")
             return {"text": "", "intent": "error", "entities": {}, "confidence": 0.0}

        self.log(f"🎤 [WHISPER] Đang chuyển đổi STT cho {os.path.basename(audio_path)}...", "blue")
        start_time = time.time()
        
        try:
            result = self.model.transcribe(audio_path, language="vi", fp16=False)
            text = result["text"].strip()
            
            self.log(f"📝 [WHISPER] ASR Output: '{text}' ({time.time() - start_time:.2f}s)", "cyan")
            
            intent = "query_weather" if len(text) > 3 else "no_speech"

            return {"text": text, "intent": intent, "entities": {}, "confidence": 0.9}
        except Exception as e:
            self.log(f"❌ [WHISPER] Lỗi xử lý STT: {e}", "red") 
            return {"text": "", "intent": "error", "entities": {}, "confidence": 0.0}

    def terminate(self):
        self.model = None
        self._is_ready = False
        self.log("🗑️ [WHISPER] Mô hình đã được dỡ bỏ.", "orange")


class _MockResponseGenerator:
    def __init__(self, log_callback): 
        self.log = log_callback
        # ✅ NEW: Lấy SCENARIOS_CONFIG từ global (đã được import)
        self.scenarios = globals().get('SCENARIOS_CONFIG', _SCENARIOS_CONFIG) 
        
    def generate(self, nlu_result, current_state):
        self.log("💬 [Mock] Tạo phản hồi...", "yellow")
        intent = nlu_result['intent']
        
        # ✅ NEW: Tìm và chọn phản hồi dựa trên Intent
        found_scenario = next((item for item in self.scenarios['intents'] if item['intent_name'] == intent), None)
        
        if found_scenario and found_scenario['responses']:
            response = random.choice(found_scenario['responses'])
        elif intent == "no_speech":
            response = "Xin lỗi, tôi không nghe rõ. Bạn có thể nói lại không?"
        else:
            response = f"Tôi không tìm thấy kịch bản cho ý định '{intent}'. (Fallback response: Thời tiết tại Hà Nội hôm nay là 25 độ, có mưa rào.)"
        
        return response
        
    def tts_processor(self, response_text):
        """
        Tạo file WAV giả lập hợp lệ (có header và data câm) để tránh lỗi Playback.
        """
        tts_file = f"temp/tts_{uuid.uuid4().hex[:6]}.wav" 
        
        try:
            sample_width = 2 # 16-bit audio
            mock_duration_seconds = 0.5 
            
            # Sử dụng các hằng số
            frame_rate = SAMPLE_RATE 
            channels = CHANNELS
            
            # Tính toán số lượng frames và tạo dữ liệu câm (bytes 0)
            num_frames = int(frame_rate * mock_duration_seconds)
            silent_data = b'\x00' * num_frames * channels * sample_width

            with wave.open(tts_file, 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(sample_width)
                wf.setframerate(frame_rate)
                wf.writeframes(silent_data)
                
            self.log(f"💾 [Mock TTS] Created valid silent WAV file: {os.path.basename(tts_file)}", "green")
            return tts_file
            
        except Exception as e:
             self.log(f"❌ [Mock TTS] Lỗi khi tạo file WAV giả lập: {e}", "red")
             return None 

    def terminate(self): 
        self.log("🗑️ [Mock] Response Generator/LLM đã terminate.", "orange")


# ----------------------------
# DIALOG MANAGER CLASS
# ----------------------------
class DialogManager:
# ... (Phần còn lại giữ nguyên)
    def __init__(self, log_callback: Callable, api_key: str, voice_manager=None, config: Optional[Dict] = None):
        self.log = log_callback
        self.api_key = api_key
        self.voice_manager = voice_manager
        self.config = config or {}
        self.current_state = _INITIAL_STATE
        self._is_ready = False
        self._initial_error = ""

        try:
            # Khởi tạo ASR/NLU Module
            if ASR_MODE_DEFAULT == "WHISPER" and WHISPER_AVAILABLE:
                self.nlu_asr = WhisperASR(self.log, WHISPER_MODEL_NAME)
                if not self.nlu_asr.is_ready():
                    self.log("⚠️ [DM] Whisper ASR lỗi/không sẵn sàng. Dùng Mock ASR/NLU.", "orange")
                    self.nlu_asr = _MockNLUASR(self.log)
            else:
                self.nlu_asr = _MockNLUASR(self.log)
            
            # Khởi tạo Response Generator
            self.response_generator = _MockResponseGenerator(self.log)
            
            self._is_ready = self._check_readiness()
            
            if self._is_ready:
                self.log(f"🤖 [DM] DM khởi tạo thành công. API Key: {self.api_key[:5]}...", "green")
            else:
                self.log(f"❌ [DM] DM khởi tạo lỗi. Lỗi: {self._initial_error}", "red")

        except Exception as e:
            self._initial_error = f"Lỗi khởi tạo module: {e}"
            self.log(f"❌ [DM] Lỗi khởi tạo DialogManager: {self._initial_error}", "red")

    def _check_readiness(self) -> bool:
        if not self.api_key or len(self.api_key) < 10:
            self._initial_error = "API Key không hợp lệ."
            return False
            
        return (self.nlu_asr.is_ready() if hasattr(self.nlu_asr, 'is_ready') else True) and True

    def is_ready(self) -> bool:
        return self._is_ready

    def get_initial_error(self) -> str:
        return self._initial_error

    def terminate(self):
        self.log("🗑️ [DM] DialogManager đang dọn dẹp tài nguyên...", "orange")
        
        if self.nlu_asr and hasattr(self.nlu_asr, 'terminate'):
            try: self.nlu_asr.terminate()
            except Exception as e: self.log(f"⚠️ [DM] Lỗi khi terminate NLU/ASR: {e}", "red")

        if self.response_generator and hasattr(self.response_generator, 'terminate'):
            try: self.response_generator.terminate()
            except Exception as e: self.log(f"⚠️ [DM] Lỗi khi terminate Response Generator: {e}", "red")
                
        self._is_ready = False
        self.log("🗑️ [DM] DialogManager đã terminate hoàn tất.", "green")

    def process_turn(self, nlu_result: Dict[str, Any]) -> Dict[str, Any]:
        
        user_input_asr = nlu_result.get("text", "")
        intent = nlu_result.get("intent", "no_intent")
        
        if intent != "no_speech":
             self.current_state = "PROCESSING" 

        response_text = "Xin lỗi, tôi không hiểu ý bạn."
        try:
            if hasattr(self.response_generator, 'generate'):
                 response_text = self.response_generator.generate(nlu_result, self.current_state)
        except Exception as e:
             self.log(f"❌ [DM] Lỗi Response Generation: {e}", "red")
             response_text = "Đã xảy ra lỗi trong quá trình xử lý phản hồi."

        tts_path = None
        if hasattr(self.response_generator, 'tts_processor'):
            try:
                tts_path = self.response_generator.tts_processor(response_text)
                self.log(f"🎵 [TTS] File audio TTS: {tts_path or 'None'}", "green")
            except Exception as e: self.log(f"❌ [DM] Lỗi TTS Processor: {e}", "red")

        db_info = {"nlu_result": nlu_result}
        return {"response_text": response_text, "response_audio_path": tts_path, "current_state": self.current_state, "db_info": db_info, "user_input_asr": user_input_asr}

    def process_audio_file(self, audio_path: Optional[str]) -> Dict[str, Any]:
        if not self.is_ready():
            return {"response_text": "Lỗi hệ thống.", "current_state": "ERROR", "db_info": {"error": "DM not ready", "detail": self.get_initial_error()}, "user_input_asr": ""}

        nlu_result = {"text": "", "intent": "no_speech", "entities": {}, "confidence": 0.0}

        if self.nlu_asr:
            try:
                nlu_result = self.nlu_asr.process(audio_path)
            except Exception as e:
                self.log(f"❌ [NLU/ASR] Lỗi khi gọi process: {e}", "red")
                nlu_result["error"] = str(e)
                
        return self.process_turn(nlu_result)