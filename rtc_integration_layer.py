# rtc_integration_layer.py - ĐÃ FIX LỖI BLOCKING CHO VAD/ASR/DM
import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional, Tuple, Any
from datetime import datetime as _dt
import numpy as np 
import torch 
import traceback 
import time 
import wave 

# --- SAFE IMPORTS (DIALOG MANAGER) ---
try:
    from dialog_manager import DialogManager 
except ImportError:
    class DialogManager:
        def __init__(self, *args, **kwargs): pass
        def process_audio_file(self, record_file, user_input_asr): 
            # Giả lập hàm đồng bộ
            return {"response_text": f"LỖI DM: Không tìm thấy DialogManager. ASR: {user_input_asr}", "response_audio_path": None, "user_input_asr": user_input_asr}

# --- Hằng số ---
try:
    from config_db import WHISPER_MODEL_NAME, SAMPLE_RATE
except ImportError:
    WHISPER_MODEL_NAME = "tiny" 
    SAMPLE_RATE = 16000 

RECORDING_DIR = Path("rtc_recordings"); RECORDING_DIR.mkdir(exist_ok=True) 

# ----------------------------------------------------------------------
# VAD/ASR IMPORTS
# ----------------------------------------------------------------------
WHISPER_IS_READY = False
try:
    import whisper
    import torchaudio 
        
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    USE_FP16 = (DEVICE == "cuda") 
    
    print(f"✅ [ASR] Thiết bị được chọn: {DEVICE}. Whisper model: '{WHISPER_MODEL_NAME}'. FP16: {USE_FP16}", flush=True)

    VAD_MODEL, VAD_UTILS = torch.hub.load(
        repo_or_dir='snakers4/silero-vad',
        model='silero_vad',
        force_reload=False,
        onnx=False
    )
    VAD_MODEL = VAD_MODEL.to(DEVICE)
    
    (get_speech_timestamps, save_audio, read_audio, VAD_collect_chunks, *vad_extra_utils) = VAD_UTILS 
    print("✅ [VAD] Silero VAD đã được tải thành công.", flush=True)

    WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME, device=DEVICE) 
    WHISPER_IS_READY = True
except Exception as e:
    DEVICE = "cpu"
    WHISPER_MODEL = None
    print(f"❌ [ASR] Lỗi tải Whisper/VAD: {e}. Sử dụng Mock. Vui lòng kiểm tra cài đặt PyTorch/Whisper/torchaudio.", flush=True)


# ==================== VAD HELPER (Lọc Tạp Âm) ====================

def _apply_silero_vad(audio_filepath: Path, log_callback: Callable) -> Optional[np.ndarray]:
    """Sử dụng Silero VAD để phát hiện và cắt bỏ các khoảng lặng."""
    if not WHISPER_IS_READY: return None
        
    try:
        audio_tensor = read_audio(str(audio_filepath), sampling_rate=SAMPLE_RATE)
        
        speech_timestamps = get_speech_timestamps(
            audio_tensor.to(DEVICE), 
            VAD_MODEL, 
            sampling_rate=SAMPLE_RATE, 
            threshold=0.3 
        )
        if not speech_timestamps:
            log_callback("⚠️ [VAD] Không tìm thấy hoạt động giọng nói (speech) trong file.", color="orange")
            return None 

        speech_audio_tensor = VAD_collect_chunks(speech_timestamps, audio_tensor)
        speech_audio_numpy = speech_audio_tensor.cpu().numpy()
        
        original_duration = len(audio_tensor) / SAMPLE_RATE
        filtered_duration = len(speech_audio_numpy) / SAMPLE_RATE
        
        log_callback(f"✅ [VAD] Lọc thành công. Gốc: {original_duration:.2f}s -> VAD: {filtered_duration:.2f}s.", color="blue")
        
        return speech_audio_numpy
    
    except Exception as e:
        log_callback(f"❌ [VAD] LỖI khi áp dụng Silero VAD: {e}. Fallback về audio gốc.", color="red")
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
            
            # FIX: GỌI VAD BẰNG asyncio.to_thread để tránh chặn luồng chính
            audio_input = await asyncio.to_thread(
                _apply_silero_vad, audio_filepath, self._log
            )
            
            if audio_input is None or (isinstance(audio_input, np.ndarray) and audio_input.size == 0):
                self._log("⚠️ [ASR] Không có dữ liệu audio để xử lý.", color="orange")
                yield ""
                return
            
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Bắt đầu xử lý Whisper trên {DEVICE}...", color="blue")

            # CHẠY WHISPER TRONG THREADPOOL
            result = await asyncio.to_thread(
                self.model.transcribe, 
                audio_input, 
                device=DEVICE, 
                language="vi", 
                fp16=USE_FP16 
            )
            final_transcript = result.get("text", "").strip()
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ✅ [ASR] Hoàn thành. Transcript: '{final_transcript}'. Thời gian: {processing_time:.2f}s", color="blue")
            
            yield final_transcript
            
        except asyncio.CancelledError:
             raise
        except Exception as e:
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ❌ [ASR] LỖI WHISPER: {e}", color="red")
            self._log(traceback.format_exc(), color="red")
            yield "" 

