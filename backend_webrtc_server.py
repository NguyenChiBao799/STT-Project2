# backend_webrtc_server.py - PHIÊN BẢN CUỐI CÙNG ĐÃ SỬA LỖI NoneType AWAIT
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
import traceback # ĐÃ THÊM IMPORT TRACEBACK
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
# Import tất cả các class cần thiết
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel, MediaStreamTrack, RTCConfiguration, RTCIceServer, RTCIceCandidate 
from aiortc.exceptions import InvalidStateError

# Import RTCStreamProcessor và SAMPLE_RATE
try:
    from rtc_integration_layer import RTCStreamProcessor, SAMPLE_RATE 
except ImportError:
    # Cung cấp class Mock nếu import lỗi để code không bị dừng
    class RTCStreamProcessor:
        def __init__(self, *args, **kwargs): pass
        async def handle_rtc_session(self, *args, **kwargs): 
            yield (False, {"user_text": "LỖI: RTCStreamProcessor không import được.", "bot_text": "Lỗi hệ thống nội bộ."})
    SAMPLE_RATE = 16000

# Giả định import DialogManager (giữ lại để tránh lỗi import)
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
    color_map = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m", 
        "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m", "white": "\033[97m", "orange": "\033[33m"
    }
    RESET = "\033[0m"
    print(f"{color_map.get(color, RESET)}INFO:backend_webrtc_server:[{message}]{RESET}", flush=True)


