# main_app.py
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog 
import time
import os
import threading
import json
import uuid
import random
import asyncio 
from datetime import datetime as _dt
from pathlib import Path
from typing import Optional, Callable, AsyncGenerator, Tuple, Any 
import traceback 
import wave 

# ==================== MOCK DEPENDENCIES (Cho tính Robust) =====================
# Các class này được dùng nếu các file .py tương ứng không tồn tại.
# Chúng cần trả về True cho is_ready() để cho phép logic RTC chạy.

class DialogManager: 
    def __init__(self, *args, **kwargs): self._is_ready = True
    def is_ready(self): return self._is_ready
    def get_initial_error(self): return "MOCK DM: Sẵn Sàng"
    def terminate(self): pass

class VoiceIOHandler:
    def __init__(self, log_callback, audio_file): 
        self.stop_event = threading.Event()
        self._is_ready = True
    def is_ready(self): return self._is_ready
    def get_initial_error(self): return "MOCK IO: Sẵn Sàng"
    def terminate(self): pass

# ⚠️ Import DialogManager và VoiceIOHandler
try:
    from dialog_manager import DialogManager
    from voice_io_handler import VoiceIOHandler
    print("✅ [App] Đã tìm thấy DialogManager và VoiceIOHandler.")
except ImportError:
    # Retain the MOCK classes defined above
    print("⚠️ [App] WARNING: dialog_manager.py or voice_io_handler.py not found. Using Mock classes.")


# THÊM: Import RTCStreamProcessor và các hằng số từ module RTC
try:
    from rtc_integration_layer import RTCStreamProcessor, RECORDING_DIR, SAMPLE_RATE, CHANNELS, CHUNK_SIZE
    print("✅ [App] Đã tìm thấy RTCStreamProcessor.")
except ImportError:
    # Fallback/Mock cho RTCProcessor
    class RTCStreamProcessor:
        def __init__(self, log_callback): self.log = log_callback
        async def handle_rtc_session(self, stream, session_id): 
            self.log(f"MOCK RTC: Handling session {session_id}")
            yield (False, {"user_text": "MOCK ASR Transcript", "bot_text": "MOCK Bot Response"})
            await asyncio.sleep(0.5) 
            yield (True, b"MOCK_TTS_RESPONSE")
    RECORDING_DIR = Path("rtc_recordings")
    SAMPLE_RATE = 16000 
    CHUNK_SIZE = 1024   
    CHANNELS = 1        
    print("❌ [App] RTCStreamProcessor not found. Using Mock.")
    
# --- THƯ VIỆN NGOÀI (Prometheus) ---
try:
    from prometheus_client import start_http_server, Counter as PromCounter, Gauge
    try:
         from config_db import PROMETHEUS_PORT
    except ImportError:
         PROMETHEUS_PORT = 8000
         
    REQUEST_COUNTER = PromCounter('voicebot_requests_total', 'Total requests.'); ERROR_COUNTER = PromCounter('voicebot_errors_total', 'Total errors.'); RESPONSE_TIME_GAUGE = Gauge('voicebot_response_time_seconds', 'Response time.')
except Exception: 
    start_http_server = lambda *a: None; PROMETHEUS_PORT = 8000
    class _MockMetric: 
        def inc(self): pass; 
        def set(self, v): pass
    REQUEST_COUNTER = ERROR_COUNTER = RESPONSE_TIME_GAUGE = _MockMetric()

# ==================== PHẦN I: HÀM HỖ TRỢ & HẰNG SỐ ====================

# Cấu hình file/folder (Sử dụng config_db cho các hằng số)
try:
    from config_db import AUDIO_FILE, TEMP_TTS_FILE, CONFIG_FILE, LOG_FILE_PATH, MOCK_STATS, SCENARIOS_CONFIG
    from pathlib import Path 
    AUDIO_FILE = Path(AUDIO_FILE)
    TEMP_TTS_FILE = Path(TEMP_TTS_FILE)
    CONFIG_FILE = Path(CONFIG_FILE)
    LOG_FILE_PATH = Path(LOG_FILE_PATH)
