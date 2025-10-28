# response_generator.py
# Module chịu trách nhiệm tạo phản hồi văn bản (LLM) và Text-to-Speech (TTS).

import time
import os
from typing import Optional, Dict, Any, List

# --- Thư viện mới cho gTTS ---
try:
    from gtts import gTTS
    # pydub cần thiết nếu muốn chuyển đổi MP3 sang WAV hoặc xử lý âm thanh phức tạp
    # Tuy nhiên, ta chỉ cần gTTS để tạo file MP3
except ImportError:
    gTTS = None
    print("❌ [gTTS] Thư viện gTTS chưa được cài đặt (pip install gtts). TTS sẽ sử dụng Mock.")


# --- SAFE IMPORT/FALLBACK cho config_db ---
try:
    from config_db import GEMINI_MODEL, TEMP_TTS_FILE, TTS_MODE_DEFAULT, TTS_VOICE_NAME_DEFAULT
except ImportError:
    GEMINI_MODEL = "gemini-2.5-flash"
    TEMP_TTS_FILE = "tts_fallback.mp3" 
    TTS_MODE_DEFAULT = "MOCK"
    TTS_VOICE_NAME_DEFAULT = "vi"
    print("⚠️ [RG] Failed to import from config_db, using fallback settings.")


class BaseTTS:
    """Lớp cơ sở cho các công cụ Text-to-Speech (MOCK)."""
    def __init__(self, log_callback):
        self.log = log_callback
        self.is_ready = True
        
    def generate_audio_file(self, text: str) -> Optional[str]:
        """Mô phỏng việc gọi API TTS và lưu file."""
        self.log(f"🎙️ [TTS MOCK]: Đang tổng hợp giọng nói cho '{text[:50]}...'...", color="blue")
        time.sleep(1.5) # Giả lập độ trễ TTS
        try:
            # Tạo file MP3 giả lập
            os.makedirs(os.path.dirname(TEMP_TTS_FILE), exist_ok=True)
            with open(TEMP_TTS_FILE, 'w') as f:
                f.write('TTS API successful mock.')
            self.log(f"✅ [TTS MOCK]: Đã tạo file giả lập tại {TEMP_TTS_FILE}.", color="green")
            return TEMP_TTS_FILE
        except Exception as e:
            self.log(f"❌ [TTS MOCK] Lỗi tạo file giả lập: {e}", color="red")
            return None


class GTTSProcessor(BaseTTS):
    """Sử dụng gTTS (Google Text-to-Speech) để tổng hợp giọng nói tiếng Việt."""
    
    def __init__(self, log_callback, lang: str = TTS_VOICE_NAME_DEFAULT):
        super().__init__(log_callback)
        self.lang = lang
        if not gTTS:
            self.log("❌ [gTTS] Thư viện gTTS chưa được cài đặt. Chuyển sang MOCK.", "red")
            self.is_ready = False
        else:
             self.is_ready = True

    def generate_audio_file(self, text: str) -> Optional[str]:
        """Gọi gTTS API công khai để tạo file MP3."""
        if not self.is_ready:
            return super().generate_audio_file(text) # Fallback về mock

        self.log(f"🎙️ [gTTS]: Đang tổng hợp giọng nói tiếng Việt cho '{text[:50]}...'...", color="blue")
        try:
            tts = gTTS(text=text, lang=self.lang, slow=False)
            output_path = TEMP_TTS_FILE
            
            # Đảm bảo thư mục tồn tại
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Lưu file trực tiếp dưới dạng MP3
            tts.save(output_path)
            
            self.log(f"✅ [gTTS]: Đã lưu file MP3 tại {output_path}.", color="green")
            return output_path
        
        except Exception as e:
            self.log(f"❌ [gTTS] Lỗi tạo file TTS: {e}", color="red")
            return None


