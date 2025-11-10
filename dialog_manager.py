# dialog_manager.py
import time
import uuid
import random
import os
import threading
import traceback
from typing import Dict, Any, Tuple, List, Optional, Callable, Literal
import wave 

# ----------------------------
# Safe import / config handling
# ----------------------------
_FALLBACK_API_KEY = "MOCK_API_KEY"
_FALLBACK_CONFIG = {"rules": []}

# =====================================================
# MOCK NLU (ĐỊNH NGHĨA TRƯỚC HẾT để dùng làm FALLBACK)
# =====================================================
class NLUModule:
    """Mock NLU Module để tránh lỗi NameError khi import thất bại."""
    def __init__(self, mode: str, api_key: str, log_callback: Callable):
        self.mode = mode
        self.log = log_callback
        self.log(f"⚠️ [NLU] Sử dụng NLU Module MOCK (fallback).", "orange")
        
    def run_nlu(self, text: str) -> Dict[str, Any]:
         if "chào" in text.lower():
             return {"intent": "chao_hoi", "entities": {"chao": "xin chào"}, "confidence": 0.95}
         return {"intent": "no_match", "entities": {}, "confidence": 0.1}

# =====================================================
# MOCK INTENT WHITELIST (ĐỊNH NGHĨA TRƯỚC HẾT)
# =====================================================
class IntentWhitelist:
    def __init__(self, log_callback: Callable): 
        self.log = log_callback
        self.log(f"⚠️ [Whitelist] Sử dụng IntentWhitelist MOCK.", "orange")
    def is_intent_supported(self, intent: str) -> bool: return True
    def get_unsupported_response(self) -> str: return "Lỗi: Intent Whitelist không hoạt động (Mock)."


try:
    from config_db import (
        NLU_CONFIDENCE_THRESHOLD, NLU_MODE_DEFAULT, 
        DB_MODE_DEFAULT, TTS_MODE_DEFAULT, LLM_MODE_DEFAULT, 
        API_KEY as CONFIG_API_KEY, SCENARIOS_CONFIG, INITIAL_STATE, GEMINI_MODEL 
    )
    from response_generator import ResponseGenerator
    from db_connector import SystemIntegrationManager 
    # 🚨 FIX: Thực hiện import NLUModule và IntentWhitelist TẠI ĐÂY
    from nlu_module import NLUModule 
    from intent_whitelist import IntentWhitelist 

except ImportError as e:
    class DefaultConfig:
        NLU_CONFIDENCE_THRESHOLD = 0.6
        NLU_MODE_DEFAULT = "MOCK"
        DB_MODE_DEFAULT = "MOCK"
        TTS_MODE_DEFAULT = "MOCK"
        LLM_MODE_DEFAULT = "MOCK"
        API_KEY = _FALLBACK_API_KEY
        SCENARIOS_CONFIG = _FALLBACK_CONFIG
        INITIAL_STATE = "START"
        GEMINI_MODEL = "gemini-2.5-flash"
    globals().update(DefaultConfig.__dict__)

    # =====================================================
    # MOCK RESPONSE GENERATOR (Giữ nguyên phần fix lỗi cũ)
    # =====================================================
    class ResponseGenerator:
        """Mock Response Generator để tránh lỗi TypeError khi import thất bại."""
        def __init__(self, log_callback: Callable, config: Dict[str, Any], llm_mode: str, tts_mode: str, db_mode: str, api_key: str): 
             self.log = log_callback
             self.log(f"⚠️ [RG Fallback] Sử dụng Response Generator Mock (vì lỗi import).", "orange")
             class MockTTSClient:
                 def synthesize_stream(self, text: str):
                      async def mock_stream(): 
                           yield b'MOCK_AUDIO_CHUNK' 
                      return mock_stream()
             self.tts_client = MockTTSClient() 
             self.api_key_var = threading.local() 
             self.api_key_var.value = api_key

        def generate_response(
            self,
            user_text: str,
            intent: str,
            entities: Dict[str, Any],
            db_result: Dict[str, Any],
            current_state: str,
            history: List[Dict[str, str]] = []
        ) -> str:
            """Trả về phản hồi mock đơn giản."""
            return f"Phản hồi Mock cho intent: {intent}. (Sử dụng chế độ Fallback)"

    # =====================================================
    # MOCK DB INTEGRATION
    # =====================================================
    class SystemIntegrationManager:
        def __init__(self, db_mode: str, log_callback: Callable): 
            self._log = log_callback
            self._log(f"⚠️ [DB] Sử dụng SystemIntegrationManager MOCK (vì lỗi import).")
            
        def query_data(self, intent: str, entities: Dict[str, Any]) -> Dict[str, Any]:
            return {"customer_data": None, "product_data": None}

    print(f"❌ [DM] LỖI IMPORT CONFIG/MODULE: {e}. Đang dùng chế độ Fallback/Mock.")
    
