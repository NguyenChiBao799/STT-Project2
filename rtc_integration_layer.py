# rtc_integration_layer.py

import asyncio
from typing import AsyncGenerator, Callable, Optional, AsyncIterator, Tuple, Any
import time
from pathlib import Path
import wave 
import uuid 
import os 
from datetime import datetime as _dt 

# --- Hằng số (Phải khớp với main_app.py) ---
SAMPLE_RATE = 16000 
CHANNELS = 1
CHUNK_SIZE = 1024 # <-- ĐÃ THÊM: Khắc phục lỗi ImportError
# THƯ MỤC GHI ÂM
RECORDING_DIR = Path("rtc_recordings"); RECORDING_DIR.mkdir(exist_ok=True) 

# ==================== MOCK SERVICES (Giả lập ASR và TTS) ====================

class ASRServiceMock:
    """Giả lập dịch vụ ASR, nhận luồng audio và trả về luồng text."""
    def __init__(self, log_callback: Callable):
        self._log = log_callback 
        self.full_transcript = "Xin cho tôi đặt một đơn hàng cuối cùng" 

    async def transcribe(self, audio_stream: AsyncGenerator[bytes, None]) -> AsyncGenerator[str, None]:
        """Xử lý luồng audio và tạo luồng transcript."""
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Bắt đầu nhận và xử lý luồng âm thanh...", color="blue")
        
        chunk_count = 0
        async for chunk in audio_stream:
            chunk_count += 1
            pass 
        
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Nhận {chunk_count} chunks. Kết thúc luồng audio.", color="blue")

        if chunk_count > 0:
            await asyncio.sleep(0.01) 
            for i, word in enumerate(self.full_transcript.split()):
                yield word + (" " if i < len(self.full_transcript.split()) - 1 else "")
        else:
            yield "" 

class TTSServiceMock:
    """Giả lập dịch vụ TTS, nhận text và trả về luồng audio."""
    def __init__(self, log_callback: Callable):
        self._log = log_callback

    async def synthesize(self, text_response: str) -> AsyncGenerator[bytes, None]:
        """Tạo luồng audio từ văn bản."""
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🔊 [TTS] Bắt đầu tạo luồng audio phản hồi...", color="purple")
        
        # Giả lập tạo audio chunks
        audio_chunk = f"audio_chunk_for_{text_response}".encode('utf-8')
        # Tạo ít nhất 1 chunk để đảm bảo luồng trả về
        num_chunks = max(1, len(audio_chunk) // CHUNK_SIZE + (1 if len(audio_chunk) % CHUNK_SIZE > 0 else 0))
        
        for i in range(num_chunks):
            # Cắt chunk theo CHUNK_SIZE
            start_index = i * CHUNK_SIZE
            end_index = (i + 1) * CHUNK_SIZE
            chunk = audio_chunk[start_index:end_index]
            
            if chunk:
                 yield chunk
                 await asyncio.sleep(0.005) 
            else:
                 break # Tránh chunk rỗng nếu logic cắt không hoàn hảo
        
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🔊 [TTS] Hoàn tất tạo luồng audio.", color="purple")


# ==================== RTC INTEGRATION PROCESSOR =====================

class RTCStreamProcessor:
    def __init__(self, log_callback: Optional[Callable] = None):
        def default_log(message, color=None):
            if log_callback is None:
                print(f"[{time.strftime('%H:%M:%S')}] [LOG] {message}")
        
        self._log = log_callback if log_callback else default_log
        self._asr_client = ASRServiceMock(self._log)
        self._tts_client = TTSServiceMock(self._log)

    async def _record_stream(self, 
                             audio_input_stream: AsyncGenerator[bytes, None],
                             record_file: Path) -> AsyncGenerator[bytes, None]:
        """Ghi âm stream đầu vào vào file và YIELD các chunk để truyền cho ASR."""
        
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 💾 [Recorder] Bắt đầu ghi âm đầu vào vào: {record_file.name}", color="orange")
        
        with wave.open(str(record_file), 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2) 
            wf.setframerate(SAMPLE_RATE)
            
            # ⚠️ Vòng lặp này đã được khắc phục lỗi NoneType nhờ fix trong main_app.py
            async for chunk in audio_input_stream:
                wf.writeframes(chunk)
                yield chunk # Truyền chunk sang bước tiếp theo (ASR)

        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 💾 [Recorder] Hoàn tất ghi âm: {record_file.name}", color="orange")


    async def handle_rtc_session(self, 
                                 audio_input_stream: AsyncGenerator[bytes, None], 
                                 session_id: str) \
                                 -> AsyncGenerator[Tuple[bool, Any], None]:
        """
        Xử lý phiên RTC: Ghi âm đầu vào -> ASR/NLU -> TTS.
        Trả về luồng audio TTS và luồng text metadata.
        Output Format: (is_audio: bool, data: Any)
        """
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ▶️ [RTC] Bắt đầu phiên RTC...", color="cyan")
        
        # 1. Ghi âm đầu vào và tạo stream mới
        record_file = RECORDING_DIR / f"{session_id}_input.wav"
        # Luồng này vừa ghi âm vừa truyền chunk cho ASR
        recording_and_passing_stream = self._record_stream(audio_input_stream, record_file)

        # 2. Xử lý ASR
        asr_stream = self._asr_client.transcribe(recording_and_passing_stream)
        full_transcript = ""
        async for partial_text in asr_stream:
            full_transcript += partial_text
        
        # 3. NLU/Response Logic (Mock)
        response_text = "Tôi không hiểu yêu cầu của bạn. Vui lòng nói lại."
        if full_transcript and "đơn hàng" in full_transcript.lower():
            response_text = "Đã tìm thấy yêu cầu đặt đơn hàng. Bạn muốn sản phẩm nào?"
        
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🧠 [NLU] Transcript: '{full_transcript[:30]}...' -> Response: '{response_text[:30]}...' (File: {record_file.name})", color="green")

        # YIELD TEXT METADATA ĐỂ GHI VÀO CHAT BOX
        # Format: (False, {'user_text': transcript, 'bot_text': response})
        yield (False, {"user_text": full_transcript, "bot_text": response_text})

        # 4. TTS và Trả về Luồng Audio
        tts_audio_stream = self._tts_client.synthesize(response_text)
        
        # YIELD AUDIO CHUNKS
        # Format: (True, audio_chunk_bytes)
        async for chunk in tts_audio_stream:
             yield (True, chunk) 
        
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🏁 [RTC] Phiên hoàn tất.", color="cyan")