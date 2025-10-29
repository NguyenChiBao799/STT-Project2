# rtc_integration_layer.py - Đã tích hợp ASR (Whisper Logic) và DialogManager
import asyncio
import os
import wave
import uuid
import time
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional, Tuple, Any
from datetime import datetime as _dt
import numpy as np # Cần thiết cho Whisper
import traceback 

# --- SAFE IMPORTS (WHISPER) ---
try:
    import whisper
    # Lấy WHISPER_MODEL_NAME từ config_db nếu có
    try:
        from config_db import WHISPER_MODEL_NAME
    except ImportError:
        WHISPER_MODEL_NAME = "small"
        
    # Tải model (CÓ THỂ GÂY LỖI KHI RE-LOAD VỚI UVICORN/MULTIPROCESSING)
    # Nếu server vẫn lỗi, hãy chuyển việc tải model này vào hàm __init__
    WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME)
    print(f"✅ [ASR] Whisper model '{WHISPER_MODEL_NAME}' đã được tải.")
    WHISPER_IS_READY = True
except Exception as e:
    WHISPER_IS_READY = False
    WHISPER_MODEL = None
    print(f"❌ [ASR] Lỗi tải Whisper (pip install openai-whisper?): {e}. Sử dụng Mock.")

# --- SAFE IMPORTS (DIALOG MANAGER) ---
try:
    from dialog_manager import DialogManager 
    DM_IS_READY = True
except ImportError:
    class DialogManager:
        def __init__(self, *args, **kwargs): pass
        def process_audio_path(self, *args, **kwargs): 
            return {"response_text": "LỖI DM: Không tìm thấy DialogManager.", "response_audio_path": None, "user_input_asr": "LỖI."}
    DM_IS_READY = False
    print("❌ [NLU] Không tìm thấy DialogManager. Sử dụng Mock Fallback.")

# --- Hằng số (Phải khớp với config_db.py) ---
SAMPLE_RATE = 16000 
CHANNELS = 1
CHUNK_SIZE = 1024 
RECORDING_DIR = Path("rtc_recordings"); RECORDING_DIR.mkdir(exist_ok=True) 

# ==================== CÁC DỊCH VỤ ASR ====================

class ASRServiceWhisper:
    """ASR sử dụng OpenAI Whisper, xử lý file WAV đã lưu."""
    def __init__(self, log_callback: Callable, model):
        self._log = log_callback 
        self.model = model
        
    async def transcribe(self, audio_filepath: Path) -> AsyncGenerator[str, None]:
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Bắt đầu xử lý Whisper trên file: {audio_filepath.name}", color="blue")

        if not WHISPER_IS_READY:
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Whisper không sẵn sàng. Giả lập transcript.", color="red")
            yield "Đây là transcript giả lập khi Whisper lỗi"
            return
            
        try:
            audio = whisper.load_audio(str(audio_filepath))
            
            # Sử dụng asyncio.to_thread để chạy Whisper (tác vụ Blocking I/O)
            result = await asyncio.to_thread(self.model.transcribe, audio)
            final_transcript = result.get("text", "").strip()
            
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Transcript: '{final_transcript}'", color="blue")
            
            yield final_transcript
            
        except Exception as e:
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ❌ [ASR] LỖI WHISPER: {e}", color="red")
            # In traceback chi tiết nếu lỗi
            self._log(traceback.format_exc(), color="red")
            yield "" 

class ASRServiceMock:
    """Giả lập dịch vụ ASR."""
    def __init__(self, log_callback: Callable):
        self._log = log_callback 
        self.full_transcript = "Xin cho tôi đặt một đơn hàng cuối cùng" 

    async def transcribe(self, audio_filepath: Path) -> AsyncGenerator[str, None]:
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR MOCK] Bắt đầu xử lý luồng âm thanh...", color="blue")
        
        await asyncio.sleep(0.5) 
        
        transcript = self.full_transcript
        for i, word in enumerate(transcript.split()):
            yield word + (" " if i < len(transcript.split()) - 1 else "")
            
# ==================== DỊCH VỤ TTS (Vẫn là Mock) ====================

class TTSServiceMock:
    """Giả lập dịch vụ TTS, nhận text và trả về luồng audio (bytes)."""
    def __init__(self, log_callback: Callable):
        self._log = log_callback
        
    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS MOCK] Bắt đầu tổng hợp âm thanh cho: '{text[:30]}...'", color="magenta")
        
        mock_chunk_size = 320 
        mock_chunk = os.urandom(mock_chunk_size) 
        num_chunks = int(len(text) * 0.5) + 10 
        num_chunks = max(30, min(100, num_chunks)) 
        
        for _ in range(num_chunks):
            yield mock_chunk
            await asyncio.sleep(0.005) 
            
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS MOCK] Kết thúc luồng audio TTS ({num_chunks} chunks).", color="magenta")

