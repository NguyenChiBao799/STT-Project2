# rtc_integration_layer.py
import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional, Tuple, Any, Dict, ClassVar
from datetime import datetime as _dt
import numpy as np 
import torch 
import traceback 
import time 
import base64
import httpx 
import whisper # Cần cài đặt thư viện Whisper
from concurrent.futures import ThreadPoolExecutor

# --- Cấu hình API Nội bộ ---
INTERNAL_UPLOAD_URL = "http://internal.company.api/v1/voice_logs/upload" 
INTERNAL_API_KEY = "YOUR_DEFAULT_INTERNAL_API_KEY_HERE" 
# ----------------------------------------------------------------------

# --- SAFE IMPORTS (CONFIG, DIALOG MANAGER VÀ RESPONSE GENERATOR) ---
try:
    from config_db import WHISPER_MODEL_NAME, SAMPLE_RATE 
    from dialog_manager import DialogManager 
    from response_generator import ResponseGenerator # ResponseGenerator được DialogManager sử dụng
except ImportError:
    # Fallback/Mock nếu không tìm thấy các lớp cốt lõi
    WHISPER_MODEL_NAME = "tiny" 
    SAMPLE_RATE = 16000
    class ResponseGenerator:
        def __init__(self, *args, **kwargs): pass
    class DialogManager:
        def __init__(self, *args, **kwargs): pass
        def process_audio_file(self, record_file, user_input_asr): 
            res_text = f"LỖI DM: Không tìm thấy DialogManager. ASR: {user_input_asr}"
            if "[NO SPEECH DETECTED]" in user_input_asr:
                 res_text = "Xin lỗi, tôi không nghe rõ. Bạn có thể nói lại không?"
            return {"response_text": res_text, "response_audio_path": None, "user_input_asr": user_input_asr}


RECORDING_DIR = Path("rtc_recordings"); RECORDING_DIR.mkdir(exist_ok=True) 

def _log_colored(message, color="white"):
    color_map = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m", 
        "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m", "white": "\033[97m", "orange": "\033[33m"
    }
    RESET = "\033[0m"
    print(f"{color_map.get(color, RESET)}{message}{RESET}", flush=True)


# ==================== VAD/ASR LOGIC ====================
WHISPER_IS_READY = False
try:
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    USE_FP16 = (DEVICE == "cuda") 
    
    # Tải VAD (Silero)
    VAD_MODEL, VAD_UTILS = torch.hub.load(
        repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False, onnx=False, trust_repo=True 
    )
    VAD_MODEL = VAD_MODEL.to(DEVICE)
    (get_speech_timestamps, save_audio, read_audio, VAD_collect_chunks, *vad_extra_utils) = VAD_UTILS 
    
    # Tải Whisper
    WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME)
    if USE_FP16: WHISPER_MODEL = WHISPER_MODEL.half()
    WHISPER_MODEL.to(DEVICE)
    WHISPER_IS_READY = True
except Exception as e:
    DEVICE = "cpu"
    WHISPER_MODEL = None
    _log_colored(f"❌ Lỗi khởi tạo ASR/VAD (Whisper/Torch): {e}", "red")

def _apply_silero_vad(audio_filepath: Path, log_callback: Callable) -> Optional[np.ndarray]:
    """Áp dụng VAD để loại bỏ khoảng lặng."""
    if not WHISPER_IS_READY: return None
    try:
        audio_numpy = whisper.load_audio(str(audio_filepath))
        audio_tensor = torch.from_numpy(audio_numpy).float()
        speech_timestamps = get_speech_timestamps(audio_tensor.to(DEVICE), VAD_MODEL, sampling_rate=SAMPLE_RATE, threshold=0.3)
        if not speech_timestamps: return None 
        speech_audio_tensor = VAD_collect_chunks(speech_timestamps, audio_tensor)
        speech_audio_numpy = speech_audio_tensor.cpu().numpy()
        MIN_SPEECH_DURATION_SECONDS = 0.5
        filtered_duration = len(speech_audio_numpy) / SAMPLE_RATE
        if filtered_duration < MIN_SPEECH_DURATION_SECONDS: return None 
        return speech_audio_numpy
    except Exception:
        return whisper.load_audio(str(audio_filepath))

class ASRServiceWhisper:
    def __init__(self, log_callback: Callable, model):
        self._log = log_callback 
        self.model = model
    async def transcribe(self, audio_filepath: Path) -> AsyncGenerator[str, None]:
        if not WHISPER_IS_READY: yield ""; return
        try:
            audio_input = await asyncio.to_thread(_apply_silero_vad, audio_filepath, self._log)
            if audio_input is None: yield "[NO SPEECH DETECTED]"; return
            result = await asyncio.to_thread(self.model.transcribe, audio_input, language="vi", fp16=USE_FP16)
            yield result.get("text", "").strip()
        except Exception as e:
            self._log(f"❌ [ASR] LỖI WHISPER: {e}", "red")
            yield "" 

# ==================== DỊCH VỤ UPLOAD AUDIO ====================