except ImportError:
    BASE_DIR = Path(__file__).parent
    TEMP_FOLDER = BASE_DIR / "temp"
    LOG_FOLDER = BASE_DIR / "logs"
    AUDIO_FILE = TEMP_FOLDER / "recording.wav"
    TEMP_TTS_FILE = TEMP_FOLDER / "tts_response.wav"
    CONFIG_FILE = BASE_DIR / "config.json"
    LOG_FILE_PATH = LOG_FOLDER / "app_log.txt"
    MOCK_STATS = {}
    SCENARIOS_CONFIG = {}
    print("⚠️ [IO] Failed to import paths/config from config_db, using fallback paths.")


TEMP_FOLDER = AUDIO_FILE.parent 
LOG_FOLDER = LOG_FILE_PATH.parent
TEMP_FOLDER.mkdir(exist_ok=True); LOG_FOLDER.mkdir(exist_ok=True)

# --- 1. HÀM HỖ TRỢ CHUNG ---
def styled_print(message, color="white"):
    """In ra console với màu."""
    colors = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
        "blue": "\033[94m", "purple": "\033[95m", "cyan": "\033[96m",
        "white": "\033[97m", "orange": "\033[33m"
    }
    reset = "\033[0m"
    print(f"{colors.get(color.lower(), colors['white'])}{message}{reset}")

def log_to_file(message, log_file_path):
    """Ghi log vào file."""
    timestamp = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        log_dir = Path(log_file_path).parent; log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_file_path, 'a', encoding='utf-8') as f: f.write(f"[{timestamp}] {message}\n")
    except Exception as e: styled_print(f"❌ [LOG] Lỗi ghi file log '{log_file_path}': {e}", "red")

def anonymize_text(text):
    """Rút gọn text cho mục đích log."""
    if not isinstance(text, str): return str(text)
    return f"{text[:20]}... (len: {len(text)})" if len(text) > 50 else text

