# rtc_integration_layer.py - PHIÊN BẢN ĐÃ SỬA LỖI DỨT ĐIỂM NoneType
import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional, Tuple, Any
from datetime import datetime as _dt
import numpy as np 
import torch 
import traceback 
import time 
import base64

# --- SAFE IMPORTS (DIALOG MANAGER) ---
try:
    from dialog_manager import DialogManager 
except ImportError:
    class DialogManager:
        def __init__(self, *args, **kwargs): pass
        def process_audio_file(self, record_file, user_input_asr): 
            return {"response_text": f"LỖI DM: Không tìm thấy DialogManager. ASR: {user_input_asr}", "response_audio_path": None, "user_input_asr": user_input_asr}

# --- Hằng số ---
try:
    from config_db import WHISPER_MODEL_NAME, SAMPLE_RATE 
except ImportError:
    WHISPER_MODEL_NAME = "tiny" 
    SAMPLE_RATE = 16000 

RECORDING_DIR = Path("rtc_recordings"); RECORDING_DIR.mkdir(exist_ok=True) 

def _log_colored(message, color="white"):
    color_map = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m", 
        "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m", "white": "\033[97m"
    }
    RESET = "\033[0m"
    print(f"{color_map.get(color, RESET)}{message}{RESET}", flush=True)


# ----------------------------------------------------------------------
# VAD/ASR IMPORTS
# ----------------------------------------------------------------------
WHISPER_IS_READY = False
try:
    import whisper
    import torchaudio 
        
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    USE_FP16 = (DEVICE == "cuda") 
    
    _log_colored(f"✅ [ASR] Thiết bị được chọn: {DEVICE}. Whisper model: '{WHISPER_MODEL_NAME}'. FP16: {USE_FP16}", "blue")

    # VAD Load Model
    VAD_MODEL, VAD_UTILS = torch.hub.load(
        repo_or_dir='snakers4/silero-vad',
        model='silero_vad',
        force_reload=False,
        onnx=False,
        trust_repo=True 
    )
    VAD_MODEL = VAD_MODEL.to(DEVICE)
    
    (get_speech_timestamps, save_audio, read_audio, VAD_collect_chunks, *vad_extra_utils) = VAD_UTILS 
    _log_colored("✅ [VAD] Silero VAD đã được tải thành công.", "blue")

    # WHISPER Load Model và Tối ưu FP16
    WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME)
    if USE_FP16:
        WHISPER_MODEL = WHISPER_MODEL.half()
    
    WHISPER_MODEL.to(DEVICE)
    WHISPER_IS_READY = True
    
except Exception as e:
    DEVICE = "cpu"
    WHISPER_MODEL = None
    _log_colored(f"❌ [ASR] Lỗi tải Whisper/VAD: {e}. Sử dụng Mock.", "red")
    _log_colored(traceback.format_exc(), "red") 


# ==================== VAD HELPER (Lọc Tạp Âm) ====================

def _apply_silero_vad(audio_filepath: Path, log_callback: Callable) -> Optional[np.ndarray]:
    if not WHISPER_IS_READY: return None
        
    try:
        audio_numpy = whisper.load_audio(str(audio_filepath))
        audio_tensor = torch.from_numpy(audio_numpy).float()
        
        speech_timestamps = get_speech_timestamps(
            audio_tensor.to(DEVICE), 
            VAD_MODEL, 
            sampling_rate=SAMPLE_RATE, 
            # ĐIỀU CHỈNH: Giảm ngưỡng về 0.3 để bắt giọng nói từ loa máy tính
            threshold=0.3 
        )
        if not speech_timestamps:
            log_callback("⚠️ [VAD] Không tìm thấy hoạt động giọng nói (speech) trong file.", "orange")
            return None 

        speech_audio_tensor = VAD_collect_chunks(speech_timestamps, audio_tensor)
        speech_audio_numpy = speech_audio_tensor.cpu().numpy()
        
        original_duration = len(audio_tensor) / SAMPLE_RATE
        filtered_duration = len(speech_audio_numpy) / SAMPLE_RATE
        
        MIN_SPEECH_DURATION_SECONDS = 0.5
        if filtered_duration < MIN_SPEECH_DURATION_SECONDS:
             log_callback(f"⚠️ [VAD] Audio đã lọc quá ngắn ({filtered_duration:.2f}s < {MIN_SPEECH_DURATION_SECONDS}s). Coi là tạp âm.", "orange")
             return None 

        log_callback(f"✅ [VAD] Lọc thành công. Gốc: {original_duration:.2f}s -> VAD: {filtered_duration:.2f}s.", "blue")
        
        return speech_audio_numpy
    
    except Exception as e:
        log_callback(f"❌ [VAD] LỖI khi áp dụng Silero VAD: {e}. Fallback về audio gốc.", "red")
        log_callback(traceback.format_exc(), "red") 
        return whisper.load_audio(str(audio_filepath))


# ==================== CÁC DỊCH VỤ ASR ====================

