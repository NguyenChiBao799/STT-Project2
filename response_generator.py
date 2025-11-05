# response_generator.py
import time
import os
import random
import threading
from typing import Optional, Dict, Any, List, Callable, Literal
import wave

# ----------------------------
# SAFE IMPORT/FALLBACK cho config_db
# ----------------------------
_FALLBACK_API_KEY = "MOCK_API_KEY"

try:
    from config_db import GEMINI_MODEL, TTS_MODE_DEFAULT, TTS_VOICE_NAME_DEFAULT, API_KEY
except ImportError:
    GEMINI_MODEL = "gemini-2.5-flash"
    TTS_MODE_DEFAULT = "MOCK"
    TTS_VOICE_NAME_DEFAULT = "vi"
    API_KEY = _FALLBACK_API_KEY

# Mock/Fallback gTTS
try:
    from gtts import gTTS
except ImportError:
    gTTS = None
    
# ======================================================
# LỚP TTS CƠ SỞ VÀ MOCK
# ======================================================

class BaseTTS:
    """Lớp cơ sở cho các công cụ Text-to-Speech (MOCK)."""
    def __init__(self, log_callback):
        self.log = log_callback
        self.is_ready = True
        
    def generate(self, text: str, output_path: str) -> Optional[str]:
        # Giả lập tạo file WAV (chỉ dùng cho chế độ file-based)
        try:
            with wave.open(output_path, 'w') as wf:
                wf.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                wf.writeframes(b'\x00' * 16000 * 2) # 1 second of silence
            self.log(f"🎵 [TTS Mock] Tạo file giả lập: {output_path}", "magenta")
            return output_path
        except Exception: return None

# TTSServiceMock trong rtc_integration_layer sẽ xử lý streaming

# ======================================================
# LỚP RESPONSE GENERATOR CHÍNH (Đã cập nhật)
# ======================================================

class ResponseGenerator:
    """
    Tạo phản hồi văn bản dựa trên Intent, Entities, DB Result và State.
    """
    def __init__(self, 
                 log_callback: Callable, 
                 config: Dict[str, Any],
                 llm_mode: str,
                 tts_mode: str,
                 db_mode: str,
                 api_key: str):
        
        self.log = log_callback
        self.config = config
        self.llm_mode = llm_mode
        self.tts_mode = tts_mode
        self.db_mode = db_mode
        
        # Sử dụng threading.local để lưu trữ API Key (an toàn trong môi trường đa luồng)
        self.api_key_var: threading.local = threading.local()
        setattr(self.api_key_var, 'value', api_key)
        
        self.tts_client = BaseTTS(self.log) # Dùng Mock base class

    def generate_response(self, 
                          user_input_asr: str, 
                          intent: str, 
                          entities: List[Dict[str, str]], 
                          db_query_result: Dict[str, Any],
                          current_state: str) -> str:
        
        # 1. Logic Phản hồi dựa trên DB Lookup (Ưu tiên cao nhất)
        response_text = self._generate_from_db_result(intent, db_query_result)
        if response_text:
            self.log("✅ [RG] Trả lời dựa trên dữ liệu tra cứu.", "green")
            return response_text

        # 2. Logic Phản hồi dựa trên Template 
        for rule in self.config.get("rules", []):
            if rule["intent"] == intent:
                # Lấy ngẫu nhiên một response nếu có nhiều responses
                responses = rule.get("responses") or [rule.get("response")]
                response_text = random.choice(responses)
                if response_text:
                    self.log("✅ [RG] Trả lời dựa trên template.", "green")
                    return response_text

        # 3. Logic Phản hồi bằng LLM (Nếu template không khớp)
        if self.llm_mode in ["API", "MOCK"]:
            self.log("⚠️ [RG] Không có template khớp. Chuyển sang tạo ngôn ngữ tự nhiên (LLM Mock).", "orange")
            llm_context = {
                "user_text": user_input_asr, "intent": intent, "entities": entities, 
                "db_result": db_query_result, "state": current_state
            }
            return self._generate_with_llm_mock(llm_context)
            
        # 4. Fallback cuối cùng
        return self.config.get("rules", [{}])[0].get("response", "Xin lỗi, tôi không hiểu yêu cầu của bạn.")

    def _generate_from_db_result(self, intent: str, db_query_result: Dict[str, Any]) -> Optional[str]:
        """Tạo phản hồi dựa trên kết quả DB Lookup."""
        
        customer_data = db_query_result.get("customer_data")
        product_data = db_query_result.get("product_data")
        
        if intent == "kiem_tra_don_hang" and customer_data:
            return (
                f"Xin chào **{customer_data['customer_name']}**. "
                f"Đơn hàng gần nhất của bạn đã được cập nhật: '{customer_data['last_order']}'. "
                f"Bạn có cần hỗ trợ gì thêm không?"
            )
        
        if intent in ["hoi_thong_tin_san_pham", "hoi_khuyen_mai"] and product_data:
            discount = product_data.get("discount")
            price = product_data.get("price")
            product_name = product_data.get("product_name")
            
            if discount and int(discount) > 0:
                 return (
                    f"Sản phẩm **{product_name}** có giá **{price}**. Hiện đang có khuyến mãi hấp dẫn: "
                    f"giảm **{discount}%** cho khách hàng thân thiết. Bạn muốn đặt hàng ngay chứ?"
                 )
            else:
                 return (
                    f"Sản phẩm **{product_name}** có giá **{price}**. "
                    f"Hiện tại sản phẩm này không có khuyến mãi nào đặc biệt. "
                    f"Bạn có muốn tôi kiểm tra thông tin khác không?"
                 )
        
        return None

    def _generate_with_llm_mock(self, llm_context: Dict[str, Any]) -> str:
        """Giả lập tạo phản hồi ngôn ngữ tự nhiên bằng LLM."""
        api_key = getattr(self.api_key_var, 'value', _FALLBACK_API_KEY)
        
        if not api_key or api_key == _FALLBACK_API_KEY:
            return f"Tôi đã nhận được yêu cầu (**{llm_context['intent']}**). Vui lòng cung cấp API Key để sử dụng trí tuệ nhân tạo tạo phản hồi chi tiết hơn."

        try:
            self.log(f"🗣️ [GEMINI MOCK] Phản hồi đã nhận (Mock LLM) với API Key: {llm_context['intent']}", color="blue")
            db_info_str = ""
            if llm_context['db_result'].get("customer_data"): db_info_str += f" | KH: {llm_context['db_result']['customer_data']['customer_name']}"
            if llm_context['db_result'].get("product_data"): db_info_str += f" | SP: {llm_context['db_result']['product_data']['product_name']}"
            
            return f"Đây là phản hồi LLM giả lập cho yêu cầu: '**{llm_context['user_text']}**'. Intent được nhận diện: **{llm_context['intent']}**. Dữ liệu tra cứu: {db_info_str if db_info_str else 'Không có'}. (Sử dụng {GEMINI_MODEL})"
        
        except Exception as e:
            self.log(f"❌ [GEMINI] Lỗi gọi API: {e}", color="red")
            return f"Xin lỗi, có lỗi khi tạo phản hồi AI: {e}"