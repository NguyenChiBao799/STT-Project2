# dialog_manager.py (ĐÃ SỬA: Tích hợp db_connector.py)
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
_INITIAL_STATE = "START"
_NLU_CONFIDENCE_THRESHOLD = 0.6
_DB_MODE_DEFAULT = "MOCK"
_TTS_MODE_DEFAULT = "MOCK"
_LLM_MODE_DEFAULT = "API"
_ASR_MODE_DEFAULT = "WHISPER"
_NLU_MODE_DEFAULT = "MOCK"
_SCENARIOS_CONFIG = {"rules": []}
_TEMP_TTS_FILE = "tts_fallback.wav"
_AUDIO_FILE = "asr_input.wav"
_TTS_VOICE_NAME_DEFAULT = "vi"

# Thử import các hằng số từ config_db và các lớp client
try:
    from config_db import (
        ASR_MODE_DEFAULT, NLU_CONFIDENCE_THRESHOLD,
        NLU_MODE_DEFAULT, DB_MODE_DEFAULT, TTS_MODE_DEFAULT,
        LLM_MODE_DEFAULT, API_KEY, SCENARIOS_CONFIG,
        INITIAL_STATE, GEMINI_MODEL 
    )
    # Import các lớp Client (Giả lập)
    class LLMClientMock:
        def __init__(self, *args, **kwargs): pass
        def classify_intent(self, text, *args, **kwargs): return {"intent": "chao_hoi", "confidence": 1.0}

    class TTSProcessorMock:
        def __init__(self, *args, **kwargs): pass
        def __call__(self, text): return None
        
    class ResponseGeneratorMock:
        def __init__(self, *args, **kwargs): self.tts_processor = TTSProcessorMock()
        def generate_response(self, *args, **kwargs): return "Chào bạn, tôi là trợ lý ảo. Bạn cần hỗ trợ gì?"
        
    class NLUClientMock:
        def __init__(self, *args, **kwargs): pass
        def classify_intent(self, text, *args, **kwargs): return {"intent": "chao_hoi", "confidence": 1.0}

    # ✅ Import lớp Tích hợp DB mới từ db_connector
    from db_connector import MockIntegrationManager as SystemIntegrationManager 
    
except ImportError as e:
    # Fallback cho các lớp cần thiết nếu import lỗi
    SystemIntegrationManager = lambda log_callback: type('MockIntegrationManager', (object,), {
        'query_external_customer_data': lambda self, *a, **kw: None,
        'query_internal_product_data': lambda self, *a, **kw: None,
        '_log': log_callback
    })()
    LLMClientMock = lambda *args, **kwargs: type('LLMClientMock', (object,), {
        'classify_intent': lambda self, *a, **kw: {"intent": "chao_hoi", "confidence": 1.0}
    })()
    NLUClientMock = LLMClientMock 
    TTSProcessorMock = lambda *args, **kwargs: type('TTSProcessorMock', (object,), {'__call__': lambda self, text: None})()
    ResponseGeneratorMock = lambda *args, **kwargs: type('ResponseGeneratorMock', (object,), {
        'generate_response': lambda self, *a, **kw: "Chào bạn, tôi là trợ lý ảo (FALLBACK).",
        'tts_processor': TTSProcessorMock()
    })()
    
    print(f"❌ [DM] Lỗi Import/Fallback: {e}. Sử dụng MOCK cho tất cả các thành phần.", flush=True)


# ==================== DIALOG MANAGER ====================

