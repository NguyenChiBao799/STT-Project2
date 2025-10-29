# response_generator.py
# Module chịu trách nhiệm tạo phản hồi văn bản (LLM) và Text-to-Speech (TTS).

import time
import os
from typing import Optional, Dict, Any, List, Callable
import wave

# --- Thư viện mới cho gTTS ---
try:
    from gtts import gTTS
except ImportError:
    gTTS = None
    print("❌ [gTTS] Thư viện gTTS chưa được cài đặt (pip install gtts). TTS sẽ sử dụng Mock.")


# --- SAFE IMPORT/FALLBACK cho config_db ---
try:
    from config_db import GEMINI_MODEL, TEMP_TTS_FILE, TTS_MODE_DEFAULT, TTS_VOICE_NAME_DEFAULT, API_KEY
except ImportError:
    GEMINI_MODEL = "gemini-2.5-flash"
    TEMP_TTS_FILE = "tts_fallback.mp3" 
    TTS_MODE_DEFAULT = "MOCK"
    TTS_VOICE_NAME_DEFAULT = "vi"
    API_KEY = "MOCK_API_KEY"
    print("⚠️ [RG] Failed to import from config_db, using fallback settings.")


class BaseTTS:
    """Lớp cơ sở cho các công cụ Text-to-Speech (MOCK)."""
    def __init__(self, log_callback):
        self.log = log_callback
        self.is_ready = True
        
    def generate(self, text: str, output_path: str) -> Optional[str]:
        self.log(f"🎵 [TTS Mock] Tạo file giả lập cho: '{text[:20]}...'", color="yellow")
        # Giả lập tạo file WAV 44 byte (header WAV)
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b'')
        return output_path

class ResponseGenerator:
    """
    Tạo phản hồi văn bản (LLM) và sinh giọng nói (TTS).
    """
    
    # ⚠️ FIX LỖI: Chấp nhận tham số 'api_key'
    def __init__(self, log_callback: Callable, config: Dict[str, Any], api_key: str = ""):
        self.log = log_callback
        self.config = config
        self.is_ready = True
        
        # API Key sẽ được truyền từ DialogManager (hoặc dùng fallback)
        self.api_key = api_key or API_KEY
        
        # Ta cần một cơ chế để mô phỏng `self.api_key_var.get()` 
        # Nếu code gốc có đối tượng cấu hình phức tạp, ta sẽ dùng key được truyền vào
        class MockApiKeyVar:
            def get(self):
                return self.key
            def set(self, key):
                self.key = key
        
        self.api_key_var = MockApiKeyVar()
        self.api_key_var.set(self.api_key) 
        
        self.tts_processor = self._initialize_tts_client()
        
    def _initialize_tts_client(self):
        tts_mode = self.config.get("tts_mode", TTS_MODE_DEFAULT)
        if tts_mode == "GOOGLE_TTS" and gTTS:
            # TODO: Implement GoogleTTS client
            return BaseTTS(self.log) # Dùng Mock tạm thời
        else:
            return BaseTTS(self.log)

    def generate_response_from_tool_data(self, intent: str, tool_data: Dict[str, Any]) -> Optional[str]:
        # Logic Template dựa trên tool_data
        if intent == "query_weather":
            return f"Thông tin thời tiết: {tool_data.get('weather_data', 'Không tìm thấy.')}"
        
        return None
    
    def generate_response(self, user_text: str, intent: str, nlu_result: Dict[str, Any], tool_data: Dict[str, Any], current_state: str) -> str:
        """
        Luồng sinh phản hồi: Template -> LLM (nếu có API Key).
        """
        prompt = f"Người dùng: {user_text}. Intent: {intent}. State: {current_state}."
        context = f"Entities: {nlu_result.get('entities')}. Tool Data: {tool_data}."
        
        tool_response = str(tool_data)
        
        # 1. Ưu tiên Template
        if tool_data and intent:
            template_response = self.generate_response_from_tool_data(intent, tool_data)
            if template_response:
                self.log(f"✅ [RG] Sử dụng Template cho intent '{intent}'.", color="green")
                return template_response

        # 2. Sinh ngôn ngữ tự nhiên bằng LLM (Nếu không có template hoặc template lỗi)
        api_key = self.api_key_var.get()
        
        if not api_key or api_key == "MOCK_API_KEY":
            self.log("⚠️ [RG] Không có API Key (hoặc đang dùng Mock). Sử dụng phản hồi mặc định/fallback.", color="orange")
            # Fallback dựa trên Intent
            for item in self.config.get("nlu_config", {}).get("intents", []):
                if item["intent_name"] == intent and item["responses"]:
                    return item["responses"][0]
            
            # Fallback chung
            return "Tôi đã nhận được yêu cầu. Vui lòng cung cấp API Key để sử dụng trí tuệ nhân tạo tạo phản hồi chi tiết hơn."

        try:
            # TODO: Implement _call_gemini_api(prompt, context, tool_response)
            # Giả lập phản hồi LLM thành công
            self.log(f"🗣️ [GEMINI MOCK] Phản hồi đã nhận (Mock LLM): {intent}", color="blue")
            return f"Đây là phản hồi LLM giả lập cho intent: {intent}. Dữ liệu tra cứu: {tool_response}"
        
        except Exception as e:
            self.log(f"❌ [GEMINI] Lỗi gọi API: {e}", color="red")
            return f"Xin lỗi, có lỗi khi tạo phản hồi AI: {e}"
            
    def generate_tts(self, response_text: str) -> Optional[str]:
        """Tạo file audio TTS từ phản hồi văn bản."""
        return self.tts_processor.generate(response_text, TEMP_TTS_FILE)

# Cần đảm bảo rằng `ResponseGenerator` được export đúng cách.