class ASRServiceWhisper:
    def __init__(self, log_callback: Callable, model):
        self._log = log_callback 
        self.model = model
        
    async def transcribe(self, audio_filepath: Path) -> AsyncGenerator[str, None]:
        if not WHISPER_IS_READY: yield ""; return
            
        try:
            start_time = time.time()
            
            # VAD được áp dụng trong threadpool trước khi gọi Whisper
            audio_input = await asyncio.to_thread(
                _apply_silero_vad, audio_filepath, self._log
            )
            
            if audio_input is None or (isinstance(audio_input, np.ndarray) and audio_input.size == 0):
                self._log("⚠️ [ASR] Không có dữ liệu audio để xử lý.", "orange")
                yield ""
                return
            
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Bắt đầu xử lý Whisper trên {DEVICE}...", "blue")

            result = await asyncio.to_thread(
                self.model.transcribe, 
                audio_input, 
                language="vi", 
                fp16=USE_FP16 
            )
            final_transcript = result.get("text", "").strip()
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ✅ [ASR] Hoàn thành. Transcript: '{final_transcript}'. Thời gian: {processing_time:.2f}s", "blue")
            
            yield final_transcript
            
        except asyncio.CancelledError:
             raise
        except Exception as e:
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ❌ [ASR] LỖI WHISPER: {e}", "red")
            self._log(traceback.format_exc(), "red") 
            yield "" 

class TTSServiceMock:
    def __init__(self, log_callback: Callable): self._log = log_callback
    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS MOCK] Bắt đầu tổng hợp âm thanh...", "magenta")
        mock_chunk_size = 320 
        mock_chunk = base64.b64encode(os.urandom(mock_chunk_size)) 
        
        num_chunks = max(30, min(100, int(len(text) * 0.5) + 10)) 
        for _ in range(num_chunks):
            yield mock_chunk 
            await asyncio.sleep(0.005) 
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS MOCK] Kết thúc luồng audio TTS.", "magenta")

# ==================== LỚP XỬ LÝ RTC TÍCH HỢP ====================

class RTCStreamProcessor:
    
    def __init__(self, log_callback: Optional[Callable] = None):
        self._log = log_callback if log_callback else _log_colored

        if WHISPER_IS_READY:
            self._asr_client = ASRServiceWhisper(self._log, WHISPER_MODEL)
            self._asr_mode = "WHISPER"
        else:
            class ASRServiceMock:
                def __init__(self, log_callback): self._log = log_callback
                async def transcribe(self, audio_filepath: Path): yield "Transcript giả lập."
            self._asr_client = ASRServiceMock(self._log)
            self._asr_mode = "MOCK"

        self._dm = DialogManager(log_callback=self._log, mode="RTC") 
        self._tts_client = TTSServiceMock(self._log)

    async def handle_rtc_session(self, 
                                 record_file: Path,
                                 session_id: str) \
                                 -> AsyncGenerator[Tuple[bool, Any], None]:
        
        self._log(f"▶️ [RTC] Bắt đầu phiên xử lý ASR/NLU. Session ID: {session_id}. File: {record_file.name}", "cyan") 
        
        full_transcript = ""
        response_text = "Xin lỗi, tôi chưa thể xử lý yêu cầu."
        
        try: 
            yield (False, {"type": "generator_init", "user_text": "", "bot_text": ""}) 
            
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Bắt đầu gọi ASR Service...", "yellow")
            asr_stream = self._asr_client.transcribe(record_file)
            async for partial_text in asr_stream:
                 if partial_text:
                     full_transcript = partial_text
                     
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Transcript nhận được: '{full_transcript[:50]}...'", "green")

            dm_input_asr = full_transcript.strip() if full_transcript.strip() else "[NO SPEECH DETECTED]"
            
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🧠 [DM] Bắt đầu xử lý DialogManager (Chuyển sang luồng phụ)...", "yellow")
            
            dm_result = await asyncio.to_thread(
                self._dm.process_audio_file, 
                str(record_file), 
                user_input_asr=dm_input_asr
            )
                
            response_text = dm_result.get("response_text", response_text)
            
            if dm_input_asr == "[NO SPEECH DETECTED]":
                 response_text = "Xin lỗi, tôi không nghe rõ. Bạn có thể nói lại không?"

            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🧠 [DM] Hoàn tất. Response: '{response_text[:50]}...' (mode: {self._asr_mode})", "green")


            yield (False, {"user_text": full_transcript, "bot_text": response_text})

            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS] Bắt đầu streaming audio phản hồi...", "magenta")
            tts_audio_stream = self._tts_client.synthesize_stream(response_text)
            async for audio_chunk in tts_audio_stream:
                yield (True, audio_chunk)
        
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # ✅ FIX: PHẢI YIELD trong khối except để tránh lỗi NoneType khi hàm generator kết thúc không hợp lệ
            full_transcript = full_transcript if full_transcript else "[ERROR_DURING_INIT]"
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ❌ [RTC] LỖI XỬ LÝ CHUNG: {e}", "red")
            self._log(traceback.format_exc(), "red") 
            
            error_message = f"Lỗi xử lý. Chi tiết: {e.__class__.__name__}"
            yield (False, {"user_text": full_transcript, "bot_text": error_message}) 

        finally: 
             self._log(f"[{_dt.now().strftime('%H:%M:%S')}] [RTC] Kết thúc xử lý RTC.", "cyan")