# ======================================================
# LỚP GHI ÂM ỔN ĐỊNH (FIX GHI FILE WAV - setparams(tuple))
# ======================================================
class AudioFileRecorder:
    """Class ghi luồng audio từ aiortc track vào file WAV (Sử dụng Asyncio.to_thread)."""
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
        
        log_info(f"[Recorder] Bắt đầu ghi âm vào file (Internal Buffering): {self._file_path.name}")

    def on(self, event: str, callback: Callable):
        if event == "stop":
            self._on_stop_callback = callback

    def _get_wav_params_tuple(self):
         # Trả về 6-tuple chuẩn cho wave.setparams()
         # (nchannels, sampwidth, framerate, nframes, comptype, compname)
         return (
            CHANNELS,      # nchannels = 1
            SAMPLE_WIDTH,  # sampwidth = 2
            SAMPLE_RATE,   # framerate = 16000
            0,             # nframes (placeholder)
            'NONE',        # comptype 
            'not compressed' # compname 
         )

    async def _read_track_and_write(self):
        try:
            while True:
                if self._stop_event.is_set():
                    log_info("[Recorder] 🛑 Dừng nhận luồng audio (Nhận lệnh stop từ frontend).")
                    break
                    
                packet = await self._track.recv() 
                
                audio_data_np = packet.to_ndarray() 
                
                # Chuyển đổi định dạng nếu cần
                if audio_data_np.dtype == np.float32:
                    audio_data_np = (audio_data_np * 32767).astype(np.int16)
                elif audio_data_np.dtype != np.int16:
                     audio_data_np = audio_data_np.astype(np.int16)
                     
                self._chunks.append(audio_data_np.tobytes())

        except asyncio.CancelledError:
             log_info(f"[Recorder] 🛑 Task ghi âm bị hủy (Đã nhận lệnh stop).")
        except Exception as e:
            if not self._stop_event.is_set():
                log_info(f"[Recorder] 🛑 Dừng nhận luồng audio (Remote closed/Error). Kích hoạt xử lý. Lỗi: {e}")
        finally:
            if not self._chunks:
                log_info("[Recorder] ⚠️ Không có dữ liệu audio để ghi. Bỏ qua ghi file.")
                if self._on_stop_callback and self._file_path:
                    # Gọi callback để thông báo không có file
                    self._on_stop_callback(str(self._file_path)) 
                return

            # Ghi file WAV trong threadpool (non-blocking)
            wav_params_tuple = self._get_wav_params_tuple() 
            
            await asyncio.to_thread(
                self._write_wav_file_safe, 
                str(self._file_path), 
                self._chunks, 
                len(self._chunks), 
                wav_params_tuple
            )
            
            if self._on_stop_callback and self._file_path:
                self._on_stop_callback(str(self._file_path))
            
    # HÀM GHI FILE WAV AN TOÀN
    def _write_wav_file_safe(self, file_path_str: str, chunks: list[bytes], chunk_count: int, wav_params_tuple: tuple):
        if not chunks:
            log_info("[Recorder] ⚠️ Không có dữ liệu audio để ghi (Trong threadpool).")
            return

        total_bytes = sum(len(c) for c in chunks)
        
        try:
            # Ghi file WAV
            with wave.open(file_path_str, 'wb') as wf:
                wf.setparams(wav_params_tuple) 
                
                for chunk in chunks:
                    wf.writeframes(chunk)
                    
            log_info(f"[Recorder] ✅ Hoàn tất ghi âm. Kích thước file: {total_bytes} bytes. Tổng chunks: {chunk_count}.")
        except Exception as e:
            log_info(f"[Recorder] ❌ Lỗi khi ghi file WAV: {e}")
            # Nếu file tồn tại nhưng bị lỗi, xóa nó.
            file_path = Path(file_path_str)
            if os.path.exists(file_path):
                 os.remove(file_path)
                 log_info(f"[Recorder] Đã xóa file hỏng: {file_path.name}")

    def stop(self):
        self._stop_event.set()
        
        # FIX QUAN TRỌNG: Hủy task để unblock await self._track.recv()
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
        record_file: str
    ):
    """Xử lý file audio và gửi phản hồi dưới dạng stream qua Data Channel."""
    
    # DEBUG LOG BẮT BUỘC: XÁC NHẬN HÀM ĐƯỢC CHẠY ĐẦY ĐỦ
    log_info(f"[{session_id}] DEBUG: START_PROCESS_AUDIO_AND_RESPOND", color="magenta") 

    log_info(f"[{session_id}] Bắt đầu xử lý DialogManager...")
    
    # FIX QUAN TRỌNG: Kiểm tra file bị thiếu NGAY LẬP TỨC
    if not os.path.exists(record_file):
        log_info(f"[{session_id}] ❌ File audio không tồn tại/đã bị xóa do lỗi ghi.", color="red")
        if data_channel and data_channel.readyState == 'open':
             try: data_channel.send(json.dumps({"type": "error", "error": "Lỗi: Không thể tạo file audio để xử lý."})) # <--- ĐÃ SỬA: BỎ await
             except Exception: pass
        return # Thoát sớm

    try:
        if data_channel and data_channel.readyState == 'open':
             # await 1
             data_channel.send(json.dumps({"type": "start_processing"})) # <--- ĐÃ SỬA: BỎ await
        else:
             log_info(f"[{session_id}] ⚠️ Data Channel không sẵn sàng để gửi tín hiệu bắt đầu.", color="orange")
        
        stream_generator = dm_processor.handle_rtc_session(
            record_file=Path(record_file),
            session_id=session_id
        )

        # FIX QUAN TRỌNG NHẤT: BẮT LỖI NoneType NGAY TẠI ĐÂY
        if stream_generator is None:
            log_info(f"[{session_id}] ❌ LỖI KHỞI TẠO: stream_generator là None. KHÔNG THỂ TIẾP TỤC.", color="red")
            if data_channel and data_channel.readyState == 'open':
                 try: data_channel.send(json.dumps({"type": "error", "error": "Lỗi: Internal server stream closed (stream is None)."})) # <--- ĐÃ SỬA: BỎ await
                 except Exception: pass
            return # Thoát sớm


        # DÒNG NÀY GÂY LỖI NẾU stream_generator LÀ None TẠI THỜI ĐIỂM NÀY
        async for is_audio, data in stream_generator: 
            if is_audio:
                # Dữ liệu Audio Chunk (Base64 bytes)
                response_data = {
                    "type": "audio_chunk",
                    "chunk": data.decode('utf-8') 
                }
                if data_channel and data_channel.readyState == 'open':
                   # await 2
                   data_channel.send(json.dumps(response_data)) # <--- ĐÃ SỬA: BỎ await
            else:
                # Dữ liệu Phản hồi Text
                response_data = {
                    "type": "text_response",
                    "user_text": data.get("user_text", ""),
                    "bot_text": data.get("bot_text", "")
                }
                if data_channel and data_channel.readyState == 'open':
                   # await 3
                   data_channel.send(json.dumps(response_data)) # <--- ĐÃ SỬA: BỎ await

    except asyncio.CancelledError:
        log_info(f"[{session_id}] 🛑 Task xử lý bị hủy (Cancel).", color="red")
        if data_channel and data_channel.readyState == 'open':
             try: data_channel.send(json.dumps({"type": "error", "error": "Xử lý đã bị hủy bởi người dùng."})) # <--- ĐÃ SỬA: BỎ await
             except Exception: pass
    except RuntimeError as e:
        if 'Executor shutdown has been called' in str(e):
             log_info(f"[{session_id}] ❌ LỖI XỬ LÝ: Threadpool đã đóng do server shutdown/reload. Bỏ qua.", color="red")
        else:
            log_info(f"[{session_id}] ❌ LỖI XỬ LÝ: {e}", color="red")
            if data_channel and data_channel.readyState == 'open':
                try: data_channel.send(json.dumps({"type": "error", "error": f"Lỗi server: {e}"})) # <--- ĐÃ SỬA: BỎ await
                except Exception: pass
    except Exception as e:
        # FIX CUỐI CÙNG: IN TRACEBACK ĐỂ TÌM DÒNG GÂY LỖI
        log_info(f"[{session_id}] ❌ LỖI XỬ LÝ CHUNG: {e}", color="red")
        log_info(f"[{session_id}] TRACEBACK ĐẦY ĐỦ:\n{traceback.format_exc()}", color="red")
        
        if data_channel and data_channel.readyState == 'open':
            try: data_channel.send(json.dumps({"type": "error", "error": f"Lỗi server: {e}"})) # <--- ĐÃ SỬA: BỎ await
            except Exception: pass
    finally:
        log_info(f"[{session_id}] Dọn dẹp Task xử lý.")
        # Dọn dẹp file chỉ khi nó còn tồn tại
        if os.path.exists(record_file):
            os.remove(record_file)
        
        try:
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

    config = RTCConfiguration(
        iceServers=ice_servers_objects 
    )
    
    pc = RTCPeerConnection(
        configuration=config
    )
    
    @pc.on("iceconnectionstatechange")
    def on_iceconnectionstatechange():
        log_info(f"[{session_id}] Trạng thái ICE: {pc.iceConnectionState}")

    return pc