# ==================== PHẦN II: CUSTOM TKINTER APP ====================
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title("Trợ Lý Bán Hàng AI Boo Boo")
        self.geometry("1000x700")
        self.grid_columnconfigure(0, weight=0) 
        self.grid_columnconfigure(1, weight=1) 
        self.grid_rowconfigure(0, weight=1)

        self.dm: Optional[DialogManager] = None
        self.voice_io: Optional[VoiceIOHandler] = None
        self.rtc_processor: Optional[RTCStreamProcessor] = None 
        self.dm_initialized = False
        
        # State variables
        self.api_key_var = tk.StringVar(value="")
        self.audio_device_var = tk.StringVar(value="Default")
        self.is_recording = False
        self.is_processing = False
        self.is_speaking = False
        self.rec_start_time = 0.0
        
        self.process_stop_event = threading.Event() 
        self.processing_thread: Optional[threading.Thread] = None 
        self.mic_stream = None # Lưu trữ luồng mic async

        self.scenario_intents = SCENARIOS_CONFIG.get("intents", [])
        self.selected_intent_var = tk.StringVar(value=self.scenario_intents[0]["intent_name"] if self.scenario_intents else "")


        self._load_ui_config()
        self._create_ui()
        threading.Thread(target=self._initialize_core_modules, daemon=True).start()
        self._update_ui_loop() 

    # ... (các hàm UI _create_ui, log, _save_ui_config, _load_ui_config giữ nguyên) ...
    def _create_ui(self):
        # --- Left Panel: Controls & Status ---
        self.left_panel = ctk.CTkFrame(self, width=300, corner_radius=0)
        self.left_panel.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.left_panel.grid_columnconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(9, weight=1) 

        ctk.CTkLabel(self.left_panel, text="Voice AI Control Panel", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")

        # API Key Input
        ctk.CTkLabel(self.left_panel, text="API Key (Mock):").grid(row=1, column=0, padx=20, pady=(10, 0), sticky="w")
        ctk.CTkEntry(self.left_panel, textvariable=self.api_key_var, show="*").grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.api_key_var.trace_add("write", self._reinit_modules) 

        # --- Button Frame (Updated) ---
        self.button_frame = ctk.CTkFrame(self.left_panel)
        self.button_frame.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        self.button_frame.columnconfigure((0, 1), weight=1)

        self.record_button = ctk.CTkButton(self.button_frame, text="🔴 Ghi âm (RTC Stream)", command=self.start_recording_command)
        self.record_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.stop_button = ctk.CTkButton(self.button_frame, text="⏹️ Dừng & Xử lý (RTC Stream)", command=self.stop_recording_command, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        # Stop Processing Button
        self.stop_process_button = ctk.CTkButton(self.button_frame, text="🛑 Ngừng Xử Lý", command=self.stop_processing_command, fg_color="red", hover_color="#800000", state="disabled")
        self.stop_process_button.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        # Nút Tải lên
        self.rtc_button_frame = ctk.CTkFrame(self.left_panel)
        self.rtc_button_frame.grid(row=4, column=0, padx=20, pady=10, sticky="ew")
        self.rtc_button_frame.columnconfigure(0, weight=1)
        
        self.upload_button = ctk.CTkButton(
            self.rtc_button_frame, 
            text="📤 Tải file âm thanh", 
            command=self.upload_audio_file,
            fg_color="darkblue",
            hover_color="#00008B"
        )
        self.upload_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")


        # Status (row 5)
        self.status_label = ctk.CTkLabel(self.left_panel, text="Trạng Thái: ⚪ Chưa Khởi Tạo", fg_color="gray", corner_radius=6)
        self.status_label.grid(row=5, column=0, padx=20, pady=5, sticky="ew")
        
        # Progress & Duration (row 6, 7)
        self.progress_bar = ctk.CTkProgressBar(self.left_panel, orientation="horizontal", mode="determinate")
        self.progress_bar.grid(row=6, column=0, padx=20, pady=(5, 0), sticky="ew")
        self.progress_bar.set(0.0)
        self.duration_label = ctk.CTkLabel(self.left_panel, text="Duration: 0.00s")
        self.duration_label.grid(row=7, column=0, padx=20, pady=(0, 5), sticky="w")

        # Log Box (row 8, 9)
        ctk.CTkLabel(self.left_panel, text="Log Output:").grid(row=8, column=0, padx=20, pady=(10, 0), sticky="w")
        self.log_textbox = ctk.CTkTextbox(self.left_panel, height=200)
        self.log_textbox.grid(row=9, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.log_textbox.configure(state="disabled")

        # --- Right Panel: Chat ---
        self.right_panel = ctk.CTkFrame(self, corner_radius=0)
        self.right_panel.grid(row=0, column=1, rowspan=2, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, weight=1) 

        # 1. Chat/ASR Box
        self.chat_frame = ctk.CTkFrame(self.right_panel)
        self.chat_frame.grid(row=0, column=0, padx=10, pady=(10, 10), sticky="nsew")
        self.chat_frame.grid_columnconfigure(0, weight=1)
        self.chat_frame.grid_rowconfigure(1, weight=1)

        self.asr_label = ctk.CTkLabel(self.chat_frame, text="User (ASR): [No Input]")
        self.asr_label.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")

        self.chat_textbox = ctk.CTkTextbox(self.chat_frame, height=250)
        self.chat_textbox.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nsew")
        self.chat_textbox.configure(state="disabled")

    # ... (các hàm log, _append_log_safe, _save_ui_config, _load_ui_config giữ nguyên) ...

    def log(self, message: str, color: str = "white"):
        """In log ra console và UI."""
        styled_print(message, color)
        log_to_file(message, LOG_FILE_PATH)
        self.after(0, lambda: self._append_log_safe(message, color))

    def _append_log_safe(self, message, tag):
        """Ghi log an toàn vào textbox của UI."""
        try:
            if hasattr(self, 'log_textbox') and self.log_textbox.winfo_exists():
                 self.log_textbox.configure(state="normal")
                 timestamp = _dt.now().strftime("[%H:%M:%S]")
                 self.log_textbox.insert("end", f"{timestamp} {message}\n", (tag,))
                 self.log_textbox.tag_config("red", foreground="red"); self.log_textbox.tag_config("green", foreground="green"); self.log_textbox.tag_config("yellow", foreground="yellow")
                 self.log_textbox.tag_config("blue", foreground="blue"); self.log_textbox.tag_config("cyan", foreground="cyan"); self.log_textbox.tag_config("orange", foreground="orange")
                 self.log_textbox.configure(state="disabled"); self.log_textbox.see("end")
        except Exception: pass

    def _save_ui_config(self):
        """Lưu cấu hình UI."""
        config = {
            "api_key": self.api_key_var.get(),
            "audio_device": self.audio_device_var.get()
        }
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            self.log("💾 [CONFIG] Cấu hình UI đã được lưu.", "green")
            return True
        except Exception as e:
            self.log(f"❌ [CONFIG] Lỗi lưu cấu hình: {e}", "red")
            return False

    def _load_ui_config(self):
        """Tải cấu hình UI."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.api_key_var.set(config.get("api_key", ""))
                    self.audio_device_var.set(config.get("audio_device", "Default"))
                self.log("✅ [CONFIG] Cấu hình UI đã được tải.", "green")
            except Exception as e:
                self.log(f"⚠️ [CONFIG] Lỗi tải cấu hình: {e}", "orange")


    # -------------------- CORE MODULE INITIALIZATION --------------------
    def _initialize_core_modules(self):
        """Khởi tạo DialogManager, VoiceIOHandler, và RTCProcessor trong một thread riêng."""
        if self.dm_initialized: return
        self.dm_initialized = True
        self.log("⏳ [APP] Bắt đầu khởi tạo core modules...", "yellow")
        self.after(0, lambda: self.status_label.configure(text="Trạng Thái: 🟡 Đang Khởi Tạo..."))
        
        try:
            # 1. Khởi tạo VoiceIO
            self.voice_io = VoiceIOHandler(log_callback=self.log, audio_file=str(AUDIO_FILE))
            
            # 2. Khởi tạo DialogManager
            self.dm = DialogManager(
                log_callback=self.log,
                api_key=self.api_key_var.get(), 
                voice_manager=self.voice_io 
            )

            # 3. Khởi tạo RTC Processor (Phần quan trọng)
            self.rtc_processor = RTCStreamProcessor(log_callback=self.log)
            
            # Kiểm tra trạng thái sẵn sàng
            is_ready = self.dm.is_ready() and self.voice_io.is_ready() and self.rtc_processor is not None
            
            if is_ready:
                 self.log("✅ [APP] Core modules đã sẵn sàng!", "green")
                 self.after(0, lambda: self.status_label.configure(text="Trạng Thái: 🟢 Sẵn Sàng"))
                 self.after(0, lambda: self._update_buttons(True))
            else:
                 error_io = self.voice_io.get_initial_error() if self.voice_io and not self.voice_io.is_ready() else "IO Sẵn Sàng. "
                 error_dm = self.dm.get_initial_error() if self.dm and not self.dm.is_ready() else ""
                 error_msg = f"IO Lỗi: {error_io} | DM Lỗi: {error_dm}"
                 self.log(f"❌ [APP] Core modules lỗi. Lỗi: {error_msg}", "red")
                 self.after(0, lambda: self.status_label.configure(text=f"Trạng Thái: 🔴 Lỗi Core"))
                 self.after(0, lambda: self._update_buttons(False))

        except Exception as e:
            self.log(f"❌ [APP] Lỗi khởi tạo core modules: {e}. Vui lòng kiểm tra các file dependency.", "red")
            self.after(0, lambda: self.status_label.configure(text="Trạng Thái: 🔴 Lỗi Core"))
            self.dm_initialized = False 
            self.after(0, lambda: self._update_buttons(False))

    def _reinit_modules(self, *args):
        """Khởi tạo lại module khi API Key thay đổi."""
        if self._save_ui_config():
            self.log("🔄 [CONFIG] Config changed. Re-initializing DM...", "yellow")
            
            self.stop_processing_command()
            time.sleep(0.1)
            
            # Đảm bảo reset các biến để khởi tạo lại
            self.dm = None; self.voice_io = None; self.rtc_processor = None
            self.dm_initialized = False 
            
            self._update_buttons(False) 
            threading.Thread(target=self._initialize_core_modules, daemon=True).start()
            
    # -------------------- RTC STREAM PROCESSING --------------------

    async def create_stream_from_file(self, file_path: str) -> AsyncGenerator[bytes, None]:
        """Tạo Async Generator từ file WAV đã tải lên."""
        self.log(f"📥 [File Stream] Bắt đầu đọc file: {file_path}", "blue")
        try:
            with wave.open(file_path, 'rb') as wf:
                if wf.getframerate() != SAMPLE_RATE or wf.getnchannels() != CHANNELS or wf.getsampwidth() != 2:
                    self.log(f"❌ [File Stream] Định dạng file WAV không đúng (cần {SAMPLE_RATE}Hz, mono, 16-bit).", "red")
                    return 
                
                while True:
                    chunk = wf.readframes(CHUNK_SIZE)
                    if not chunk: break
                    yield chunk
                    await asyncio.sleep(0.001)
            self.log("📥 [File Stream] Hoàn tất truyền file.", "blue")
        except Exception as e:
            self.log(f"❌ [File Stream] Lỗi khi đọc file audio: {e}", "red")
            
    async def _mic_rtc_stream_async(self) -> AsyncGenerator[bytes, None]:
        """Giả lập luồng audio từ microphone cho RTC."""
        self.log("MOCK: Microphone đang tạo luồng audio...", "yellow")
        
        while self.is_recording and not self.process_stop_event.is_set():
            yield b'\x00' * CHUNK_SIZE
            await asyncio.sleep(0.01)
            
        self.log("MOCK: Microphone dừng luồng.", "yellow")

    def start_processing_rtc(self, audio_stream_generator: Callable[[], AsyncGenerator[bytes, None]]):
        """Khởi chạy một luồng mới để xử lý RTC session."""
        if self.is_processing or not self.rtc_processor:
            self.log("⚠️ [App] RTC Processor chưa sẵn sàng hoặc đang bận.", "orange")
            return

        self.is_processing = True
        self._update_buttons(False) 
        
        self.log("🚀 [RTC] Bắt đầu xử lý RTC session trong luồng...", "green")

        threading.Thread(
            target=self._run_async_processing,
            args=(audio_stream_generator,),
            daemon=True
        ).start()

    def _run_async_processing(self, audio_stream_generator: Callable[[], AsyncGenerator[bytes, None]]):
        """Hàm đồng bộ chạy trong thread để khởi tạo loop asyncio và chạy session."""
        self.process_stop_event.clear()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            loop.run_until_complete(self._handle_rtc_session_async(audio_stream_generator()))
            
        except Exception as e:
            self.log(f"❌ [App Thread] Lỗi nghiêm trọng trong luồng xử lý RTC: {e}", "red")
            traceback.print_exc()
        finally:
            self.is_processing = False
            self.process_stop_event.clear()
            self.after(0, lambda: self._update_buttons(self.dm.is_ready() if self.dm else False))
            
    async def _handle_rtc_session_async(self, audio_stream: AsyncGenerator[bytes, None]):
        """Xử lý phiên RTC (async) và tiêu thụ luồng đầu ra."""
        REQUEST_COUNTER.inc()
        start_time = time.time()
        session_id = str(uuid.uuid4())
        
        try:
            self.log(f"🚀 [RTC] Session ID: {session_id}. Bắt đầu gọi RTC Processor...", "green")
            self.after(0, lambda: self.progress_bar.set(0.1))
            
            output_stream: AsyncGenerator[Tuple[bool, Any], None] = self.rtc_processor.handle_rtc_session(audio_stream, session_id=session_id)
            
            async for is_audio, data in output_stream: 
                if self.process_stop_event.is_set(): self.log("🛑 [TTS] Phát âm thanh bị hủy.", "red"); break
                
                if not is_audio:
                    full_transcript = data.get("user_text", "[Lỗi Transcript]")
                    response_text = data.get("bot_text", "[Lỗi Phản Hồi]")
                    
                    self.after(0, lambda: self.asr_label.configure(text=f"User (ASR): {full_transcript}"))
                    self.after(0, lambda: self._append_chat_safe("User", full_transcript, "User"))
                    self.after(0, lambda: self._append_chat_safe("Bot", response_text, "Bot"))
                    
                    self.log(f"📝 [Chat Log] User: {anonymize_text(full_transcript)} | Bot: {anonymize_text(response_text)}", "cyan")
                    self.after(0, lambda: self.progress_bar.set(0.3)) 
                
                else:
                    self.log(f"🔈 [TTS Out] Nhận chunk phản hồi ({len(data)} bytes)", "purple")
                    self.after(0, lambda: self.progress_bar.set(0.5)) 
                
            duration = time.time() - start_time
            RESPONSE_TIME_GAUGE.set(duration)
            self.log(f"✅ [RTC] Phiên hoàn tất. Thời gian phản hồi: {duration:.3f}s. File ghi âm đã lưu tại: {RECORDING_DIR}", "green")
            
            if not self.process_stop_event.is_set():
                 self.after(0, lambda: self.asr_label.configure(text=f"User (Stream): Xử lý hoàn tất."))
                 self.after(0, lambda: self.progress_bar.set(1.0))
            
        except Exception as e:
            ERROR_COUNTER.inc()
            self.log(f"❌ [RTC] Lỗi xử lý session: {e}", "red")
            traceback.print_exc()
            
    # -------------------- ACTION HANDLERS --------------------
    
    def stop_processing_command(self):
        """Gửi tín hiệu dừng tới thread xử lý và VoiceIO."""
        if self.is_processing or self.is_recording:
            self.process_stop_event.set() 
            if self.voice_io: self.voice_io.stop_event.set() 
            self.log("🛑 [PROCESS] Stop signal sent.", "red")
            if self.is_recording:
                self.is_recording = False
                self.mic_stream = None
                self._update_buttons(self.dm.is_ready() if self.dm else False)

        else:
            self.log("⚠️ [PROCESS] Không có tiến trình nào đang chạy để dừng.", "orange")

    def start_recording_command(self):
        """Bắt đầu ghi âm bằng cách kích hoạt luồng RTC từ Mic."""
        if self.is_recording or self.is_processing or self.is_speaking:
            self.log("⚠️ [IO] Đang bận. Không thể bắt đầu ghi âm.", "orange")
            return

        is_ready = self.rtc_processor is not None
        if not is_ready:
            # Lỗi này đã được log, nhưng chúng ta vẫn cần dừng lại nếu biến là None
            self.log(f"❌ [IO] RTC Processor chưa sẵn sàng. (biến rtc_processor là None)", "red")
            messagebox.showerror("Lỗi RTC", "Hệ thống RTC chưa sẵn sàng. Vui lòng kiểm tra Log.")
            return

        self.is_recording = True
        self.rec_start_time = time.time()
        self.asr_label.configure(text="User (RTC Stream): Đang lắng nghe...")
        self.log("🎤 [RTC] Bắt đầu Ghi âm từ Mic (Stream)...", "yellow")
        self.progress_bar.set(0.0)
        self._update_buttons(False) 
        
        self.mic_stream = self._mic_rtc_stream_async() 
        
    def stop_recording_command(self):
        """Dừng ghi âm và bắt đầu xử lý RTC session với luồng từ Mic."""
        if not self.is_recording or self.is_processing: return

        self.is_recording = False
        self.duration_label.configure(text="0.00s")
        self.log("🛑 [RTC] Dừng Ghi âm. Bắt đầu Xử lý Stream...", "yellow")

        self._update_buttons(False) 
        
        current_mic_stream = self.mic_stream
        
        if current_mic_stream:
            def mic_stream_generator():
                return current_mic_stream 
            
            self.start_processing_rtc(mic_stream_generator)
            self.mic_stream = None
        else:
            self.is_processing = False
            self.log("❌ [RTC] Lỗi: Không có luồng mic đang hoạt động (Mic stream là None).", "red")
            self.after(0, lambda: self._update_buttons(self.dm.is_ready() if self.dm else False))


    def upload_audio_file(self):
        """Xử lý nút tải lên file audio và khởi chạy RTC streaming."""
        if self.is_processing or self.is_recording or self.is_speaking or not self.rtc_processor:
             return

        file_path = filedialog.askopenfilename(
            title="Chọn file Audio WAV (16kHz, mono, 16-bit)",
            filetypes=[("WAV files", "*.wav")]
        )

        if file_path:
            self.log(f"⬆️ [Upload] Đã chọn file: {file_path}", "blue")
            
            stream_generator_obj = self.create_stream_from_file(file_path)
            
            def file_stream_generator():
                return stream_generator_obj
            
            self.start_processing_rtc(file_stream_generator)

    def _append_chat_safe(self, sender, message, tag):
        """Ghi nội dung chat an toàn vào textbox của UI."""
        try:
            if hasattr(self, 'chat_textbox') and self.chat_textbox.winfo_exists():
                 self.chat_textbox.configure(state="normal")
                 tag_map = {"User": "blue", "Bot": "green", "Error": "red"} 
                 self.chat_textbox.insert("end", f"[{sender}]: {message}\n", (tag,))
                 for t, c in tag_map.items(): self.chat_textbox.tag_config(t, foreground=c)
                 self.chat_textbox.configure(state="disabled"); self.chat_textbox.see("end")
        except Exception: pass
    
    # -------------------- UI UPDATES --------------------
    def _update_ui_loop(self,):
        """Cập nhật UI định kỳ (như thời lượng ghi âm)."""
        if self.is_recording:
            elapsed = time.time() - self.rec_start_time
            self.duration_label.configure(text=f"{elapsed:.2f}s")
        
        self.after(100, self._update_ui_loop)

    def _update_buttons(self, is_dm_ready: bool):
        """Cập nhật trạng thái nút bấm dựa trên trạng thái ứng dụng."""
        self.after(0, lambda: self._force_update_buttons(is_dm_ready))
        
    def _force_update_buttons(self, is_dm_ready: bool):
        """Logic cập nhật trạng thái nút bấm."""
        is_io_ready = self.voice_io and self.voice_io.is_ready()
        is_rtc_ready = self.rtc_processor is not None
        is_core_ready = is_dm_ready and is_io_ready and is_rtc_ready
        
        upload_state = "normal" if is_core_ready and not self.is_processing and not self.is_recording else "disabled"
        self.upload_button.configure(state=upload_state)
        
        if self.is_recording:
            self.record_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.stop_process_button.configure(state="disabled") 
            self.status_label.configure(text="Trạng Thái: 🔴 Đang Ghi Âm (RTC)")
        elif self.is_processing or self.is_speaking:
            self.record_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
            self.stop_process_button.configure(state="normal") 
            self.status_label.configure(text="Trạng Thái: 🟡 Đang Xử Lý/Nói...")
        elif is_core_ready:
            self.record_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.stop_process_button.configure(state="disabled") 
            self.status_label.configure(text="Trạng Thái: 🟢 Sẵn Sàng (RTC/File)")
        else:
            self.record_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
            self.stop_process_button.configure(state="disabled") 
            io_error = "Core Lỗi"
            self.status_label.configure(text=f"Trạng Thái: 🔴 Lỗi ({io_error})")

    # -------------------- CLOSING HANDLER --------------------
    def _on_closing(self):
        """Dọn dẹp tài nguyên khi đóng ứng dụng."""
        self.log("👋 [APP] Ứng dụng đang đóng...", "yellow")
        self._save_ui_config() 
        
        self.stop_processing_command() 
        time.sleep(0.5)

        if self.dm and hasattr(self.dm, 'terminate'):
            try: self.dm.terminate()
            except Exception as e: self.log(f"⚠️ [APP] Error terminating DM: {e}", "orange")

        if self.voice_io and hasattr(self.voice_io, 'terminate'):
            try: self.voice_io.terminate()
            except Exception as e: self.log(f"⚠️ [APP] Error terminating Voice IO: {e}", "orange")
            
        self.log(f"💾 [Recorder] File ghi âm được lưu tại thư mục: {RECORDING_DIR}", "orange")

        for f in [AUDIO_FILE, TEMP_TTS_FILE]:
            if f and os.path.exists(f):
                try: os.remove(f)
                except Exception as e: self.log(f"⚠️ [APP] Error deleting temp file {f}: {e}", "orange")

        self.destroy() 

# ==================== PHẦN III: KHỞI CHẠY ỨNG DỤNG ====================

if __name__ == "__main__":
    for f in [AUDIO_FILE, TEMP_TTS_FILE]:
        if f and os.path.exists(f): 
            try: os.remove(f)
            except Exception: pass
    
    try:
        if 'start_http_server' in globals() and start_http_server is not None:
            start_http_server(PROMETHEUS_PORT); styled_print(f"📈 [Metrics] Prometheus server on port {PROMETHEUS_PORT}", "green")
    except OSError as e:
         if "Address already in use" in str(e): styled_print(f"⚠️ [Metrics] Port {PROMETHEUS_PORT} in use.", "orange")
         else: styled_print(f"❌ [Metrics] Error starting Prometheus: {e}", "red")
    except Exception as e: styled_print(f"❌ [Metrics] Error starting Prometheus: {e}", "red")
    
    app = App()
    app.protocol("WM_DELETE_WINDOW", app._on_closing)
    app.mainloop()