class DialogManager:
    """Quản lý luồng xử lý NLU, DB Lookup, State và Phản hồi (DM)."""
    
    def __init__(self, log_callback: Callable, mode: str = "RTC", api_key: str = None):
        self.log = log_callback
        self.mode = mode # RTC hoặc CLI
        self.current_state = _INITIAL_STATE
        self.api_key = api_key
        
        # 1. Khởi tạo NLU Client
        if NLU_MODE_DEFAULT == "LLM":
            self.nlu_client = LLMClientMock(log_callback=self.log, model=GEMINI_MODEL, api_key=api_key)
        else: # MOCK hoặc LOCAL
            self.nlu_client = NLUClientMock(log_callback=self.log)
            
        # 2. Khởi tạo DB Integration (SỬ DỤNG LỚP MỚI)
        self.db_integration = SystemIntegrationManager(log_callback=self.log)
        
        # 3. Khởi tạo Response Generator (Giả lập)
        self.response_generator = ResponseGeneratorMock(log_callback=self.log)
        
        self.log(f"🧠 [DM] Khởi tạo thành công (NLU: {NLU_MODE_DEFAULT}, TTS: {TTS_MODE_DEFAULT})", "green")


    def _query_db(self, user_input_asr: str, nlu_result: Dict[str, Any]) -> Dict[str, Any]:
        """Thực hiện tra cứu DB dựa trên intent và slots."""
        db_query_result = {}
        intent = nlu_result.get("intent")
        
        # ✅ SỬ DỤNG DB CONNECTOR ĐỂ TRA CỨU KHÁCH HÀNG
        if intent == "query_customer" and nlu_result.get("slots", {}).get("customer_id"):
            customer_id = nlu_result["slots"]["customer_id"]
            # Gọi phương thức từ MockIntegrationManager
            customer_data = self.db_integration.query_external_customer_data(customer_id)
            if customer_data:
                db_query_result["customer_data"] = customer_data
        
        # ✅ SỬ DỤNG DB CONNECTOR ĐỂ TRA CỨU SẢN PHẨM
        if intent == "query_product" and nlu_result.get("slots", {}).get("product_sku"):
            product_sku = nlu_result["slots"]["product_sku"]
            # Gọi phương thức từ MockIntegrationManager
            product_data = self.db_integration.query_internal_product_data(product_sku)
            if product_data:
                db_query_result["product_data"] = product_data

        return db_query_result


    def _update_state(self, intent: str, nlu_result: Dict[str, Any], current_state: str) -> str:
        """Logic State Machine (Đơn giản)"""
        return current_state


    def process_audio_file(self, audio_file_path: str, user_input_asr: str) -> Dict[str, Any]:
        """
        Phương thức đồng bộ chính (Được gọi trong asyncio.to_thread).
        Thực hiện toàn bộ luồng xử lý NLU/DM/TTS.
        """
        start_time = time.time()
        self.log(f"[{time.strftime('%H:%M:%S', time.localtime(start_time))}] 🧠 [DM] Bắt đầu xử lý cho Transcript: '{user_input_asr[:30]}...'", "yellow")
        
        # 1. NLU (Intent & Slot Extraction)
        nlu_result = {"intent": "no_match", "confidence": 0.00, "slots": {}}
        try:
            nlu_result = self.nlu_client.classify_intent(user_input_asr)
            if nlu_result.get("confidence", 0.0) < _NLU_CONFIDENCE_THRESHOLD:
                raise ValueError("Confidence thấp.")
            
        except Exception as e:
            self.log(f"⚠️ [NLU] Lỗi/Confidence thấp ({nlu_result.get('confidence', 0.0):.2f}), chuyển về no_match. Lỗi: {e}", "orange")
            nlu_result["intent"] = "no_match"
            nlu_result["confidence"] = 0.00
            
        # 2. Tra cứu DB và State Update
        db_query_result = self._query_db(user_input_asr, nlu_result) 
        self.current_state = self._update_state(nlu_result["intent"], nlu_result, self.current_state)

        # 3. Response Generation & TTS
        response_text = "Đã xảy ra lỗi trong quá trình xử lý phản hồi."
        tts_path = None
        try:
            response_text = self.response_generator.generate_response(
                user_input_asr, nlu_result["intent"], nlu_result, db_query_result, self.current_state
            )
        except Exception as e:
             self.log(f"❌ [DM] Lỗi Response Generation: {e}", "red")
        
        # Tạm thời bỏ qua TTS Path vì luồng RTC sẽ tự động xử lý TTS Mock/Streaming

        end_time = time.time()
        self.log(f"[{time.strftime('%H:%M:%S', time.localtime(end_time))}] ✅ [DM] Hoàn tất. Thời gian: {end_time - start_time:.2f}s", "green")

        return {
            "response_text": response_text, 
            "response_audio_path": tts_path, 
            "user_input_asr": user_input_asr
        }