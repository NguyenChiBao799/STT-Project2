# dialog_manager.py
import time
import uuid
import re
from config_db import ConfigDB, NLU_CONFIDENCE_THRESHOLD

# Fallback an toàn cho các module phụ thuộc
try:
    from db_connector import CorporateAPIConnector
except ImportError:
    # Định nghĩa Mock class nếu không tìm thấy file
    class CorporateAPIConnector:
        def __init__(self, log): self.log=log
        def get_order_status(self, *args): return {}, "Lỗi DB: Không tìm thấy đơn hàng (Mock)."
        def get_product_price(self, *args): return {}, "Lỗi DB: Không tìm thấy sản phẩm (Mock)."
        def get_product_features(self, *args): return {}, "Lỗi DB: Không tìm thấy sản phẩm (Mock)."
        def get_script_content(self, *args): return {}, "Lỗi DB: Không tìm thấy kịch bản (Mock)."

try:
    from response_generator import ResponseGenerator
except ImportError:
    class ResponseGenerator:
        def __init__(self, api_key, log): self.log=log; self.api_key=api_key
        def generate_response(self, *args, **kwargs): return "Lỗi LLM: Response Generator không khả dụng."
        def generate_tts(self, *args): return None # Không tạo file TTS

try:
    from metrics_layer import MetricsLayer
except ImportError:
    class MetricsLayer:
        def __init__(self, log_callback): self.log = log_callback
        def record_metric(self, *args): pass

def anonymize_text(text):
    """Ẩn danh các thông tin nhạy cảm."""
    if not text: return ""
    text = re.sub(r'(?:0|\+84)\d{9,10}', 'PHONE_NUMBER', text)
    text = re.sub(r'ord\d{3,}', 'ORDER_ID', text, flags=re.IGNORECASE)
    text = re.sub(r'u\d{3,}', 'USER_ID', text, flags=re.IGNORECASE)
    return text

