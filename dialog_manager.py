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

try:
    from config_db import (
        NLU_CONFIDENCE_THRESHOLD, NLU_MODE_DEFAULT, 
        DB_MODE_DEFAULT, TTS_MODE_DEFAULT, LLM_MODE_DEFAULT, 
        API_KEY as CONFIG_API_KEY, SCENARIOS_CONFIG, INITIAL_STATE, GEMINI_MODEL 
    )
    from response_generator import ResponseGenerator
    from db_connector import SystemIntegrationManager 
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

    class ResponseGenerator:
        def __init__(self, *args, **kwargs): pass
        def generate_response(self, user_text, intent, entities, db_result, state):
             return f"⚠️ [RG MOCK] Không tìm thấy ResponseGenerator. Intent: {intent}"
             
    class SystemIntegrationManager:
        def __init__(self, log_callback: Callable): log_callback("⚠️ [DB] Sử dụng SystemIntegrationManager MOCK (FALLBACK).")
        def query_external_customer_data(self, *args): return None
        def query_internal_product_data(self, *args): return None


# ======================================================
# LỚP NLU MOCK
# ======================================================
class NLUClientMock:
    """Giả lập kết quả NLU từ ASR Text."""
    def __init__(self, log_callback: Callable): self.log = log_callback
    
    def process_text(self, text: str) -> Dict[str, Any]:
        text_lower = text.lower()
        
        if "chào" in text_lower or "xin chào" in text_lower:
            intent, confidence = "chao_hoi", 0.95
        elif "khuyến mãi" in text_lower or "giảm giá" in text_lower:
            intent, confidence = "hoi_khuyen_mai", 0.85
        elif "kiểm tra đơn hàng" in text_lower or "đơn hàng" in text_lower or "007" in text_lower:
            intent, confidence = "kiem_tra_don_hang", 0.80
        elif "sản phẩm" in text_lower or "sku" in text_lower or "a" in text_lower or "b" in text_lower:
             intent, confidence = "hoi_thong_tin_san_pham", 0.75
        else:
            # Giả lập Confidence thấp cho các câu không rõ ràng
            intent, confidence = "no_match", 0.4
            
        return {
            "intent": intent, 
            "confidence": confidence, 
            "entities": self._extract_mock_entities(text)
        }
        
    def _extract_mock_entities(self, text: str) -> List[Dict[str, str]]:
        entities = []
        if "007" in text: entities.append({"entity": "customer_id", "value": "007"})
        if "SKU A" in text or "sản phẩm a" in text.lower(): entities.append({"entity": "product_sku", "value": "A"})
        elif "SKU B" in text or "sản phẩm b" in text.lower(): entities.append({"entity": "product_sku", "value": "B"})
        return entities

# ======================================================
# DIALOG MANAGER CHÍNH
# ======================================================