class TTSServiceMock:
    def __init__(self, log_callback: Callable): self._log = log_callback
    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS MOCK] Bắt đầu tổng hợp âm thanh...", color="magenta")
        mock_chunk_size = 320 
        mock_chunk = os.urandom(mock_chunk_size) 
        num_chunks = max(30, min(100, int(len(text) * 0.5) + 10)) 
        for _ in range(num_chunks):
            yield mock_chunk
            await asyncio.sleep(0.005) 
        self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS MOCK] Kết thúc luồng audio TTS.", color="magenta")

# ==================== LỚP XỬ LÝ RTC TÍCH HỢP ====================

class RTCStreamProcessor:
    
    def __init__(self, log_callback: Optional[Callable] = None):
        def default_log(message, color=None):
            print(f"[{_dt.now().strftime('%H:%M:%S')}] [LOG] {message}", flush=True)

        self._log = log_callback if log_callback else default_log

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
        
        self._log(f"▶️ [RTC] Bắt đầu phiên xử lý ASR/NLU. Session ID: {session_id}. File: {record_file.name}", color="cyan") 
        
        full_transcript = ""
        response_text = "Xin lỗi, tôi chưa thể xử lý yêu cầu."
        
        try: 
            # 1. Xử lý ASR (Bao gồm VAD)
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Bắt đầu gọi ASR Service...", color="yellow")
            asr_stream = self._asr_client.transcribe(record_file)
            async for partial_text in asr_stream:
                 if partial_text:
                     full_transcript = partial_text
                     
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎙️ [ASR] Transcript nhận được: '{full_transcript[:50]}...'", color="green")

            # 2. NLU/Response Logic - TÍCH HỢP DIALOG MANAGER
            dm_input_asr = full_transcript.strip() if full_transcript.strip() else "[NO SPEECH DETECTED]"
            
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🧠 [DM] Bắt đầu xử lý DialogManager (Chuyển sang luồng phụ)...", color="yellow")
            
            # ✅ FIX: GỌI HÀM ĐỒNG BỘ CỦA DIALOG MANAGER TRONG THREADPOOL
            dm_result = await asyncio.to_thread(
                self._dm.process_audio_file, 
                str(record_file), 
                user_input_asr=dm_input_asr
            )
                
            response_text = dm_result.get("response_text", response_text)
            
            if dm_input_asr == "[NO SPEECH DETECTED]":
                 response_text = "Xin lỗi, tôi không nghe rõ. Bạn có thể nói lại không?"

            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🧠 [DM] Hoàn tất. Response: '{response_text[:50]}...' (mode: {self._asr_mode})", color="green")


            yield (False, {"user_text": full_transcript, "bot_text": response_text})

            # 3. TTS và Trả về Luồng Audio
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] 🎵 [TTS] Bắt đầu streaming audio phản hồi...", color="magenta")
            tts_audio_stream = self._tts_client.synthesize_stream(response_text)
            async for audio_chunk in tts_audio_stream:
                yield (True, audio_chunk)
        
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._log(f"[{_dt.now().strftime('%H:%M:%S')}] ❌ [RTC] LỖI XỬ LÝ CHUNG: {e}", color="red")
            self._log(traceback.format_exc(), color="red")
        finally: 
             self._log(f"[{_dt.now().strftime('%H:%M:%S')}] [RTC] Kết thúc xử lý RTC.", color="cyan")