async def _upload_audio_to_internal_api(file_path: Path, session_id: str, log_callback: Callable, api_key: str = INTERNAL_API_KEY):
    """Giả lập/thực hiện upload file audio lên API nội bộ."""
    if str(INTERNAL_UPLOAD_URL).startswith("http://internal.company.api"):
        log_callback("⚠️ [UPLOAD] Bỏ qua upload: URL vẫn là placeholder.", "orange")
        return False
        
    try:
        log_callback(f"[{_dt.now().strftime('%H:%M:%S')}] 📤 [UPLOAD] Bắt đầu upload file: {file_path.name}...", "yellow")
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client: 
            with open(file_path, 'rb') as f:
                files = {'file': (file_path.name, f, 'audio/wav')}
                headers = {'X-API-Key': api_key, 'X-Session-ID': session_id} 
                response = await client.post(INTERNAL_UPLOAD_URL, files=files, headers=headers)
                response.raise_for_status() 
                log_callback(f"[{_dt.now().strftime('%H:%M:%S')}] ✅ [UPLOAD] Upload thành công!", "green")
                return True
    except Exception as e:
        log_callback(f"[{_dt.now().strftime('%H:%M:%S')}] ❌ [UPLOAD] LỖI UPLOAD: {e}", "red")
        return False

# ==================== DỊCH VỤ TTS (Mock Streaming) ====================

class TTSServiceMock:
    """Mock TTS tạo chunk base64 để streaming."""
    def __init__(self, log_callback: Callable): self._log = log_callback
    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS MOCK] Bắt đầu tổng hợp âm thanh...", "magenta")
        # Giả lập chunk audio 10ms (16000 sample/s * 2 bytes/sample * 1 kênh * 0.01s = 320 bytes)
        mock_chunk_size = 320 
        num_chunks = max(30, min(100, int(len(text) * 0.5) + 10)) 
        
        for _ in range(num_chunks):
            # Giả lập Base64 encoded chunk
            mock_chunk = base64.b64encode(os.urandom(mock_chunk_size)) 
            yield mock_chunk 
            await asyncio.sleep(0.005) # Giả lập độ trễ streaming
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS MOCK] Kết thúc luồng audio TTS.", "magenta")

# ==================== LỚP XỬ LÝ RTC TÍCH HỢP MỚI (Đã sửa đổi) ====================

class RTCStreamProcessor:
    
    def __init__(self, log_callback: Optional[Callable] = None):
        # Đảm bảo sử dụng _log
        self._log = log_callback if log_callback else _log_colored
        self._asr_client = ASRServiceWhisper(self._log, WHISPER_MODEL) if WHISPER_IS_READY else type('ASRMock', (object,), {'transcribe': lambda self, fp: (yield "Transcript giả lập.")})()
        self._tts_client = TTSServiceMock(self._log)
        # Sử dụng ThreadPoolExecutor để chạy các tác vụ đồng bộ (DM)
        self._executor = ThreadPoolExecutor(max_workers=1)
    
    async def handle_rtc_session(self, 
                                 record_file: Path,
                                 session_id: str,
                                 api_key: str) \
                                 -> AsyncGenerator[Tuple[bool, Any], None]:
        
        self._log(f"▶️ [RTC] Bắt đầu phiên xử lý ASR/NLU. Session ID: {session_id}.", "cyan") 
        full_transcript = ""
        response_text = "Xin lỗi, tôi chưa thể xử lý yêu cầu."
        
        try: 
            # KHỞI TẠO DIALOG MANAGER VỚI API KEY
            dm_instance = DialogManager(log_callback=self._log, mode="RTC", api_key=api_key) 
            
            yield (False, {"type": "generator_init", "user_text": "", "bot_text": ""}) 
            
            # 1. UPLOAD AUDIO (Bất đồng bộ)
            await _upload_audio_to_internal_api(record_file, session_id, self._log, api_key)
            
            # 2. [ASR Engine] (Bất đồng bộ)
            asr_stream = self._asr_client.transcribe(record_file)
            async for partial_text in asr_stream:
                 if partial_text: full_transcript = partial_text
                     
            dm_input_asr = full_transcript.strip() if full_transcript.strip() and partial_text != "[NO SPEECH DETECTED]" else "[NO SPEECH DETECTED]"
            
            # 3-5. [Dialog Manager] (Đồng bộ)
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🧠 [DM/NLU] Bắt đầu xử lý DialogManager...", "yellow")
            
            # SỬA LỖI 1: Thay keyword argument thành positional argument
            dm_result = await asyncio.get_event_loop().run_in_executor(
                 self._executor,
                 dm_instance.process_audio_file, 
                 str(record_file), 
                 dm_input_asr # <--- POSITIONAL ARGUMENT
            )
            response_text = dm_result.get("response_text", response_text)

            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🧠 [DM] Hoàn tất. Response: '{response_text[:50]}...'", "green")

            yield (False, {"user_text": full_transcript.strip(), "bot_text": response_text})

            # 6. [TTS Engine] -> [Speaker Output] (Stream)
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS] Bắt đầu streaming audio phản hồi...", "magenta")
            tts_audio_stream = self._tts_client.synthesize_stream(response_text)
            async for audio_chunk in tts_audio_stream:
                yield (True, audio_chunk)
        
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ❌ [RTC] LỖI XỬ LÝ CHUNG: {e}", "red")
            # SỬA LỖI 2: self.log -> self._log
            self._log(traceback.format_exc(), "red") 
            yield (False, {"type": "error", "user_text": full_transcript.strip(), "bot_text": f"Lỗi hệ thống: {e}"})
        finally: 
             self._log(f"[{_dt.now().strftime('%H:%M:%S')}] [RTC] Kết thúc xử lý RTC.", "cyan")