class DialogManager:
    """
    Quản lý luồng hội thoại: ASR -> NLU -> DB Lookup -> State Update -> Response Generation.
    """
    def __init__(self, 
                 log_callback: Callable, 
                 mode: Literal["RTC", "FILE"] = "FILE",
                 api_key: str = _FALLBACK_API_KEY): 
        
        self.log = log_callback
        self.mode = mode
        self.current_state = INITIAL_STATE
        self.session_data: Dict[str, Any] = {}
        
        # 1. Khởi tạo NLU
        self.nlu_client = NLUClientMock(self.log)
        
        # 2. Khởi tạo DB/System Integration
        self.db_manager = SystemIntegrationManager(self.log) 
        
        # 3. Khởi tạo Response Generator
        self.response_generator = ResponseGenerator(
            log_callback=self.log,
            config=SCENARIOS_CONFIG,
            db_mode=DB_MODE_DEFAULT,
            llm_mode=LLM_MODE_DEFAULT,
            tts_mode=TTS_MODE_DEFAULT,
            api_key=api_key 
        )
        
        self.log(f"🧠 [DM] Khởi tạo. NLU: {NLU_MODE_DEFAULT}, DB: {DB_MODE_DEFAULT}, State: {INITIAL_STATE}", "cyan")
        
    # ======================================================
    # NEW: Hàm xử lý Low Confidence/No Speech
    # ======================================================
    def _handle_low_confidence_or_no_speech(self, user_input_asr: str, confidence: float) -> Dict[str, Any]:
        """Tạo kết quả xử lý cho trường hợp No Speech hoặc Confidence thấp."""
        
        if user_input_asr == "[NO SPEECH DETECTED]" or not user_input_asr.strip():
            response_text = "Xin lỗi, tôi không nghe rõ. Bạn có thể nói lại không?"
            confidence_level = 0.0
        elif confidence < NLU_CONFIDENCE_THRESHOLD:
            # Phản hồi khi confidence thấp
            response_text = "Xin lỗi, tôi chưa hiểu rõ ý bạn. Bạn có thể nói chi tiết hơn không?"
            confidence_level = confidence
        else:
            # Fallback (chỉ xảy ra nếu gọi hàm này không đúng)
            response_text = "Lỗi xử lý không xác định. Vui lòng thử lại."
            confidence_level = confidence

        self.log(f"⚠️ [DM] Xử lý Low Confidence/No Speech (Conf: {confidence_level:.2f}).", "orange")
        
        return {
            "response_text": response_text,
            "response_audio_path": None, 
            "user_input_asr": user_input_asr
        }

    # ======================================================
    # Existing Helper: Query DB (Giữ nguyên)
    # ======================================================
    def _query_db(self, user_input: str, nlu_result: Dict[str, Any]) -> Dict[str, Any]:
        """Thực hiện các tra cứu DB/POS dựa trên NLU và State."""
        
        db_query_result = {"customer_data": None, "product_data": None}
        
        entities = nlu_result.get("entities", [])
        customer_id = next((e["value"] for e in entities if e["entity"] == "customer_id"), None)
        product_sku = next((e["value"] for e in entities if e["entity"] == "product_sku"), None)
        
        if nlu_result["intent"] == "kiem_tra_don_hang":
            # Luôn cố gắng tìm ID khách hàng (dù là trong NLU hay Session)
            if not customer_id and "007" in user_input: customer_id = "007" 
            if customer_id:
                db_query_result["customer_data"] = self.db_manager.query_external_customer_data(customer_id)
            
        elif nlu_result["intent"] in ["hoi_thong_tin_san_pham", "hoi_khuyen_mai"]:
             if not product_sku:
                if "a" in user_input.lower(): product_sku = "A"
                elif "b" in user_input.lower(): product_sku = "B"
             if product_sku:
                db_query_result["product_data"] = self.db_manager.query_internal_product_data(product_sku)

        self.log(f"🔍 [DB] Kết quả tra cứu (Sản phẩm/Khách hàng): {db_query_result}", "blue")
        return db_query_result

    # ======================================================
    # Existing Helper: State Update (Giữ nguyên)
    # ======================================================
    def _update_state(self, intent: str, nlu_result: Dict[str, Any], current_state: str) -> str:
        """Logic State Machine (Đơn giản hóa)."""
        if intent == "kiem_tra_don_hang": return "ORDER_CHECK"
        elif intent in ["hoi_thong_tin_san_pham", "hoi_khuyen_mai"]: return "PRODUCT_INFO"
        elif intent == "chao_hoi": return "START"
        return current_state

    # ======================================================
    # Core Processor (Đã sửa đổi)
    # ======================================================
    def process_audio_file(self, record_file: str, user_input_asr: str) -> Dict[str, Any]:
        """Hàm xử lý chính (Đồng bộ)."""
        start_time = time.time()
        self.log(f"\n==========================================", "cyan")
        self.log(f"💬 [DM] Bắt đầu xử lý. ASR: '{user_input_asr}'", "cyan")
        
        # 1. KIỂM TRA NO SPEECH NGAY TỪ ĐẦU
        if user_input_asr == "[NO SPEECH DETECTED]" or not user_input_asr.strip():
            return self._handle_low_confidence_or_no_speech(user_input_asr, 0.0)

        nlu_result = {"intent": "no_match", "confidence": 0.00, "entities": []}

        try:
            # 2. NLU/Intent Detection
            nlu_result = self.nlu_client.process_text(user_input_asr)
            self.log(f"🧠 [NLU] Intent: {nlu_result.get('intent')}, Conf: {nlu_result.get('confidence', 0.0):.2f}", "yellow")
            
            # 3. KIỂM TRA LOW CONFIDENCE
            if nlu_result.get("confidence", 0.0) < NLU_CONFIDENCE_THRESHOLD:
                return self._handle_low_confidence_or_no_speech(user_input_asr, nlu_result.get("confidence", 0.0))
            
        except Exception as e:
            # Nếu NLU gặp lỗi không xác định, coi như confidence thấp
            self.log(f"⚠️ [NLU] Lỗi NLU, chuyển về no_match. Lỗi: {e}", "orange")
            return self._handle_low_confidence_or_no_speech(user_input_asr, 0.0)
            
        # 4. Tra cứu DB và State Update (CHỈ CHẠY KHI CONFIDENCE CAO)
        db_query_result = self._query_db(user_input_asr, nlu_result) 
        self.current_state = self._update_state(nlu_result["intent"], nlu_result, self.current_state)

        # 5. Response Generation
        response_text = "Đã xảy ra lỗi trong quá trình xử lý phản hồi."
        try:
            response_text = self.response_generator.generate_response(
                user_input_asr, 
                nlu_result["intent"], 
                nlu_result["entities"], 
                db_query_result, 
                self.current_state
            )
        except Exception as e:
             self.log(f"❌ [DM] Lỗi Response Generation: {e}", "red")
        
        end_time = time.time()
        self.log(f"✅ [DM] Hoàn tất xử lý ({end_time - start_time:.2f}s). State: {self.current_state}. Response: '{response_text[:50]}...'", "green")
        self.log(f"==========================================", "cyan")

        return {
            "response_text": response_text,
            "response_audio_path": None, 
            "user_input_asr": user_input_asr
        }