# backend_webrtc_server.py - PHIÊN BẢN ĐÃ SỬA LỖI IMPORTERROR
import asyncio
import os
import json
import uuid
import wave
import time
import base64
import numpy as np
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import traceback 
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel, MediaStreamTrack, RTCConfiguration, RTCIceServer, RTCIceCandidate 
from aiortc.exceptions import InvalidStateError

# Import RTCStreamProcessor và SAMPLE_RATE
try:
    # --- DÒNG LỖI ĐÃ BỊ XÓA: from rtc_integration_layer import RTCStreamProcessor, SAMPLE_RATE, log_info 
    from rtc_integration_layer import RTCStreamProcessor, SAMPLE_RATE 
except ImportError:
    class RTCStreamProcessor:
        def __init__(self, *args, **kwargs): pass
        async def handle_rtc_session(self, *args, **kwargs): 
            yield (False, {"user_text": "LỖI: RTCStreamProcessor không import được.", "bot_text": "Lỗi hệ thống nội bộ."})
    SAMPLE_RATE = 16000

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

# Cấu hình STUN/TURN Servers toàn cầu
ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:global.stun.twilio.com:3478"}
]

# State Management
processing_tasks: Dict[str, asyncio.Task] = {}
websocket_connections: Dict[str, WebSocket] = {}

def log_info(message: str, color="white"):
    """Hàm log_info được định nghĩa trong backend_webrtc_server.py"""
    color_map = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m", 
        "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m", "white": "\033[97m", "orange": "\033[33m"
    }
    RESET = "\033[0m"
    print(f"{color_map.get(color, RESET)}INFO:backend_webrtc_server:[{message}]{RESET}", flush=True)


# ======================================================
# LỚP GHI ÂM ỔN ĐỊNH VÀ BÁO LỖI (VỚI TRACEBACK)
# ======================================================
class AudioFileRecorder:
    """Class ghi luồng audio từ aiortc track vào file WAV."""
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
        
        log_info(f"[Recorder] Bắt đầu ghi âm (Internal Buffering): {self._file_path.name}")

    def on(self, event: str, callback: Callable):
        if event == "stop":
            self._on_stop_callback = callback

    def _get_wav_params_tuple(self):
         return (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE, 0, 'NONE', 'not compressed')

    async def _read_track_and_write(self):
        """Hàm đọc luồng audio từ track, lưu vào buffer và sau đó ghi file."""
        try:
            # 1. Đọc luồng audio vào buffer
            while not self._stop_event.is_set():
                try:
                    packet = await self._track.recv() 
                    audio_data_np = packet.to_ndarray() 
                    
                    if audio_data_np.dtype == np.float32:
                        audio_data_np = (audio_data_np * 32767).astype(np.int16)
                    elif audio_data_np.dtype != np.int16:
                         audio_data_np = audio_data_np.astype(np.int16)
                         
                    self._chunks.append(audio_data_np.tobytes())
                except InvalidStateError:
                    log_info("[Recorder] Track đã bị đóng (InvalidStateError). Dừng nhận luồng audio.", "orange")
                    break
                except Exception as e:
                    if not self._stop_event.is_set():
                        log_info(f"[Recorder] Lỗi khi nhận audio packet: {e}", "red")
                        log_info(f"[Recorder] TRACEBACK LỖI NHẬN GÓI:\n{traceback.format_exc()}", "red") 
                    break

        except asyncio.CancelledError:
             log_info(f"[Recorder] 🛑 Task đọc track bị hủy (Tiến hành ghi file).")
        except Exception as e:
            log_info(f"[Recorder] 🛑 Dừng nhận luồng audio do lỗi không xác định: {e}")
            log_info(f"[Recorder] TRACEBACK LỖI KHÔNG XÁC ĐỊNH:\n{traceback.format_exc()}", "red") 
        finally:
            # 2. Xử lý ghi file hoặc báo lỗi không có dữ liệu
            if not self._chunks:
                # --- LOG CẢNH BÁO MỚI (Lỗi chính) ---
                log_info("[Recorder] ⚠️ KHÔNG CÓ DỮ LIỆU AUDIO ĐỂ GHI. TỔNG CHUNKS: 0.", "red")
                log_info("--- KIỂM TRA FRONTEND/MÍC (Lỗi này do không nhận được gói dữ liệu WebRTC từ trình duyệt.) ---", "red")
                # --- KẾT THÚC LOG CẢNH BÁO MỚI ---
                if self._on_stop_callback and self._file_path:
                    self._on_stop_callback(None) 
                return

            wav_params_tuple = self._get_wav_params_tuple() 
            file_path_str = str(self._file_path)
            
            try:
                # Ghi file WAV trong threadpool (non-blocking)
                await asyncio.to_thread(
                    self._write_wav_file_safe, 
                    file_path_str, 
                    self._chunks, 
                    len(self._chunks), 
                    wav_params_tuple
                )
                if self._on_stop_callback:
                    # Gửi đường dẫn file đã ghi thành công
                    self._on_stop_callback(file_path_str)
            except Exception as e:
                log_info(f"[Recorder] ❌ Lỗi TOÀN BỘ khi ghi file WAV: {e}", "red")
                if self._on_stop_callback:
                    self._on_stop_callback(None) 


    def _write_wav_file_safe(self, file_path_str: str, chunks: list[bytes], chunk_count: int, wav_params_tuple: tuple):
        """Hàm đồng bộ chạy trong threadpool để ghi file WAV."""
        total_bytes = sum(len(c) for c in chunks)
        
        try:
            with wave.open(file_path_str, 'wb') as wf:
                wf.setparams(wav_params_tuple) 
                for chunk in chunks:
                    wf.writeframes(chunk)
                    
            log_info(f"[Recorder] ✅ Hoàn tất ghi âm. Kích thước file: {total_bytes} bytes. Tổng chunks: {chunk_count}.")
        except Exception as e:
            log_info(f"[Recorder] ❌ Lỗi khi ghi nội dung file WAV: {e}", "red")
            log_info(f"[Recorder] TRACEBACK LỖI GHI FILE:\n{traceback.format_exc()}", "red") 
            file_path = Path(file_path_str)
            if os.path.exists(file_path):
                 os.remove(file_path)
                 log_info(f"[Recorder] Đã xóa file hỏng: {file_path.name}")
            raise 

    def stop(self):
        self._stop_event.set()
        if self._record_task:
             self._record_task.cancel()


