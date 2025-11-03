import asyncio
import os
import json
import uuid
import wave
import time 
from typing import Dict, Any, Optional, Callable
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel
from aiortc.exceptions import InvalidStateError
import numpy as np
from rtc_integration_layer import RTCStreamProcessor, SAMPLE_RATE 

# Giả định import DialogManager
try:
    from dialog_manager import DialogManager
except ImportError:
    class DialogManager:
        def __init__(self, *args, **kwargs): pass
        def process_audio_file(self, *args, **kwargs): return {}

# Hằng số Audio
CHANNELS = 1
SAMPLE_WIDTH = 2 
os.makedirs("temp", exist_ok=True) 

# FIX LOG: Chỉ dùng print, dựa vào lệnh chạy -u để flush.
def log_info(message, color="white"):
    print(f"INFO:backend_webrtc_server:[{message}]")

# ======================================================
# LỚP GHI ÂM THỰC TẾ (FIX: INTERNAL BUFFERING)
# ======================================================
class AudioFileRecorder:
    """Class ghi luồng audio từ aiortc track vào file WAV."""
    def __init__(self, pc):
        self._pc = pc
        self._on_stop_callback: Optional[Callable] = None
        self._track = None
        self._path = None
        self._chunks_recorded = 0
        self._is_recording = False
        self._record_task: Optional[asyncio.Task] = None
        
        # ✅ FIX: Internal Buffer và Kích thước Chunk (30 frames * 10ms = 300ms)
        self._buffer = bytearray()
        self._chunk_size_frames = 30 
        self._wav_file = None # Sẽ được mở trong luồng phụ khi ghi chunk

    def on(self, event, callback):
        if event == "stop":
            self._on_stop_callback = callback
            
    # Hàm ghi WAV đồng bộ (chạy trong Thread)
    def _write_chunk_sync(self, data: bytes):
        if not self._wav_file:
             # Mở file trong thread I/O lần đầu tiên được gọi
            self._wav_file = wave.open(self._path, 'wb')
            self._wav_file.setnchannels(CHANNELS)
            self._wav_file.setsampwidth(SAMPLE_WIDTH)
            self._wav_file.setframerate(SAMPLE_RATE)
            
        self._wav_file.writeframes(data)


    def start(self, track, path):
        if self._is_recording: return
        self._is_recording = True
        self._track = track
        self._path = path
        
        try:
            self._record_task = asyncio.create_task(self._record_loop())
            log_info(f"[Recorder] Bắt đầu ghi âm vào file (Internal Buffering): {path}") 
        except Exception as e:
            log_info(f"❌ [Recorder] Lỗi khi tạo task ghi âm: {e}")
            self._is_recording = False


    async def _record_loop(self):
        frame_counter = 0
        while self._is_recording:
            try:
                frame = await self._track.recv() 
                audio_data_np = frame.to_ndarray() 
                
                if audio_data_np.dtype == np.float32:
                    audio_data_np = (audio_data_np * 32767).astype(np.int16)
                elif audio_data_np.dtype != np.int16:
                     audio_data_np = audio_data_np.astype(np.int16)

                audio_data_bytes = audio_data_np.tobytes()
                
                # Thêm vào buffer
                self._buffer.extend(audio_data_bytes)
                frame_counter += 1
                
                # Ghi khối lớn nếu đủ frames
                if frame_counter >= self._chunk_size_frames:
                    data_to_write = bytes(self._buffer)
                    self._buffer = bytearray()
                    frame_counter = 0
                    self._chunks_recorded += 1
                    
                    # ✅ FIX: Chuyển khối lớn (300ms) sang Thread. Giảm tần suất gọi to_thread 30 lần.
                    await asyncio.to_thread(self._write_chunk_sync, data_to_write)
            
            except StopAsyncIteration:
                self._is_recording = False 
                log_info(f"[Recorder] 🛑 Dừng nhận luồng audio từ Frontend (StopAsyncIteration). Kích hoạt xử lý.", color="orange")
                break
            except InvalidStateError:
                self._is_recording = False 
                break
            except Exception as e:
                log_info(f"❌ [Recorder] Lỗi không mong muốn: {e}", color="red")
                self._is_recording = False 
                break
            
            # Giải phóng vòng lặp sau mỗi frame (10ms) để nhận tín hiệu dừng
            await asyncio.sleep(0) 
        
        if not self._is_recording:
            self.stop() 


    def stop(self):
        if not self._path: return
            
        _was_recording = self._is_recording
        self._is_recording = False

        # Ghi nốt phần còn lại của buffer (nếu có)
        if self._buffer:
            try:
                 asyncio.run_coroutine_threadsafe(
                    asyncio.to_thread(self._write_chunk_sync, bytes(self._buffer)), 
                    self._record_task.get_loop()
                 )
            except Exception as e:
                 log_info(f"❌ [Recorder] Lỗi ghi nốt buffer: {e}")
            self._buffer = bytearray()
        
        # Đóng file WAV (đồng bộ)
        if self._wav_file:
            try:
                self._wav_file.close()
            except Exception as e:
                 log_info(f"❌ [Recorder] Lỗi đóng file WAV: {e}")
            self._wav_file = None
            
        file_size = os.path.getsize(self._path) if os.path.exists(self._path) else 0
        log_info(f"[Recorder] ✅ Hoàn tất ghi âm. Kích thước file: {file_size} bytes. Tổng chunks: {self._chunks_recorded}.")

        if self._on_stop_callback and _was_recording:
            self._on_stop_callback(self._path)
            