# ==================== LỚP XỬ LÝ RTC TÍCH HỢP ====================

class RTCStreamProcessor:
    
    @staticmethod
    async def _record_stream(audio_input_stream: AsyncGenerator[bytes, None], record_file: Path) -> Path:
        """Ghi audio input vào file WAV và trả về đường dẫn file."""
        
        # CHÚ Ý: Mở file I/O blocking trong Async function là không nên, 
        # nhưng wave.open không có phiên bản async, ta chấp nhận điều này 
        # vì nó chỉ diễn ra một lần sau khi luồng kết thúc.
        wf = wave.open(str(record_file), 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2) 
        wf.setframerate(SAMPLE_RATE)
        
        # Vòng lặp nhận audio chunks là async
        async for chunk in audio_input_stream:
            wf.writeframes(chunk) # Lỗi ở đây sẽ được bắt bởi try/except bên ngoài
            
        wf.close()
        return record_file
    
    def __init__(self, log_callback: Optional[Callable] = None):
        def default_log(message, color=None):
            print(f"[{_dt.now().strftime('%H:%M:%S')}] [LOG] {message}")

        self._log = log_callback if log_callback else default_log

        if WHISPER_IS_READY:
            self._asr_client = ASRServiceWhisper(self._log, WHISPER_MODEL)
            self._asr_mode = "WHISPER"
        else:
            self._asr_client = ASRServiceMock(self._log)
            self._asr_mode = "MOCK"

        # Tích hợp DialogManager và TTS Mock
        self._dm = DialogManager(log_callback=self._log, mode="RTC") 
        self._tts_client = TTSServiceMock(self._log)

    async def handle_rtc_session(self, 
                                 audio_input_stream: AsyncGenerator[bytes, None],
                                 session_id: str) \
                                 -> AsyncGenerator[Tuple[bool, Any], None]:
        
        self._log("▶️ [RTC] Bắt đầu phiên RTC...", color="cyan")
        
        record_file = RECORDING_DIR / f"{session_id}_input.wav"
        full_transcript = ""
        response_text = "Xin lỗi, tôi chưa thể xử lý yêu cầu."
        
        # ⚠️ KHỐI TRY LỚN: Bao bọc toàn bộ logic phiên để đảm bảo finally chạy
        try: 
            # 1. Ghi âm thanh vào file WAV
            try:
                # Ghi luồng audio, đợi cho đến khi hết luồng
                await self._record_stream(audio_input_stream, record_file)
                self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 💾 [Recorder] Đã lưu audio input vào: {record_file.name}", color="orange")
            except Exception as e:
                self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ❌ [Recorder] Lỗi ghi file: {e}", color="red")
                # In traceback cho lỗi I/O
                self._log(traceback.format_exc(), color="red")
                record_file = None # Đặt lại file thành None nếu có lỗi

            # **********************************************
            # 2. Xử lý ASR, NLU, TTS (Chỉ chạy nếu có file)
            # **********************************************
            if record_file and os.path.exists(record_file):
                # 2. Xử lý ASR
                asr_stream = self._asr_client.transcribe(record_file)
                async for partial_text in asr_stream:
                     if partial_text:
                         full_transcript = partial_text

                # 3. NLU/Response Logic - TÍCH HỢP DIALOG MANAGER
                if full_transcript.strip():
                    dm_result = self._dm.process_audio_path(str(record_file), user_input_asr=full_transcript)
                else:
                    dm_result = self._dm.process_audio_path(str(record_file), user_input_asr="[NO SPEECH DETECTED]")
                    dm_result['response_text'] = "Xin lỗi, tôi không nghe rõ. Bạn có thể nói lại không?"
                    
                response_text = dm_result.get("response_text", response_text)
                
                self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🧠 [DM] Transcript: '{full_transcript[:30]}...' -> Response: '{response_text[:30]}...'", color="green")

                # YIELD TEXT METADATA ĐỂ GHI VÀO CHAT BOX
                yield (False, {"user_text": full_transcript, "bot_text": response_text})

                # 4. TTS và Trả về Luồng Audio
                tts_audio_stream = self._tts_client.synthesize_stream(response_text)
                
                # YIELD AUDIO CHUNKS
                async for audio_chunk in tts_audio_stream:
                    yield (True, audio_chunk)
        
        except Exception as e:
            # Bắt các lỗi không lường trước xảy ra trong quá trình ASR/NLU/TTS
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ❌ [RTC] LỖI XỬ LÝ CHUNG: {e}", color="red")
            self._log(traceback.format_exc(), color="red")

        # ⚠️ KHỐI FINALLY: Đảm bảo luồng dọn dẹp chạy
        finally: 
             self._log(f"[{_dt.now().strftime('%H:%M:%S')}] [RTC] Kết thúc xử lý RTC. (File: {record_file.name if record_file else 'None'})", color="cyan")