# NLUModule và IntentWhitelist đã được định nghĩa ở trên (Mock) hoặc được import thành công trong khối try.

# =====================================================
# HẰNG SỐ CỦA DIALOG MANAGER
# =====================================================
INITIAL_STATE = globals().get('INITIAL_STATE', 'START') 

# =====================================================
# DIALOG MANAGER (TRUNG TÂM XỬ LÝ)
# =====================================================

class DialogManager:
    """
    Xử lý Luồng hội thoại.
    Tích hợp DBConnector, NLU và Response Generator.
    """
    def __init__(self, log_callback: Optional[Callable] = None, mode: str = "RTC", api_key: str = ""):
        self.session_id = str(uuid.uuid4())
        self.mode = mode
        self.log = log_callback or print
        self.api_key = api_key
        self.current_state = INITIAL_STATE # Start state machine
        self.tts_mode = globals().get('TTS_MODE_DEFAULT', 'MOCK') # Chế độ TTS mặc định
        
        # Khả năng ghi nhớ hội thoại (Conversation History)
        self.history: List[Dict[str, str]] = [] 
        
        # 1. Khởi tạo DB Manager
        self.db_manager = SystemIntegrationManager(globals().get('DB_MODE_DEFAULT', 'MOCK'), self.log)
        
        # 2. Khởi tạo Response Generator
        self.response_generator = ResponseGenerator(
            log_callback=self.log,
            config=globals().get('SCENARIOS_CONFIG', _FALLBACK_CONFIG),
            llm_mode=globals().get('LLM_MODE_DEFAULT', 'MOCK'),
            tts_mode=self.tts_mode,
            db_mode=globals().get('DB_MODE_DEFAULT', 'MOCK'),
            api_key=globals().get('CONFIG_API_KEY', _FALLBACK_API_KEY)
        ) 
        
        # 3. Khởi tạo Intent Whitelist (Đã được đảm bảo là lớp gốc hoặc Mock)
        self.intent_whitelist = IntentWhitelist(self.log)

        self._load_configs()
        # 4. Khởi tạo NLU Module (Đã được đảm bảo là lớp gốc hoặc Mock)
        self.nlu = NLUModule(mode=globals().get('NLU_MODE_DEFAULT', 'MOCK'), api_key=api_key or globals().get('CONFIG_API_KEY', _FALLBACK_API_KEY), log_callback=self.log)

    def _load_configs(self):
        # Hàm giả lập/tải cấu hình, hiện tại đã dùng globals() để lấy từ config_db hoặc DefaultConfig
        self.log("⚙️ [DM] Đã tải xong cấu hình. State ban đầu: " + self.current_state, "blue")

    def _run_nlu_mock(self, text: str) -> Dict[str, Any]:
        """Chạy NLU module (có thể là mock hoặc real)"""
        return self.nlu.run_nlu(text)

    def _query_db(self, user_input_asr: str, nlu_result: Dict[str, Any]) -> Dict[str, Any]:
        """Tra cứu DB/System dựa trên kết quả NLU."""
        self.log(f"🔎 [DB] Tra cứu DB với intent: {nlu_result['intent']}", "yellow")
        
        # Thay thế bằng logic tra cứu thực tế trong SystemIntegrationManager
        db_result = self.db_manager.query_data(nlu_result["intent"], nlu_result["entities"])

        self.log(f"✅ [DB] Kết quả tra cứu: {db_result}", "yellow")
        return db_result

    def _update_state(self, intent: str, nlu_result: Dict[str, Any], current_state: str) -> str:
        """Cập nhật state machine."""
        # Logic cập nhật state đơn giản/mock
        new_state = current_state
        if intent == "chao_hoi":
            new_state = "GREETED"
        elif intent == "no_match" or intent == "fallback_error":
            # Không thay đổi state nếu là fallback, trừ khi có logic đặc biệt
            pass 
        self.log(f"🔄 [State] Cập nhật state: {current_state} -> {new_state}", "cyan")
        return new_state

    def _handle_low_confidence_or_no_speech(self, user_input_asr: str, confidence: float) -> Dict[str, Any]:
        """Xử lý khi ASR không có tiếng nói hoặc NLU confidence thấp."""
        
        # 1. Cập nhật state về No Match
        self.current_state = self._update_state("no_match", {}, self.current_state)
        
        if user_input_asr == "[NO SPEECH DETECTED]":
            self.log("🔇 [NLU] Không phát hiện tiếng nói. Trả về phản hồi tĩnh.", "orange")
            response_text = "Tôi không nghe rõ bạn nói gì. Bạn có thể nói lại không?"
        else:
            self.log(f"⚠️ [NLU] Confidence thấp ({confidence:.2f}). Trả về phản hồi tĩnh.", "orange")
            response_text = "Xin lỗi, tôi chưa hiểu rõ ý bạn. Bạn có thể nói rõ hơn không?"

        # 2. Tạo mock nlu result
        nlu_result: Dict[str, Any] = {"intent": "low_confidence_or_no_speech", "entities": {}, "confidence": confidence}

        # 3. Log và trả về
        return self._log_and_return(time.time(), response_text, user_input_asr, nlu_result)


    def _log_and_return(self, start_time: float, response_text: str, user_input_asr: str, nlu_result: Dict[str, Any]) -> Dict[str, Any]:
        """Hàm hỗ trợ để Ghi Log, ghi nhớ và định dạng kết quả trả về."""
        end_time = time.time()
        
        # Ghi nhớ cuộc hội thoại vào history
        self.history.append({"user": user_input_asr, "bot": response_text})
        
        latency = end_time - start_time
        log_message = (
            f"⚡️ [DM] Hoàn tất phiên ({latency:.2f}s) | Intent: {nlu_result['intent']} | State: {self.current_state}\n"
            f"       Lịch sử: {len(self.history)} lượt | ASR: '{user_input_asr[:50]}...' | BOT: '{response_text[:50]}...'"
        )
        self.log(log_message, "green")
        
        return {
            "response_text": response_text,
            "tts_mode": self.tts_mode,
            "latency": latency,
            "full_history_len": len(self.history)
        }


    def _process_and_update_context(self, user_input_asr: str) -> Dict[str, Any]:
        """Luồng xử lý chính: ASR -> NLU -> DB/State -> Response."""
        start_time = time.time()
        response_text = ""
        nlu_result: Dict[str, Any] = {"intent": "fallback_error", "entities": {}, "confidence": 0.0}

        if user_input_asr == "[NO SPEECH DETECTED]":
             return self._handle_low_confidence_or_no_speech(user_input_asr, 0.0)

        try:
            # 1. NLU Module
            nlu_result = self._run_nlu_mock(user_input_asr)
            current_intent = nlu_result["intent"]
            
            # 2. Xử lý Fallback/Low Confidence
            if nlu_result.get("confidence", 0.0) < globals().get('NLU_CONFIDENCE_THRESHOLD', 0.6):
                return self._handle_low_confidence_or_no_speech(user_input_asr, nlu_result.get("confidence", 0.0))
            
            # 3. KIỂM TRA INTENT WHITELIST
            if not self.intent_whitelist.is_intent_supported(current_intent):
                response_text = self.intent_whitelist.get_unsupported_response()
                nlu_result["intent"] = "unsupported_topic_block"
                nlu_result["confidence"] = 1.0 
                self.log(f"🛑 [Whitelist] Intent '{current_intent}' không được hỗ trợ. Chặn xử lý nghiệp vụ.", "red")
                return self._log_and_return(start_time, response_text, user_input_asr, nlu_result)


            # 4. Tra cứu DB và State Update
            db_query_result = self._query_db(user_input_asr, nlu_result)
            self.current_state = self._update_state(current_intent, nlu_result, self.current_state)

            # 5. Response Generation
            response_text = "Đã xảy ra lỗi trong quá trình xử lý phản hồi."
            try:
                response_text = self.response_generator.generate_response(
                    user_input_asr, 
                    nlu_result["intent"], 
                    nlu_result["entities"], 
                    db_query_result, 
                    self.current_state,
                    self.history # Truyền History
                )
            except Exception as e:
                 self.log(f"❌ [DM] Lỗi Response Generation: {e}", "red")
                 response_text = f"Đã xảy ra lỗi hệ thống khi tạo phản hồi: {e}"

        except Exception as e:
            self.log(f"⚠️ [NLU] Lỗi NLU, chuyển về no_match. Lỗi: {e}. Traceback: {traceback.format_exc()}", "orange")
            return self._handle_low_confidence_or_no_speech(user_input_asr, 0.0)
        
        return self._log_and_return(start_time, response_text, user_input_asr, nlu_result)


    def process_audio_file(self, record_file: str, user_input_asr: str) -> Dict[str, Any]:
        """Hàm công khai được gọi từ RTCStreamProcessor."""
        
        # Tải lại API Key nếu có (dùng cho LLM)
        if self.mode == "RTC" and self.api_key:
            # Cập nhật API Key trong ResponseGenerator (giả định dùng threading.local hoặc thuộc tính)
            if hasattr(self.response_generator, 'api_key_var') and hasattr(self.response_generator.api_key_var, 'value'):
                self.response_generator.api_key_var.value = self.api_key
            elif hasattr(self.response_generator, 'api_key'):
                 self.response_generator.api_key = self.api_key
        
        self.log(f"🚀 [DM] Bắt đầu xử lý file audio: {os.path.basename(record_file)} | ASR: '{user_input_asr}'", "blue")
        return self._process_and_update_context(user_input_asr)