# ======================================================
# API SERVER VÀ LOGIC XỬ LÝ RTC (Giữ nguyên)
# ======================================================

app = FastAPI()

processing_tasks: Dict[str, asyncio.Task] = {} 

async def _process_audio_and_respond(session_id: str, dm: DialogManager, pc: RTCPeerConnection, 
                                     data_channel: Optional[RTCDataChannel], saved_path: str):
    
    log_info(f"[{session_id}] Bắt đầu xử lý DialogManager...")
    
    try:
        processor = RTCStreamProcessor(log_callback=log_info) 

        async for is_audio, payload in processor.handle_rtc_session(
            record_file=Path(saved_path),
            session_id=session_id
        ):
            if not is_audio:
                data_to_send = json.dumps({"type": "metadata", **payload})
                if data_channel and data_channel.readyState == 'open':
                    data_channel.send(data_to_send)
            else:
                if data_channel and data_channel.readyState == 'open':
                    data_channel.send(payload)
                
    except asyncio.CancelledError:
        log_info(f"[{session_id}] 🛑 Xử lý đã bị HỦY bởi người dùng.", color="red")
        if data_channel and data_channel.readyState == 'open':
             data_channel.send(json.dumps({"type": "cancelled"}))
    except Exception as e:
        log_info(f"[{session_id}] ❌ LỖI trong quá trình xử lý: {e}", color="red")
        if data_channel and data_channel.readyState == 'open':
             data_channel.send(json.dumps({"type": "error", "message": str(e)}))
        
    finally:
        log_info(f"[{session_id}] Dọn dẹp Task xử lý.")
        if session_id in processing_tasks:
            del processing_tasks[session_id]
        
@app.post("/offer")
async def offer(request: Request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    
    api_key = params.get("api_key", "") 
    session_id = str(uuid.uuid4())
    log_info(f"[{session_id}] Bắt đầu phiên RTC.")

    pc = RTCPeerConnection()
    data_channel = None 
    
    dm = DialogManager(log_callback=log_info, api_key=api_key) 
    recorder = AudioFileRecorder(pc) 
    
    @pc.on("datachannel")
    def on_datachannel(channel):
        nonlocal data_channel
        data_channel = channel
        log_info(f"[{session_id}] Data Channel được thiết lập: {channel.label}")
        
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    if data.get("type") == "cancel_processing": 
                        log_info(f"[{session_id}] 🛑 Nhận lệnh HỦY XỬ LÝ từ Frontend.", color="red")
                        if session_id in processing_tasks:
                            processing_tasks[session_id].cancel() 
                except json.JSONDecodeError:
                    pass

        
    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            log_info(f"[{session_id}] Nhận Media Track: audio (Bắt đầu ghi âm)")
            input_audio_path = os.path.join("temp", f"{session_id}_input.wav")
            
            recorder.start(track, input_audio_path)
            
            def on_stop(saved_path):
                log_info(f"[{session_id}] Ghi âm dừng. Tạo task xử lý...")
                task = asyncio.create_task(
                    _process_audio_and_respond(session_id, dm, pc, data_channel, saved_path)
                )
                processing_tasks[session_id] = task 

            recorder.on("stop", on_stop) 

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

app.mount("/", StaticFiles(directory=".", html=True), name="static")