# ======================================================
# FASTAPI APP & ROUTING
# ======================================================

app = FastAPI()
dm = RTCStreamProcessor(log_callback=log_info) 


@app.post("/offer")
async def offer(request: Request):
    params = await request.json()
    
    offer = RTCSessionDescription(
        sdp=params["sdp"],
        type=params["type"]
    )
    session_id = params.get("session_id", str(uuid.uuid4()))
    api_key = params.get("api_key", "MOCK")
    
    log_info(f"[{session_id}] Bắt đầu phiên RTC. Session ID: {session_id}")
    
    pc = await create_local_peer_connection(session_id, log_info)
    recorder = AudioFileRecorder(pc)
    
    # === Handlers cho Data Channel & Media Track ===
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
                    
                    # FIX: Thêm xử lý lệnh stop_recording
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
            
            def on_stop(saved_path):
                nonlocal data_channel_holder
                log_info(f"[{session_id}] Ghi âm dừng. Tạo task xử lý...")
                
                if not data_channel_holder:
                    log_info(f"[{session_id}] ❌ Không tìm thấy Data Channel để phản hồi. Đóng PC.")
                    asyncio.create_task(pc.close()) 
                    if os.path.exists(saved_path): os.remove(saved_path)
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
    # Sử dụng lệnh: uvicorn backend_webrtc_server:app --reload
    uvicorn.run(app, host="127.0.0.1", port=8000)