# ======================================================
# LÔGIC XỬ LÝ HỆ THỐNG
# ======================================================

async def _process_audio_and_respond(
        session_id: str,
        dm_processor: RTCStreamProcessor,
        pc: RTCPeerConnection,
        data_channel: Optional[RTCDataChannel],
        record_file: Optional[str] 
    ):
    """Xử lý file audio và gửi phản hồi dưới dạng stream qua Data Channel."""
    
    log_info(f"[{session_id}] DEBUG: START_PROCESS_AUDIO_AND_RESPOND", color="magenta") 
    
    if not record_file or not os.path.exists(record_file):
        log_info(f"[{session_id}] ❌ File audio không tồn tại/ghi lỗi. BỎ QUA XỬ LÝ.", color="red")
        
        # Gửi thông báo lỗi qua Data Channel
        if data_channel and data_channel.readyState == 'open':
             try: data_channel.send(json.dumps({"type": "error", "error": "Lỗi: Không thể tạo file audio để xử lý (Không có dữ liệu đầu vào)."})) 
             except Exception: pass
        
        try: await pc.close()
        except Exception: pass
        
        if session_id in processing_tasks:
            del processing_tasks[session_id]
        return 

    try:
        # Gửi tín hiệu bắt đầu xử lý cho frontend
        if data_channel and data_channel.readyState == 'open':
             data_channel.send(json.dumps({"type": "start_processing"})) 
        
        stream_generator = dm_processor.handle_rtc_session(
            record_file=Path(record_file),
            session_id=session_id
        )
        
        # BẮT ĐẦU VÒNG LẶP XỬ LÝ STREAM
        async for is_audio, data in stream_generator: 
            if is_audio:
                response_data = {"type": "audio_chunk", "chunk": data.decode('utf-8')}
                if data_channel and data_channel.readyState == 'open':
                   data_channel.send(json.dumps(response_data)) 
            else:
                response_data = {"type": "text_response", **data}
                if data_channel and data_channel.readyState == 'open':
                   data_channel.send(json.dumps(response_data)) 
        
        # Gửi tín hiệu kết thúc
        if data_channel and data_channel.readyState == 'open':
           data_channel.send(json.dumps({"type": "end_of_session"})) 


    except asyncio.CancelledError:
        log_info(f"[{session_id}] 🛑 Task xử lý bị hủy (Cancel).", color="red")
        if data_channel and data_channel.readyState == 'open':
             try: data_channel.send(json.dumps({"type": "error", "error": "Xử lý đã bị hủy bởi người dùng."})) 
             except Exception: pass
    except Exception as e:
        log_info(f"[{session_id}] ❌ LỖI XỬ LÝ CHUNG: {e}", "red")
        log_info(f"[{session_id}] TRACEBACK LỖI XỬ LÝ CHUNG:\n{traceback.format_exc()}", "red") 
        
        if data_channel and data_channel.readyState == 'open':
            try: data_channel.send(json.dumps({"type": "error", "error": f"Lỗi server: {e}"})) 
            except Exception: pass
    finally:
        log_info(f"[{session_id}] Dọn dẹp Task xử lý.")
        if record_file and os.path.exists(record_file):
            os.remove(record_file)
        
        try:
            # Đảm bảo PC đóng hoàn toàn
            if pc.connectionState != 'closed': 
                 await pc.close()
        except Exception:
            pass
            
        if session_id in processing_tasks:
            del processing_tasks[session_id]

