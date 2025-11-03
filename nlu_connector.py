# nlu_connector.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
import time

# --- SAFE IMPORT CONFIG ---
try:
    from config_db import NLU_CONFIG
except ImportError:
    NLU_CONFIG = {"intents": []}
    
# ==================== BASE INTERFACE ====================
class INLUClient(ABC):
    """Interface cho các hệ thống NLU (thực hoặc mock)."""
    @abstractmethod
    def get_intent(self, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pass
        
# ==================== IMPLEMENTATION MOCK ====================
class NLUClientMock(INLUClient):
    """Mock class cho NLU, nhận diện intent dựa trên keywords đơn giản."""
    def __init__(self, log_callback: Callable, config: Dict[str, Any]):
        self._log = log_callback
        self.intents = config.get("intents", [])
        self._log("⚠️ [NLU] Sử dụng NLUClient MOCK.")

    def get_intent(self, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        text_lower = text.lower().strip()
        
        for intent_data in self.intents:
            intent_name = intent_data.get("intent_name")
            keywords = intent_data.get("keywords", [])
            
            for keyword in keywords:
                if keyword in text_lower:
                    self._log(f"✅ [NLU MOCK] Đã tìm thấy intent: {intent_name} (Keyword: '{keyword}')")
                    return {
                        "intent": intent_name,
                        "confidence": 0.99, 
                        "entities": {}
                    }

        self._log(f"❌ [NLU MOCK] Không tìm thấy intent khớp cho: '{text_lower[:20]}...'")
        return {"intent": "no_match", "confidence": 0.00, "entities": {}}

# ==================== FACTORY FUNCTION ====================
def NLUClientFactory(mode: str, log_callback: Callable, config: Dict[str, Any]):
    """Chọn client NLU dựa trên mode."""
    if mode == "MOCK":
        return NLUClientMock(log_callback, config)
    # TODO: Thêm các chế độ khác (ví dụ: mode == "LLM" cho NLUClientLLM)
    else:
        log_callback(f"⚠️ [NLU] Chế độ NLU '{mode}' không được hỗ trợ. Dùng MOCK.")
        return NLUClientMock(log_callback, config)