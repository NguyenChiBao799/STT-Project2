# backend_webrtc_server.py
import asyncio
import os
import json
import uuid
import wave
import numpy as np
from typing import Dict, Any, Optional, Callable, Tuple, AsyncGenerator
from pathlib import Path
import traceback 
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel, MediaStreamTrack, RTCConfiguration, RTCIceServer
from aiortc.exceptions import InvalidStateError

# Import RTCStreamProcessor và SAMPLE_RATE, INTERNAL_API_KEY
try:
    from rtc_integration_layer import RTCStreamProcessor, SAMPLE_RATE, INTERNAL_API_KEY 
except ImportError:
    class RTCStreamProcessor:
        def __init__(self, *args, **kwargs): pass
        async def handle_rtc_session(self, *args, **kwargs): 
            yield (False, {"user_text": "LỖI: RTCStreamProcessor không import được.", "bot_text": "Lỗi hệ thống nội bộ."})
    SAMPLE_RATE = 16000
    INTERNAL_API_KEY = "" 

# --- Hằng số và State Management ---
CHANNELS = 1
SAMPLE_WIDTH = 2
os.makedirs("temp", exist_ok=True)
# Sử dụng STUN server công khai
ICE_SERVERS = [{"urls": "stun:stun.l.google.com:19302"}]
processing_tasks: Dict[str, asyncio.Task] = {}

def log_info(message: str, color="white"):
    color_map = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m", 
        "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m", "white": "\033[97m", "orange": "\033[33m"
    }
    RESET = "\033[0m"
    print(f"{color_map.get(color, RESET)}INFO:backend_webrtc_server:[{message}]{RESET}", flush=True)


# ======================================================
# LỚP GHI ÂM (AudioFileRecorder)
# ======================================================
class AudioFileRecorder:
    def __init__(self, pc):
        self._pc = pc
        self._on_stop_callback: Optional[Callable] = None
        self._track: Optional[MediaStreamTrack] = None
        self._file_path: Optional[Path] = None
        self._stop_event = asyncio.Event()
        self._chunks: list[bytes] = []
        self._record_task: Optional[asyncio.Task] = None 
        
    def start(self, track: MediaStreamTrack, file_path: str):
        self._track = track
        self._file_path = Path(file_path)
        self._stop_event.clear()
        self._chunks = []
        self._record_task = asyncio.create_task(self._read_track_and_write()) 
        log_info(f"[Recorder] Bắt đầu ghi âm: {self._file_path.name}")
        
    def on(self, event: str, callback: Callable):
        if event == "stop": self._on_stop_callback = callback
        
    def _get_wav_params_tuple(self):
         return (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE, 0, 'NONE', 'not compressed')

    async def _read_track_and_write(self):
        # ... (logic ghi âm giữ nguyên, sử dụng asyncio.to_thread để ghi file) ...
        try:
            while not self._stop_event.is_set():
                try:
                    packet = await self._track.recv() 
                    audio_data_np = packet.to_ndarray() 
                    if audio_data_np.dtype == np.float32:
                        audio_data_np = (audio_data_np * 32767).astype(np.int16)
                    elif audio_data_np.dtype != np.int16:
                         audio_data_np = audio_data_np.astype(np.int16)
                    self._chunks.append(audio_data_np.tobytes())
                except InvalidStateError: break
                except Exception as e:
                    if not self._stop_event.is_set(): log_info(f"[Recorder] Lỗi khi nhận audio packet: {e}", "red")
                    break
        except asyncio.CancelledError: log_info(f"[Recorder] Task đọc track bị hủy.")
        finally:
            if not self._chunks:
                if self._on_stop_callback and self._file_path: self._on_stop_callback(None) 
                return
            try:
                # Ghi file trong một luồng đồng bộ
                await asyncio.to_thread(self._write_wav_file_safe, str(self._file_path), self._chunks, self._get_wav_params_tuple())
                if self._on_stop_callback: self._on_stop_callback(str(self._file_path))
            except Exception as e:
                log_info(f"[Recorder] LỖI GHI FILE: {e}", "red")
                if self._on_stop_callback: self._on_stop_callback(None) 

    def _write_wav_file_safe(self, file_path_str: str, chunks: list[bytes], wav_params_tuple: tuple):
        try:
            with wave.open(file_path_str, 'wb') as wf:
                wf.setparams(wav_params_tuple) 
                for chunk in chunks: wf.writeframes(chunk)
            log_info(f"[Recorder] ✅ Hoàn tất ghi âm: {file_path_str}")
        except Exception as e: raise 

    def stop(self):
        self._stop_event.set()
        if self._record_task: self._record_task.cancel()

# ======================================================
# LÔGIC XỬ LÝ CHÍNH (Truyền API Key)
# ======================================================