async def create_local_peer_connection(session_id: str, log_info: Callable) -> RTCPeerConnection:
    """Tạo RTCPeerConnection với cấu hình ICE Servers."""
    ice_servers_objects = [
        RTCIceServer(urls=server["urls"]) 
        for server in ICE_SERVERS
    ]

    config = RTCConfiguration(iceServers=ice_servers_objects)
    pc = RTCPeerConnection(configuration=config)
    
    @pc.on("iceconnectionstatechange")
    def on_iceconnectionstatechange():
        log_info(f"[{session_id}] Trạng thái ICE: {pc.iceConnectionState}")

    return pc


app = FastAPI()
# Truyền hàm log_info của chính file này cho RTCStreamProcessor
dm = RTCStreamProcessor(log_callback=log_info) 


@app.post("/offer")
async def offer(request: Request):
    params = await request.json()
    
    offer = RTCSessionDescription(
        sdp=params["sdp"],
        type=params["type"]
    )
    session_id = params.get("session_id", str(uuid.uuid4()))
    
    log_info(f"[{session_id}] Bắt đầu phiên RTC. Session ID: {session_id}")
    
    pc = await create_local_peer_connection(session_id, log_info)
    recorder = AudioFileRecorder(pc)
    data_channel_holder: Optional[RTCDataChannel] = None

    @pc.on("datachannel")
    def on_datachannel(channel):
        nonlocal data_channel_holder
        data_channel_holder = channel
        log_info(f"[{session_id}] Data Channel được thiết lập: {channel.label}")

        @channel.on("message")
        def on_message(message):
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    if data.get("type") == "stop_recording": 
                        log_info(f"[{session_id}] 🛑 Nhận lệnh DỪNG GHI ÂM từ Frontend.")
                        recorder.stop()
                    elif data.get("type") == "cancel_processing": 
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
            
            def on_stop(saved_path: Optional[str]): 
                nonlocal data_channel_holder
                log_info(f"[{session_id}] Ghi âm dừng. Tạo task xử lý...")
                
                if not data_channel_holder:
                    log_info(f"[{session_id}] ❌ Không tìm thấy Data Channel để phản hồi. Đóng PC.")
                    asyncio.create_task(pc.close()) 
                    if saved_path and os.path.exists(saved_path): os.remove(saved_path)
                    return
                
                task = asyncio.create_task(
                    _process_audio_and_respond(session_id, dm, pc, data_channel_holder, saved_path)
                )
                processing_tasks[session_id] = task

            recorder.on("stop", on_stop)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

# 2. Định nghĩa route WEBSOCKET (cho ICE candidates)
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str = "default_session"):
    
    await websocket.accept()
    websocket_connections[session_id] = websocket
    
    try:
        while True:
            # Websocket được giữ mở, không cần xử lý tin nhắn candidate phức tạp ở đây
            await websocket.receive_text()
    
    except WebSocketDisconnect:
        log_info(f"[{session_id}] WebSocket bị đóng.")
    except Exception:
        pass
    finally:
        if session_id in websocket_connections:
             del websocket_connections[session_id]

# 3. Gắn StaticFiles CUỐI CÙNG (CATCH-ALL)
app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)