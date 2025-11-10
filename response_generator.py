# response_generator.py
import time
import os
import random
import threading
from typing import Optional, Dict, Any, List, Callable, Literal, AsyncGenerator
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
    def __init__(self, log_callback: Callable):
        self.log = log_callback
        self.is_ready = True
        
    def generate(self, text: str, output_path: str) -> Optional[str]:
        # Giả lập tạo file WAV (chỉ dùng cho chế độ file-based)
        try:
            with wave.open(output_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                # Giả lập 1 giây audio rỗng
                wf.writeframes(b'\x00\x00' * 16000) 
            self.log(f"🎵 [TTS Mock] Đã tạo file audio giả lập: {os.path.basename(output_path)}", "magenta")
            return output_path
        except Exception as e:
            self.log(f"❌ [TTS Mock] Lỗi tạo file audio giả lập: {e}", "red")
            return None
        
    def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Giả lập streaming audio bytes (chunked)."""
        async def mock_stream():
             # Giả lập stream 3 chunks
             yield b'MOCK_AUDIO_CHUNK_1'
             yield b'MOCK_AUDIO_CHUNK_2'
             yield b'MOCK_AUDIO_CHUNK_3'
        return mock_stream()
        
class MockTTS(BaseTTS):
    """Sử dụng BaseTTS Mock."""
    pass

# ======================================================
# RESPONSE GENERATOR
# ======================================================

class ResponseGenerator:
    """
    Tạo phản hồi, sử dụng LLM hoặc rule-based.
    Cũng quản lý TTS Client.
    """
    # 🚨 FIX: Đảm bảo __init__ nhận đủ 6 tham số cần thiết
    def __init__(self, log_callback: Callable, config: Dict[str, Any], llm_mode: str, tts_mode: str, db_mode: str, api_key: str):
        self.log = log_callback
        self.config = config
        self.llm_mode = llm_mode
        self.tts_mode = tts_mode
        self.db_mode = db_mode
        
        # API Key cần được lưu trữ an toàn, sử dụng threading.local để hỗ trợ đồng thời.
        self.api_key_var = threading.local()
        self.api_key_var.value = api_key or API_KEY # Lấy từ tham số hoặc config_db/fallback

        # Khởi tạo TTS Client
        self._initialize_tts_client()


    def _initialize_tts_client(self):
        """Khởi tạo TTS client dựa trên self.tts_mode."""
        if self.tts_mode == "MOCK":
            self.tts_client = MockTTS(self.log)
        else:
            # Ở đây có thể tích hợp Google Cloud TTS/Gradio TTS hoặc các engine khác.
            self.log(f"⚠️ [TTS] Chế độ TTS '{self.tts_mode}' không được hỗ trợ, sử dụng Mock TTS.", "yellow")
            self.tts_client = MockTTS(self.log)
            
        self.log(f"🎵 [TTS] TTS Client đã khởi tạo thành công (Mode: {self.tts_mode}).", "magenta")


    # API công khai để lấy TTS client
    @property
    def tts_client(self):
        return self._tts_client

    @tts_client.setter
    def tts_client(self, client):
        self._tts_client = client


    def _generate_with_rules(self, intent: str) -> Optional[str]:
        """Tạo phản hồi dựa trên rule-based config."""
        
        # Tìm rule theo intent
        for rule in self.config.get("rules", []):
            if rule["intent"] == intent:
                responses = rule.get("responses", [rule.get("response")])
                if responses:
                    return random.choice(responses)
        
        # Rule fallback cho no_match
        if intent != "no_match":
            return self._generate_with_rules("no_match")
            
        return None

    def _generate_with_db_info(self, intent: str, db_result: Dict[str, Any]) -> Optional[str]:
        """Tạo phản hồi chi tiết dựa trên kết quả DB."""
        customer_data = db_result.get("customer_data")
        product_data = db_result.get("product_data")

        if intent == "query_customer_info" and customer_data:
            return (
                f"Thông tin khách hàng: **{customer_data['customer_name']}**."
                f" Lần đặt hàng gần nhất: {customer_data['last_order']}."
                f" Bạn cần hỗ trợ thêm về thông tin này không?"
            )
        
        if intent == "query_product_info" and product_data:
            discount = product_data.get("discount")
            if discount and int(discount) > 0:
                 return (
                    f"Sản phẩm **{product_data['product_name']}** hiện có giá {product_data['price']}."
                    f" Bạn sẽ được giảm giá {discount} phần trăm. Bạn có muốn đặt hàng ngay không?"
                 )
            else:
                 return (
                    f"Sản phẩm **{product_data['product_name']}** có giá {product_data['price']}. "
                    f"Hiện sản phẩm này không có khuyến mãi nào đặc biệt. "
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
            
            history_len = len(llm_context.get('history', []))
            
            return (
                 f"Đây là phản hồi LLM giả lập cho yêu cầu: '**{llm_context['user_text']}**'. "
                 f"Trạng thái hiện tại: **{llm_context['current_state']}**."
                 f" (Dữ liệu nền: {db_info_str}). "
                 f"Lịch sử hội thoại: **{history_len} lượt**."
            )
        except Exception as e:
            self.log(f"❌ [GEMINI MOCK] Lỗi tạo LLM Mock: {e}", "red")
            return "Xin lỗi, đã xảy ra lỗi khi tạo phản hồi LLM."
    

    def generate_response(
        self,
        user_text: str,
        intent: str,
        entities: Dict[str, Any],
        db_result: Dict[str, Any],
        current_state: str,
        history: List[Dict[str, str]] = [] # ✅ Thêm tham số History
    ) -> str:
        """Tạo phản hồi cuối cùng, ưu tiên Rule -> DB -> LLM."""
        
        # 1. Rule-based / Tĩnh
        response = self._generate_with_rules(intent)
        if response:
            return response

        # 2. DB-based / Chi tiết
        response = self._generate_with_db_info(intent, db_result)
        if response:
            return response
            
        # 3. LLM-based / Ngôn ngữ tự nhiên (hoặc Mock)
        llm_context = {
            "user_text": user_text,
            "intent": intent,
            "entities": entities,
            "db_result": db_result,
            "current_state": current_state,
            "history": history # Truyền History
        }
        return self._generate_with_llm_mock(llm_context)