# main_app.py
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import time
import os
import threading
import json
import uuid
import random
from datetime import datetime as _dt
from pathlib import Path
from typing import Optional, Callable
import traceback 

# ⚠️ Import DialogManager
from dialog_manager import DialogManager
from voice_io_handler import VoiceIOHandler

# --- THƯ VIỆN NGOÀI ---
try:
    from prometheus_client import start_http_server, Counter as PromCounter, Gauge
    # Sử dụng config_db nếu có, hoặc dùng fallback
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

# ==================== PHẦN I: HÀM HỖ TRỢ & IMPORTS ====================

# Cấu hình file/folder (Sử dụng config_db cho các hằng số)
try:
    from config_db import AUDIO_FILE, TEMP_TTS_FILE, CONFIG_FILE, LOG_FILE_PATH, MOCK_STATS, SCENARIOS_CONFIG
    # Chuyển Path object
    AUDIO_FILE = Path(AUDIO_FILE)
    TEMP_TTS_FILE = Path(TEMP_TTS_FILE)
    CONFIG_FILE = Path(CONFIG_FILE)
    LOG_FILE_PATH = Path(LOG_FILE_PATH)
except ImportError:
    # Fallback paths/configs if config_db fails
    BASE_DIR = Path(__file__).parent
    TEMP_FOLDER = BASE_DIR / "temp"
    LOG_FOLDER = BASE_DIR / "logs"
    AUDIO_FILE = TEMP_FOLDER / "recording.wav"
    TEMP_TTS_FILE = TEMP_FOLDER / "tts_response.wav"
    CONFIG_FILE = BASE_DIR / "config.json"
    LOG_FILE_PATH = LOG_FOLDER / "app_log.txt"
    MOCK_STATS = {
        "total_requests": 1000, "conversion_rate": 0.1, 
        "products_mentioned": {"Product X": 200, "Product Y": 150},
        "sales_data": [{"date": "2025-01-01", "sales": 10000000, "conversion_rate": 0.1}]
    }
    SCENARIOS_CONFIG = {"intents": [{"intent_name": "query_weather", "responses": ["Fallback weather response."], "products": []}]}
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
        # ✅ Đổi tên tiêu đề ứng dụng
        self.title("Trợ Lý Bán Hàng AI - Boo Boo")
        self.geometry("1000x700")
        self.grid_columnconfigure(0, weight=0) 
        self.grid_columnconfigure(1, weight=1) 
        self.grid_rowconfigure(0, weight=1)

        self.dm: Optional[DialogManager] = None
        self.voice_io: Optional[VoiceIOHandler] = None
        self.dm_initialized = False

        # State variables
        self.api_key_var = tk.StringVar(value="")
        self.audio_device_var = tk.StringVar(value="Default")
        self.is_recording = False
        self.is_processing = False
        self.is_speaking = False
        self.rec_start_time = 0.0
        
        # Stop processing event and thread reference
        self.process_stop_event = threading.Event() 
        self.processing_thread: Optional[threading.Thread] = None 
        
        # Scenario management data
        self.scenario_intents = SCENARIOS_CONFIG.get("intents", [])
        self.selected_intent_var = tk.StringVar(value=self.scenario_intents[0]["intent_name"] if self.scenario_intents else "")


        self._load_ui_config()
        self._create_ui()
        threading.Thread(target=self._initialize_core_modules, daemon=True).start()
        self._update_ui_loop() 

    def _create_ui(self):
        # --- Left Panel: Controls & Status ---
        self.left_panel = ctk.CTkFrame(self, width=300, corner_radius=0)
        self.left_panel.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.left_panel.grid_columnconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(8, weight=1) # Log box

        ctk.CTkLabel(self.left_panel, text="Voice AI Control Panel", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")

        # API Key Input
        ctk.CTkLabel(self.left_panel, text="API Key (Mock):").grid(row=1, column=0, padx=20, pady=(10, 0), sticky="w")
        ctk.CTkEntry(self.left_panel, textvariable=self.api_key_var, show="*").grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.api_key_var.trace_add("write", self._reinit_modules) 

        # --- Button Frame (Updated) ---
        self.button_frame = ctk.CTkFrame(self.left_panel)
        self.button_frame.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        self.button_frame.columnconfigure((0, 1), weight=1)

        self.record_button = ctk.CTkButton(self.button_frame, text="🔴 Start Recording", command=self.start_recording_command)
        self.record_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.stop_button = ctk.CTkButton(self.button_frame, text="⏹️ Stop Recording", command=self.stop_recording_command, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        # Stop Processing Button
        self.stop_process_button = ctk.CTkButton(self.button_frame, text="🛑 Ngừng Xử Lý", command=self.stop_processing_command, fg_color="red", hover_color="#800000", state="disabled")
        self.stop_process_button.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        # Status
        self.status_label = ctk.CTkLabel(self.left_panel, text="Trạng Thái: ⚪ Chưa Khởi Tạo", fg_color="gray", corner_radius=6)
        self.status_label.grid(row=4, column=0, padx=20, pady=5, sticky="ew")
        
        # Progress & Duration
        self.progress_bar = ctk.CTkProgressBar(self.left_panel, orientation="horizontal", mode="determinate")
        self.progress_bar.grid(row=5, column=0, padx=20, pady=(5, 0), sticky="ew")
        self.progress_bar.set(0.0)
        self.duration_label = ctk.CTkLabel(self.left_panel, text="Duration: 0.00s")
        self.duration_label.grid(row=6, column=0, padx=20, pady=(0, 5), sticky="w")

        # Log Box
        ctk.CTkLabel(self.left_panel, text="Log Output:").grid(row=7, column=0, padx=20, pady=(10, 0), sticky="w")
        self.log_textbox = ctk.CTkTextbox(self.left_panel, height=200)
        self.log_textbox.grid(row=8, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.log_textbox.configure(state="disabled")

        # --- Right Panel: Chat & Tabs ---
        self.right_panel = ctk.CTkFrame(self, corner_radius=0)
        self.right_panel.grid(row=0, column=1, rowspan=2, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, weight=1) # Chat box gets more space

        # 1. Chat/ASR Box
        self.chat_frame = ctk.CTkFrame(self.right_panel)
        self.chat_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        self.chat_frame.grid_columnconfigure(0, weight=1)
        self.chat_frame.grid_rowconfigure(1, weight=1)

        self.asr_label = ctk.CTkLabel(self.chat_frame, text="User (ASR): [No Input]")
        self.asr_label.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")

        self.chat_textbox = ctk.CTkTextbox(self.chat_frame, height=250)
        self.chat_textbox.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nsew")
        self.chat_textbox.configure(state="disabled")

        # 2. Tab View for Management/Stats
        self.tab_view = ctk.CTkTabview(self.right_panel, height=350)
        self.tab_view.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="ew")
        
        # Create tabs
        self.stats_tab = self.tab_view.add("📊 Thống Kê")
        self.scenario_tab = self.tab_view.add("⚙️ Kịch Bản")
        self.sales_tab = self.tab_view.add("💰 Báo Cáo Doanh Số")
        
        self._create_stats_tab(self.stats_tab)
        self._create_scenario_tab(self.scenario_tab)
        self._create_sales_tab(self.sales_tab)


    # -------------------- LOGIC CHO CÁC TAB --------------------

    def _create_stats_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(tab, text="Thống Kê Tổng Quan (Mock Data)", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=10, pady=(10, 10), sticky="w")
        
        # 1. Tỷ lệ chuyển đổi
        frame_rate = ctk.CTkFrame(tab)
        frame_rate.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        rate = MOCK_STATS.get("conversion_rate", 0.0) * 100
        ctk.CTkLabel(frame_rate, text="Tỷ lệ chuyển đổi (CR):", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
        ctk.CTkLabel(frame_rate, text=f"{rate:.2f}%").pack(side="right", padx=10, pady=10)
        
        # 2. Tổng số lượt hỏi
        frame_requests = ctk.CTkFrame(tab)
        frame_requests.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        requests = MOCK_STATS.get("total_requests", 0)
        ctk.CTkLabel(frame_requests, text="Tổng số lượt hỏi:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
        ctk.CTkLabel(frame_requests, text=f"{requests} lượt").pack(side="right", padx=10, pady=10)
        
        # 3. Sản phẩm được nhắc nhiều
        ctk.CTkLabel(tab, text="Top 3 Sản phẩm được nhắc nhiều:", font=ctk.CTkFont(weight="bold")).grid(row=3, column=0, padx=10, pady=(10, 0), sticky="w")
        
        product_text = "Không có dữ liệu"
        products = MOCK_STATS.get("products_mentioned", {})
        if products:
             # Sort and format top 3
             sorted_products = sorted(products.items(), key=lambda item: item[1], reverse=True)[:3]
             product_text = "\n".join([f"- {name}: {count} lần" for name, count in sorted_products])
        
        ctk.CTkLabel(tab, text=product_text, justify="left").grid(row=4, column=0, padx=20, pady=(5, 10), sticky="w")


    def _create_scenario_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=2)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(tab, text="Quản lý Kịch Bản (CRUD Intents - Mock)", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w")
        
        # 1. Intent List (Left side)
        list_frame = ctk.CTkFrame(tab)
        list_frame.grid(row=1, column=0, rowspan=2, padx=(10, 5), pady=5, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(list_frame, text="Danh sách Intents:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        
        intent_names = [item["intent_name"] for item in self.scenario_intents]
        self.intent_listbox = tk.Listbox(list_frame, height=10, selectmode=tk.SINGLE, bg=list_frame.cget("fg_color")[1], fg="white", selectbackground=list_frame.cget("fg_color")[0])
        for name in intent_names:
             self.intent_listbox.insert(tk.END, name)
             
        self.intent_listbox.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="nsew")
        self.intent_listbox.bind('<<ListboxSelect>>', self._load_selected_intent)

        crud_button_frame = ctk.CTkFrame(list_frame)
        crud_button_frame.grid(row=2, column=0, padx=5, pady=5, sticky="ew")
        crud_button_frame.columnconfigure((0, 1), weight=1)
        ctk.CTkButton(crud_button_frame, text="➕ Thêm").grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        ctk.CTkButton(crud_button_frame, text="❌ Xóa").grid(row=0, column=1, padx=5, pady=5, sticky="ew")


        # 2. Detail/Edit Panel (Right side)
        self.detail_frame = ctk.CTkFrame(tab)
        self.detail_frame.grid(row=1, column=1, rowspan=2, padx=(5, 10), pady=5, sticky="nsew")
        self.detail_frame.grid_columnconfigure(0, weight=1)
        self.detail_frame.grid_rowconfigure(3, weight=1)
        
        ctk.CTkLabel(self.detail_frame, text="Chi tiết Intent:").grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        self.intent_name_label = ctk.CTkLabel(self.detail_frame, text="Intent Name: -", anchor="w")
        self.intent_name_label.grid(row=1, column=0, padx=10, pady=2, sticky="ew")
        
        ctk.CTkLabel(self.detail_frame, text="Phản hồi (1/n):", anchor="w").grid(row=2, column=0, padx=10, pady=(5, 0), sticky="ew")
        self.response_textbox = ctk.CTkTextbox(self.detail_frame, height=150)
        self.response_textbox.grid(row=3, column=0, padx=10, pady=(0, 5), sticky="nsew")
        self.response_textbox.insert("0.0", "Chọn một Intent để xem/sửa phản hồi.")
        self.response_textbox.configure(state="disabled")
        
        ctk.CTkButton(self.detail_frame, text="💾 Lưu Thay Đổi (Mock)").grid(row=4, column=0, padx=10, pady=(0, 10), sticky="ew")
        
        if intent_names:
            self.intent_listbox.select_set(0)
            self._load_selected_intent(None)

    def _load_selected_intent(self, event):
        """Tải dữ liệu intent đã chọn vào khung chi tiết."""
        if not self.intent_listbox.curselection():
            return

        selected_index = self.intent_listbox.curselection()[0]
        selected_name = self.intent_listbox.get(selected_index)
        
        intent_data = next((item for item in self.scenario_intents if item["intent_name"] == selected_name), None)

        if intent_data:
            self.intent_name_label.configure(text=f"Intent Name: {selected_name}")
            
            responses_text = "\n---\n".join(intent_data.get("responses", ["No responses defined."]))
            
            self.response_textbox.configure(state="normal")
            self.response_textbox.delete("0.0", "end")
            self.response_textbox.insert("0.0", responses_text)
            self.response_textbox.configure(state="disabled")
        else:
            self.intent_name_label.configure(text=f"Intent Name: {selected_name} (Not found in data)")
            self.response_textbox.configure(state="normal")
            self.response_textbox.delete("0.0", "end")
            self.response_textbox.insert("0.0", "Không tìm thấy dữ liệu kịch bản.")
            self.response_textbox.configure(state="disabled")

    def _create_sales_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(tab, text="Báo Cáo Doanh Số (Mock Data)", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        sales_data = MOCK_STATS.get("sales_data", [])
        
        ctk.CTkLabel(tab, text="Doanh số gần nhất:", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, padx=10, pady=(0, 5), sticky="w")
        
        # Table frame
        table_frame = ctk.CTkScrollableFrame(tab)
        table_frame.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_columnconfigure(1, weight=1)
        table_frame.grid_columnconfigure(2, weight=1)

        # Header
        ctk.CTkLabel(table_frame, text="Ngày", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=5, pady=2, sticky="ew")
        ctk.CTkLabel(table_frame, text="Doanh Số", font=ctk.CTkFont(weight="bold")).grid(row=0, column=1, padx=5, pady=2, sticky="e")
        ctk.CTkLabel(table_frame, text="CR", font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, padx=5, pady=2, sticky="e")

        # Data rows
        for i, row in enumerate(sales_data):
            date = row.get("date", "N/A")
            # Format tiền tệ
            sales = f"{row.get('sales', 0):,}".replace(",", "X").replace(".", ",").replace("X", ".") + " VND" 
            cr = f"{row.get('conversion_rate', 0.0)*100:.2f}%"
            
            ctk.CTkLabel(table_frame, text=date).grid(row=i+1, column=0, padx=5, pady=1, sticky="w")
            ctk.CTkLabel(table_frame, text=sales).grid(row=i+1, column=1, padx=5, pady=1, sticky="e")
            ctk.CTkLabel(table_frame, text=cr).grid(row=i+1, column=2, padx=5, pady=1, sticky="e")
            
        ctk.CTkLabel(tab, text="... (Báo cáo tổng hợp)").grid(row=3, column=0, padx=10, pady=10, sticky="w")

    # -------------------- LOGGING & CONFIG --------------------

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
        """Khởi tạo DialogManager và VoiceIOHandler trong một thread riêng."""
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
            
            is_ready = self.dm.is_ready() and self.voice_io.is_ready()
            
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
            self.log(f"❌ [APP] Lỗi khởi tạo core modules: {e}", "red")
            self.after(0, lambda: self.status_label.configure(text="Trạng Thái: 🔴 Lỗi Core"))
            self.dm_initialized = False 
            self.after(0, lambda: self._update_buttons(False))

    def _reinit_modules(self, *args):
        """Khởi tạo lại module khi API Key thay đổi."""
        if self._save_ui_config():
            self.log("🔄 [CONFIG] Config changed. Re-initializing DM...", "yellow")
            
            if self.dm and hasattr(self.dm, 'terminate'): 
                 try: self.dm.terminate()
                 except Exception: pass
                 
            if self.voice_io and hasattr(self.voice_io, 'terminate'):
                 try: self.voice_io.terminate()
                 except Exception: pass
            
            self.dm_initialized = False 
            self._update_buttons(False) 
            threading.Thread(target=self._initialize_core_modules, daemon=True).start()

    # -------------------- ACTION HANDLERS --------------------
    
    def stop_processing_command(self):
        """Gửi tín hiệu dừng tới thread xử lý và VoiceIO."""
        if self.is_processing:
            self.process_stop_event.set() # Set the flag to interrupt processing thread
            if self.voice_io:
                 self.voice_io.stop_event.set() # Dừng Playback (nếu đang nói)
            self.log("🛑 [PROCESS] Stop signal sent to processing thread.", "red")
        else:
            self.log("⚠️ [PROCESS] Không có tiến trình nào đang chạy để dừng.", "orange")

    def start_recording_command(self):
        """Bắt đầu ghi âm."""
        if self.is_recording or self.is_processing or self.is_speaking:
            self.log("⚠️ [IO] Đang bận. Không thể bắt đầu ghi âm.", "orange")
            return

        is_ready = self.dm and self.dm.is_ready() and self.voice_io and self.voice_io.is_ready()
        if not is_ready:
            error_msg = self.voice_io.get_initial_error() if self.voice_io and not self.voice_io.is_ready() else (self.dm.get_initial_error() if self.dm and not self.dm.is_ready() else "DM/IO Lỗi không xác định.")
            self.log(f"❌ [IO] DM/IO chưa sẵn sàng. Lỗi: {error_msg}", "red")
            messagebox.showerror("DM/IO Lỗi", f"Hệ thống chưa sẵn sàng để ghi âm. {error_msg}")
            return

        self.is_recording = True
        self.rec_start_time = time.time()
        self.asr_label.configure(text="User (ASR): Đang lắng nghe...")
        self.log("🎤 [IO] Bắt đầu ghi âm...", "yellow")
        self.progress_bar.set(0.0)

        self._update_buttons(False) # Force disable all buttons except Stop Rec

        try:
            success = self.voice_io.start_recording()
            if not success:
                 self.is_recording = False
                 self.log("❌ [IO] VoiceIOHandler không thể bắt đầu ghi âm.", "red")
                 messagebox.showerror("Lỗi Ghi Âm", "Không thể khởi động bộ ghi âm.")
                 self._update_buttons(self.dm.is_ready() if self.dm else False) 
        except Exception as e:
            self.is_recording = False
            self.log(f"❌ [IO] Lỗi khi start_recording: {e}", "red")
            messagebox.showerror("Lỗi Ghi Âm", f"Lỗi: {e}")
            self._update_buttons(self.dm.is_ready() if self.dm else False)


    def stop_recording_command(self):
        """Dừng ghi âm và bắt đầu xử lý dialog."""
        if not self.is_recording: return

        self.is_recording = False
        self.is_processing = True
        self.duration_label.configure(text="0.00s")
        self.log("🛑 [IO] Dừng ghi âm. Bắt đầu xử lý...", "yellow")

        self._update_buttons(False) # Force disable all buttons

        try:
            audio_file_path = self.voice_io.stop_recording()
            if not audio_file_path or not Path(audio_file_path).exists() or Path(audio_file_path).stat().st_size == 0:
                 raise FileNotFoundError("File ghi âm không được tạo hoặc rỗng.")
            
            self.log(f"💾 [IO] Audio saved to: {audio_file_path}", "cyan")
            self.after(0, lambda: self.progress_bar.set(0.1))

            # Start processing thread
            self.processing_thread = threading.Thread(target=self._process_dialog, args=(audio_file_path,), daemon=True)
            self.processing_thread.start()

        except Exception as e:
            self.is_processing = False 
            self.log(f"❌ [IO] Lỗi khi stop_recording/lưu file: {e}", "red")
            messagebox.showerror("Lỗi Ghi Âm", f"Lỗi dừng ghi âm: {e}")
            self._update_buttons(self.dm.is_ready() if self.dm else False) 


    def _process_dialog(self, audio_path: str):
        """Thực hiện chu trình ASR -> NLU -> LLM -> TTS."""
        start_time = time.time()
        self.process_stop_event.clear() # Clear the stop flag for the new process
        REQUEST_COUNTER.inc()
        response = {"response_text": "Lỗi xử lý chung.", "current_state": "ERROR", "db_info": {"error": "Processing failed"}, "user_input_asr": ""}

        try:
            self.log("🤖 [DM] Xử lý Dialog Manager...", "blue")
            self.after(0, lambda: self.progress_bar.set(0.2))

            if self.process_stop_event.is_set(): 
                self.log("🛑 [DM] Tiến trình bị hủy bởi người dùng.", "red"); return # Exit early
                
            if self.dm and self.dm.is_ready():
                response = self.dm.process_audio_file(audio_path)
                self.after(0, lambda: self.progress_bar.set(0.7))
            else:
                 response['error'] = "DM not ready for processing."
                 raise RuntimeError("DM not ready.")

            if self.process_stop_event.is_set(): 
                self.log("🛑 [DM] Tiến trình bị hủy bởi người dùng (sau ASR/NLU).", "red"); return # Exit early

            # 2. Extract and Log Results
            user_input_asr = response.get('user_input_asr', '[Không có ASR]')
            bot_response = response.get('response_text', '[Không có phản hồi]')
            current_state = response.get('current_state', 'N/A')
            db_info = response.get('db_info', {})
            nlu_intent = db_info.get('nlu_result', {}).get('intent', 'N/A')
            
            log_data_json = json.dumps({
                "timestamp": _dt.now().isoformat(),
                "user_input_asr": anonymize_text(user_input_asr),
                "response_text": anonymize_text(bot_response),
                "status": current_state,
                "nlu_result": db_info.get('nlu_result', {}),
                "duration": time.time() - start_time
            })
            log_to_file(log_data_json, LOG_FILE_PATH)
            
            self.log(f"📝 [TRANSACTION] ASR: {anonymize_text(user_input_asr[:50])} | Intent: {nlu_intent} | Status: {current_state}", "cyan")
            

            # 3. Update UI Chat
            self.after(0, lambda: self.asr_label.configure(text=f"User (ASR): {user_input_asr}"))
            self.after(0, lambda: self._append_chat_safe("User", user_input_asr, "User"))
            self.after(0, lambda: self._append_chat_safe("Bot", bot_response, "Bot"))
            self.log(f"💬 [DM] State={current_state}, Intent={nlu_intent}", "blue")

            # 4. Text-to-Speech (TTS)
            tts_path = response.get('response_audio_path', TEMP_TTS_FILE) 
            if os.path.exists(tts_path) and self.voice_io:
                 if self.process_stop_event.is_set(): # Check again before blocking play
                     self.log("🛑 [TTS] Phát âm thanh bị hủy.", "red"); return 
                 
                 self.is_speaking = True
                 self.log(f"🔈 [IO] Phát phản hồi từ: {os.path.basename(tts_path)}", "purple")
                 self.voice_io.play_audio_response(tts_path) 
                 self.is_speaking = False
            else:
                 self.log("⚠️ [TTS] Không tìm thấy file audio phản hồi hoặc VoiceIO chưa sẵn sàng.", "orange")

        except Exception as e:
            self.log(f"❌ [DM] Lỗi xử lý chính: {e}", "red")
            traceback_str = traceback.format_exc()
            self.log(f"    Traceback:\n{traceback_str}", "red")
            self.after(0, lambda: self._append_chat_safe("Error", "Lỗi xử lý: " + str(e), "error"))
            ERROR_COUNTER.inc()

        finally:
            self.is_processing = False
            self.is_speaking = False
            
            end_time = time.time()
            if self.process_stop_event.is_set():
                 self.log(f"⚠️ [APP] Tiến trình đã bị dừng sau {end_time - start_time:.2f}s.", "orange")
            else:
                 response_time = end_time - start_time
                 RESPONSE_TIME_GAUGE.set(response_time)
                 self.log(f"✅ [APP] Xử lý hoàn tất. Thời gian: {response_time:.2f}s", "green")
            
            self.process_stop_event.clear() # Ensure the flag is cleared on exit
            self.after(0, lambda: self.progress_bar.set(1.0))
            self._update_buttons(self.dm.is_ready() if self.dm else False) 

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
        
        if self.is_recording:
            self.record_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.stop_process_button.configure(state="disabled") 
            self.status_label.configure(text="Trạng Thái: 🔴 Đang Ghi Âm")
        elif self.is_processing or self.is_speaking:
            self.record_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
            self.stop_process_button.configure(state="normal") # Cho phép dừng tiến trình
            self.status_label.configure(text="Trạng Thái: 🟡 Đang Xử Lý/Nói...")
        elif is_dm_ready and is_io_ready:
            self.record_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.stop_process_button.configure(state="disabled") 
            self.status_label.configure(text="Trạng Thái: 🟢 Sẵn Sàng")
        else:
            self.record_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
            self.stop_process_button.configure(state="disabled") 
            io_error = self.voice_io.get_initial_error() if self.voice_io and not self.voice_io.is_ready() else "Core Lỗi"
            self.status_label.configure(text=f"Trạng Thái: 🔴 Lỗi ({io_error[:10]}...)")

    # -------------------- CLOSING HANDLER --------------------
    def _on_closing(self):
        """Dọn dẹp tài nguyên khi đóng ứng dụng."""
        self.log("👋 [APP] Ứng dụng đang đóng...", "yellow")
        self._save_ui_config() 
        
        # Signal any active process/recording to stop
        self.stop_processing_command() 
        time.sleep(0.5)

        if self.dm and hasattr(self.dm, 'terminate'):
            try: self.dm.terminate()
            except Exception as e: self.log(f"⚠️ [APP] Error terminating DM: {e}", "orange")

        if self.voice_io and hasattr(self.voice_io, 'terminate'):
            try: self.voice_io.terminate()
            except Exception as e: self.log(f"⚠️ [APP] Error terminating Voice IO: {e}", "orange")

        # Clean up temp files
        for f in [AUDIO_FILE, TEMP_TTS_FILE]:
            if f and os.path.exists(f):
                try: os.remove(f)
                except Exception as e: self.log(f"⚠️ [APP] Error deleting temp file {f}: {e}", "orange")

        self.destroy() 

# ==================== PHẦN III: KHỞI CHẠY ỨNG DỤNG ====================

if __name__ == "__main__":
    # Clean up temp files
    for f in [AUDIO_FILE, TEMP_TTS_FILE]:
        if f and os.path.exists(f): 
            try: os.remove(f)
            except Exception: pass
    
    # Start Prometheus
    try:
        if 'start_http_server' in globals() and start_http_server is not None:
             # Lấy PROMETHEUS_PORT từ globals, đã được đặt ở trên
            start_http_server(PROMETHEUS_PORT); styled_print(f"📈 [Metrics] Prometheus server on port {PROMETHEUS_PORT}", "green")
    except OSError as e:
         if "Address already in use" in str(e): styled_print(f"⚠️ [Metrics] Port {PROMETHEUS_PORT} in use.", "orange")
         else: styled_print(f"❌ [Metrics] Error starting Prometheus: {e}", "red")
    except Exception as e: styled_print(f"❌ [Metrics] Error starting Prometheus: {e}", "red")
    
    # Run App
    app = App()
    app.protocol("WM_DELETE_WINDOW", app._on_closing)
    app.mainloop()