async def _process_audio_and_respond(
        session_id: str,
        dm_processor: RTCStreamProcessor,
        pc: RTCPeerConnection,
        data_channel: Optional[RTCDataChannel],
        record_file: Optional[str],
        api_key: str # API Key được truyền từ Frontend
    ):
    """Xử lý file audio và gửi phản hồi dưới dạng stream qua Data Channel."""
    
    if not record_file or not os.path.exists(record_file):
        if data_channel and data_channel.readyState == 'open':
             try: data_channel.send(json.dumps({"type": "error", "error": "Lỗi: Không có dữ liệu audio."})) 
             except Exception: pass
        return 

    try:
        if data_channel and data_channel.readyState == 'open':
             data_channel.send(json.dumps({"type": "start_processing"})) 
        
        # Gọi luồng xử lý chính trong rtc_integration_layer (TRUYỀN API KEY VÀO)
        stream_generator = dm_processor.handle_rtc_session(
            record_file=Path(record_file),
            session_id=session_id,
            api_key=api_key 
        )
        
        async for is_audio, data in stream_generator: 
            if is_audio:
                # Audio chunk (Base64)
                response_data = {"type": "audio_chunk", "chunk": data.decode('utf-8')}
            else:
                # Text response or status update
                response_data = {"type": "text_response", **data}
            
            if data_channel and data_channel.readyState == 'open':
               data_channel.send(json.dumps(response_data)) 
        
        if data_channel and data_channel.readyState == 'open':
           data_channel.send(json.dumps({"type": "end_of_session"})) 

    except asyncio.CancelledError:
        log_info(f"[{session_id}] Xử lý bị hủy.", "orange")
    except Exception as e:
        log_info(f"[{session_id}] ❌ LỖI XỬ LÝ CHUNG: {e}", "red")
        log_info(traceback.format_exc(), "red")
        if data_channel and data_channel.readyState == 'open':
            try: data_channel.send(json.dumps({"type": "error", "error": f"Lỗi server: {e}"})) 
            except Exception: pass
    finally:
        if record_file and os.path.exists(record_file): os.remove(record_file)
        try:
            if pc.connectionState != 'closed': await pc.close()
        except Exception: pass
        if session_id in processing_tasks: del processing_tasks[session_id]

async def create_local_peer_connection(session_id: str, log_info: Callable) -> RTCPeerConnection:
    ice_servers_objects = [RTCIceServer(urls=server["urls"]) for server in ICE_SERVERS]
    config = RTCConfiguration(iceServers=ice_servers_objects)
    pc = RTCPeerConnection(configuration=config)
    return pc


app = FastAPI()
dm = RTCStreamProcessor(log_callback=log_info) 


@app.post("/offer")
async def offer(request: Request):
    params = await request.json()
    
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    session_id = params.get("session_id", str(uuid.uuid4()))
    # Lấy API Key từ body POST request
    client_api_key = params.get("api_key", INTERNAL_API_KEY) 
    
    pc = await create_local_peer_connection(session_id, log_info)
    recorder = AudioFileRecorder(pc)
    data_channel_holder: Optional[RTCDataChannel] = None

    @pc.on("datachannel")
    def on_datachannel(channel):
        nonlocal data_channel_holder
        data_channel_holder = channel
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    if data.get("type") == "stop_recording": recorder.stop()
                    elif data.get("type") == "cancel_processing": 
                        if session_id in processing_tasks: 
                            processing_tasks[session_id].cancel()
                            log_info(f"[{session_id}] Hủy Task xử lý theo yêu cầu.", "orange")
                except json.JSONDecodeError: pass

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            input_audio_path = os.path.join("temp", f"{session_id}_input.wav")
            recorder.start(track, input_audio_path)
            
            def on_stop(saved_path: Optional[str]): 
                nonlocal data_channel_holder
                if not data_channel_holder: 
                    log_info(f"[{session_id}] Không thấy Data Channel. Bỏ qua xử lý.", "red")
                    if saved_path and os.path.exists(saved_path): os.remove(saved_path)
                    return 
                
                # Tạo Task xử lý chính (TRUYỀN client_api_key VÀO ĐÂY)
                task = asyncio.create_task(
                    _process_audio_and_respond(session_id, dm, pc, data_channel_holder, saved_path, client_api_key) 
                )
                processing_tasks[session_id] = task

            recorder.on("stop", on_stop)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str = "default_session"):
    # WebSocket chỉ dùng cho mục đích kết nối ICE Candidates (nếu cần), 
    # nhưng ở đây ta đang dùng HTTP/POST offer/answer đơn giản. 
    # Giữ lại để đảm bảo tính ổn định của aiortc.
    await websocket.accept()
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: pass
    except Exception: pass

# Gắn StaticFiles để serve frontend_webrtc_client.html
app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Cần chạy Uvicorn với --reload để phát triển
    uvicorn.run(app, host="127.0.0.1", port=8000)