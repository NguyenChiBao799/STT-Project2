import asyncio
import os
import json
import uuid
from typing import Dict, Any

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel
# ⬅️ ĐÃ SỬA LỖI IMPORTERROR: Sử dụng MediaPlayer để stream file TTS ổn định (cần cài đặt PyAV: pip install av)
from aiortc.contrib.media import MediaPlayer 

# ⚠️ BẠN CẦN ĐẢM BẢO CÁC MODULE NÀY TỒN TẠI VÀ CHÍNH XÁC
from dialog_manager import DialogManager 

# Tạo thư mục temp nếu chưa có (cần thiết cho file input/output)
os.makedirs("temp", exist_ok=True) 

# --- CÁC MOCK/HELPER CƠ BẢN ---
# Hàm log đơn giản 
def log_info(message, color="white"):
    # Log ra console để bạn theo dõi
    print(f"INFO:backend_webrtc_server:{message}")

# Class Mock Recorder (Giả định bạn có một Recorder thực tế)
class MockAudioRecorder:
    """
    Giả lập logic ghi âm. Trong hệ thống thực tế, class này
    sẽ lắng nghe RTCRtpReceiver's track để ghi audio.
    """
    def __init__(self, pc):
        self._pc = pc
        self._on_stop_callback = None
    
    def on(self, event, callback):
        if event == "stop":
            self._on_stop_callback = callback
            
    def start(self, track, path):
        log_info(f"[Recorder] Bắt đầu ghi âm vào: {path}")
        # Trong môi trường MOCK, chúng ta sẽ tự động dừng sau 3 giây để giả lập kết thúc nói
        asyncio.create_task(self._mock_recording_process(path))
        
    async def _mock_recording_process(self, path):
        # Giả lập thời gian ghi âm
        await asyncio.sleep(3) 
        log_info(f"[Recorder] Đã lưu audio input (MOCK) vào: {path}")
        # Giả lập tạo file rỗng (hoặc file nhỏ) để DialogManager kiểm tra
        try:
             # Tạo file WAV nhỏ để tránh lỗi tensor of 0 elements
            with open(path, 'wb') as f:
                f.write(b'RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00')
        except Exception as e:
            log_info(f"Lỗi tạo mock file: {e}")

        if self._on_stop_callback:
            self._on_stop_callback(path)

# --- ỨNG DỤNG FASTAPI/STARLETTE ---
app = FastAPI()

# Cấu hình phục vụ file tĩnh (Frontend)
app.mount(
    "/",  
    StaticFiles(directory=".", html=True), 
    name="static"
)

# Route gốc trả về file HTML
@app.get("/", response_class=HTMLResponse)
async def serve_root_html():
    try:
        with open("frontend_webrtc_client.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Lỗi: Không tìm thấy frontend_webrtc_client.html</h1>", status_code=404)


# --- HÀM XỬ LÝ CHÍNH RTC ---

async def process_audio_and_generate_response(
    session_id: str, 
    audio_path: str, 
    dm: DialogManager, 
    pc: RTCPeerConnection, 
    data_channel: RTCDataChannel
):
    log_info(f"[{session_id}] Bắt đầu xử lý DialogManager...")
    
    # 1. Xử lý DialogManager
    try:
        dm_result = dm.process_audio_file(audio_path)
    except Exception as e:
        log_info(f"[{session_id}] ❌ Lỗi xử lý DM: {e}")
        dm_result = {"response_text": "Xin lỗi, có lỗi hệ thống.", "response_audio_path": None, "user_input_asr": "Lỗi"}

    response_text = dm_result["response_text"]
    response_audio_path = dm_result["response_audio_path"]
    user_input_asr = dm_result.get("user_input_asr", "Không rõ.")
    
    # 2. Gửi metadata (Text)
    if data_channel and data_channel.readyState == 'open':
        log_info(f"[{session_id}] Gửi Metadata: {response_text[:40]}...")
        try:
            # Gửi dữ liệu ASR và TTS text qua Data Channel
            await data_channel.send(json.dumps({
                "type": "transcript",
                "user_text": user_input_asr,
                "bot_text": response_text
            }))
        except Exception as e:
            log_info(f"[{session_id}] Lỗi gửi Data Channel: {e}")

    # 3. Gửi Audio (TTS)
    is_audio_sent = False
    if response_audio_path and os.path.exists(response_audio_path):
        log_info(f"[{session_id}] Gửi Audio TTS: {response_audio_path}")
        
        try:
            # Dùng MediaPlayer
            player = MediaPlayer(response_audio_path)
            audio_track = player.audio 
            pc.addTrack(audio_track) 
            is_audio_sent = True
        
            # ĐỢI cho Audio Track kết thúc
            await audio_track.ended
            
            log_info(f"[{session_id}] ✅ Audio TTS đã được truyền hoàn tất.")
            
        except Exception as e:
            log_info(f"[{session_id}] ❌ Lỗi MediaPlayer: {e}.", "red")
            
    else:
        log_info(f"[{session_id}] ⚠️ Không có file TTS để gửi.")
    
    
    # 4. Đóng kết nối An toàn
    if not is_audio_sent:
        await asyncio.sleep(1) 

    log_info(f"[{session_id}] Đóng PeerConnection (Clean up).")
    await pc.close()
    
    # Dọn dẹp file tạm
    if os.path.exists(audio_path): os.remove(audio_path)
    if response_audio_path and os.path.exists(response_audio_path): os.remove(response_audio_path)


# --- ROUTE /OFFER ---
@app.post("/offer")
async def offer(request: Request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    
    api_key = params.get("api_key", "") 
    session_id = str(uuid.uuid4())
    log_info(f"[{session_id}] Bắt đầu phiên RTC: API Key {'được cung cấp' if api_key else 'MOCK'}.")

    pc = RTCPeerConnection()
    data_channel = None 
    dm = DialogManager(log_callback=log_info, api_key=api_key) 
    recorder = MockAudioRecorder(pc)
    
    @pc.on("datachannel")
    def on_datachannel(channel):
        nonlocal data_channel
        data_channel = channel
        log_info(f"[{session_id}] Data Channel được thiết lập: {channel.label}")
        
    @pc.on("track")
    def on_track(track):
        # ⚠️ ĐÂY LÀ CHỖ CẦN LOG XUẤT HIỆN
        if track.kind == "audio":
            log_info(f"[{session_id}] Nhận Media Track: audio (Bắt đầu ghi âm)")
            input_audio_path = f"temp/{session_id}_input.wav"
            
            # Khởi động Recorder để lưu file input
            recorder.start(track, input_audio_path)
            
            @recorder.on("stop")
            def on_stop(saved_path):
                # Chạy hàm xử lý chính
                asyncio.create_task(
                    process_audio_and_generate_response(session_id, saved_path, dm, pc, data_channel)
                )

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}