class DialogManager:
    """Quản lý luồng hội thoại, trạng thái, và gọi các module NLU/DB/LLM."""

    def __init__(self, log_callback, api_key_var, nlu_mode_var, db_mode_var):
        self.log = log_callback
        self.api_key_var = api_key_var
        self.nlu_mode_var = nlu_mode_var
        self.db_mode_var = db_mode_var
        self.is_ready = False # <-- THÊM: Thuộc tính is_ready

        self.db_connector = None
        self.metrics_layer = None
        self.response_generator = None

        self._initialize_core_modules() # Gọi hàm khởi tạo core modules

        self.session_id = str(uuid.uuid4())
        self.current_state = ConfigDB.INITIAL_STATE
        self.context_history = []

        # Chỉ log nếu khởi tạo thành công
        if self.is_ready:
            self.log(f"🧠 [DialogManager] Khởi tạo Session ID: {self.session_id}", "cyan")
            self.log(f"🌐 [DialogManager] Trạng thái khởi đầu: {self.current_state}", "cyan")

    def _initialize_core_modules(self):
        """Khởi tạo các lớp phụ thuộc."""
        self.log("⚙️ [DialogManager] Khởi tạo Core Modules...", "cyan")
        self.is_ready = False # Đặt lại trạng thái khi khởi tạo lại

        try:
            self.db_connector = CorporateAPIConnector(self.log)
            self.metrics_layer = MetricsLayer(self.log) # Sử dụng fallback nếu cần
            self.response_generator = ResponseGenerator(self.api_key_var, self.log)
            _ = ConfigDB.STATE_CONFIG # Kiểm tra config
            self.is_ready = True # <-- SET: Đặt is_ready thành True nếu thành công
            self.log("✅ [DialogManager] Core Modules đã sẵn sàng.", "green")
        except Exception as e:
            self.log(f"❌ [Core] Lỗi khởi tạo Dialog Manager: {e}", "red")
            self.is_ready = False # Giữ is_ready là False nếu lỗi

    def reset_session(self):
        """Đặt lại trạng thái hội thoại."""
        self.session_id = str(uuid.uuid4())
        self.current_state = ConfigDB.INITIAL_STATE
        self.context_history = []
        self.log("🔄 [DialogManager] Đã đặt lại phiên hội thoại mới.", "cyan")

    def _execute_tool(self, intent, entities):
        """Xử lý tác vụ nghiệp vụ (Tool/API/DB) dựa trên Intent."""
        tool_response = None
        db_info = {}
        db_mode = self.db_mode_var.get()

        self.log(f"🛠️ [DM] Thực thi Tool cho Intent: {intent} (DB Mode: {db_mode})", "yellow")

        # 1. Xử lý các Intent Ưu tiên (Rule-based)
        # Sử dụng .get() để tránh KeyError nếu intent không có trong PRIORITY_RULES
        priority_rule = ConfigDB.PRIORITY_RULES.get(intent)
        if priority_rule:
            rule_intent = priority_rule.get("intent")
            if rule_intent == "stop_conversation":
                 self.current_state = "END_CONVERSATION"
                 tool_response = ConfigDB.STATE_CONFIG[self.current_state]["prompt"]
                 return None, tool_response
            elif rule_intent == "get_promotion": # Ví dụ xử lý rule khuyến mãi
                 db_info, tool_response = self.db_connector.get_script_content("promotion_script") # Giả sử có script này

        # 2. Xử lý Tra cứu (Dùng CorporateAPIConnector)
        elif intent.startswith("tra_cuu_") or intent == "check_order_status": # Bao gồm cả check_order_status
            if intent == "check_order_status":
                order_id = entities.get("order_id")
                user_id = entities.get("user_id")
                if order_id or user_id:
                     db_info, tool_response = self.db_connector.get_order_status(order_id or "UNKNOWN", mode=db_mode) # Truyền order_id vào
                else:
                    tool_response = ConfigDB.STATE_CONFIG["CHECK_ORDER"]["prompt"]

            elif intent == "tra_cuu_gia" and entities.get("product"):
                product_name = entities["product"]
                db_info, tool_response = self.db_connector.get_product_price(product_name, db_mode)

            elif intent == "tra_cuu_tinh_nang" and entities.get("product"):
                product_name = entities["product"]
                db_info, tool_response = self.db_connector.get_product_features(product_name, db_mode)

            elif intent == "tra_cuu_kich_ban" and entities.get("script_name"):
                script_name = entities["script_name"]
                db_info, tool_response = self.db_connector.get_script_content(script_name)

            elif intent == "unknown_product":
                tool_response = "Tôi có thể giúp bạn tra cứu thông tin về Vision, Exciter hoặc SH Mode."

            else:
                tool_response = "Xin lỗi, yêu cầu tra cứu của bạn thiếu thông tin sản phẩm/đơn hàng. Vui lòng cung cấp thêm chi tiết."

        # 3. Xử lý Chuyển trạng thái dựa trên Intent khác
        else:
            next_state_key = ConfigDB.INTENT_TO_STATE.get(intent)
            if next_state_key:
                self.current_state = next_state_key
                # Lấy prompt từ state config, fallback nếu state không tồn tại
                tool_response = ConfigDB.STATE_CONFIG.get(self.current_state, ConfigDB.STATE_CONFIG["FALLBACK"])["prompt"]
                self.log(f"🔄 [DM/State] Chuyển trạng thái sang: {self.current_state}", "cyan")
            else:
                 tool_response = ConfigDB.STATE_CONFIG["FALLBACK"]["prompt"]


        if db_info and "state_transition" in db_info:
            self.current_state = db_info["state_transition"]
            self.log(f"🔄 [DM/DB] Cập nhật trạng thái từ DB Tool sang: {self.current_state}", "cyan")

        if not tool_response:
             tool_response = ConfigDB.STATE_CONFIG["FALLBACK"]["prompt"]

        return db_info, tool_response

    def process_turn_with_logging(self, nlu_result):
        """Xử lý một lượt hội thoại hoàn chỉnh."""
        if not self.is_ready:
            # Trả về lỗi nếu DM chưa sẵn sàng
            return {
                "response_text": "Lỗi: Dialog Manager chưa sẵn sàng.",
                "response_audio_path": None,
                "current_state": "ERROR",
                "db_info": {"error": "DM not initialized"}
            }

        asr_text = nlu_result.get('text', '') # Dùng get để tránh KeyError
        intent = nlu_result.get('intent', 'fallback') # Fallback nếu không có intent
        entities = nlu_result.get('entities', {})

        db_info, tool_response_text = self._execute_tool(intent, entities)

        response_text = self.response_generator.generate_response(
            prompt=asr_text,
            context=self.context_history,
            tool_response=tool_response_text
        )

        self.context_history.append({"user": asr_text, "system": response_text, "intent": intent, "entities": entities})

        if db_info and "error" in db_info:
            self.log(f"⚠️ [DM] Có lỗi từ DB/API: {db_info['error']}", color="red")

        tts_path = self.response_generator.generate_tts(response_text)

        return {
            "response_text": response_text,
            "response_audio_path": tts_path,
            "current_state": self.current_state,
            "db_info": db_info
        }