class ResponseGenerator:
    """Xử lý logic tạo phản hồi."""

    def __init__(self, api_key_var: Any, log_callback: Any, tts_mode: str = TTS_MODE_DEFAULT):
        self.api_key_var = api_key_var
        self.log = log_callback
        self.tts_mode = tts_mode

        # Khởi tạo TTS Processor
        if tts_mode == "GTTS":
             self.tts_processor = GTTSProcessor(log_callback, lang=TTS_VOICE_NAME_DEFAULT)
        else:
             self.tts_processor = BaseTTS(log_callback) # MOCK
        
        # ✅ MOCK TEMPLATES (Mô phỏng template phản hồi được lưu trong DB/Config)
        self.RESPONSE_TEMPLATES = {
            "ask_price": "Sản phẩm **{product_name}** hiện có giá **{price:,}** đồng.", # Định dạng số tiền
            "ask_promotion": "Sản phẩm **{product_name}** đang giảm **{discount}%**.",
            "check_stock": "Trong kho còn **{quantity}** sản phẩm **{product_name}**.",
        }

    def _get_response_template(self, intent: str) -> Optional[str]:
        """Lấy template phản hồi theo intent (Mô phỏng tra cứu DB/Config)."""
        return self.RESPONSE_TEMPLATES.get(intent)

    def generate_response_from_tool_data(self, intent: str, tool_data: Dict[str, Any]) -> Optional[str]:
        """
        Tạo phản hồi dựa trên Template nếu có, sử dụng dữ liệu từ tool_data (DB/API).
        """
        template = self._get_response_template(intent)
        
        if not template:
            return None # Không tìm thấy template

        try:
            # Chỉ lấy các giá trị có thể định dạng (ví dụ: {price:,} cần số)
            # Giả định tool_data chứa các khóa như 'product_name', 'price', v.v.
            return template.format(**tool_data)
        except KeyError as e:
            self.log(f"⚠️ [RG Template] Thiếu khóa '{e}' để định dạng template '{intent}'. Chuyển sang LLM.", color="orange")
            return None
        except ValueError as e:
             self.log(f"⚠️ [RG Template] Lỗi định dạng giá trị (Format Error) trong template '{intent}': {e}. Chuyển sang LLM.", color="orange")
             return None
        except Exception as e:
            self.log(f"❌ [RG Template] Lỗi khác khi định dạng template '{intent}': {e}. Chuyển sang LLM.", color="red")
            return None


    def _call_gemini_api(self, prompt: str, context: List[Dict[str, Any]], tool_response: Optional[str]) -> str:
        """Mô phỏng việc gọi API Gemini thực tế."""
        self.log(f"🔗 [GEMINI] Đang gọi API Gemini ({GEMINI_MODEL})...", color="blue")
        time.sleep(1.0) # Giả lập độ trễ API
        
        # --- Logic Gọi API Gemini THỰC TẾ sẽ được thay thế ở đây ---
        
        if tool_response:
             # AI sinh ngôn ngữ tự nhiên, dựa trên kết quả tool_response
             return f"Dựa trên dữ liệu tra cứu: **{tool_response}**. Tôi có thể giải thích chi tiết hơn hoặc đưa ra các đề xuất tiếp theo cho bạn."
        
        # Phản hồi chung/Fallback
        return "Xin lỗi, tôi chưa thể trả lời câu hỏi này. Vui lòng cung cấp thêm thông tin chi tiết hoặc thử lại với câu hỏi khác."


    def generate_response(self, prompt: str, context: List[Dict[str, Any]], intent: str, tool_data: Optional[Dict[str, Any]] = None, tool_response: Optional[str] = None) -> str:
        """
        Tạo phản hồi văn bản, ưu tiên Template, sau đó là LLM.
        """
        
        # 1. Ưu tiên Template
        if tool_data and intent:
            template_response = self.generate_response_from_tool_data(intent, tool_data)
            if template_response:
                self.log(f"✅ [RG] Sử dụng Template cho intent '{intent}'.", color="green")
                return template_response

        # 2. Sinh ngôn ngữ tự nhiên bằng LLM (Nếu không có template hoặc template lỗi)
        api_key = self.api_key_var.get()
        
        if not api_key:
            self.log("⚠️ [GEMINI] Không có API Key. Sử dụng phản hồi mặc định.", color="orange")
            if tool_response:
                 return f"Tôi đã tra cứu được thông tin: {tool_response}. Vui lòng cung cấp API Key để nhận phản hồi LLM chi tiết hơn."
            return "Vui lòng cung cấp API Key để nhận phản hồi thông minh."

        try:
            response_text = self._call_gemini_api(prompt, context, tool_response)
            self.log(f"🗣️ [GEMINI] Phản hồi đã nhận: {response_text}", color="blue")
            return response_text
        except Exception as e:
            self.log(f"❌ [GEMINI] Lỗi gọi API: {e}", color="red")
            return f"Xin lỗi, có lỗi khi tạo phản hồi AI: {e}"
            
    def generate_tts(self, text: str) -> Optional[str]:
        """Tạo file TTS và trả về đường dẫn."""
        if self.tts_processor:
            return self.tts_processor.generate_audio_file(text)
        return None