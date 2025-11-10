# intent_whitelist.py

from typing import List, Callable, Optional, Set

# Danh sách các Intent (chủ đề) được phép xử lý bởi Dialog Manager.
ALLOWED_TOPIC_INTENTS: List[str] = [
    "chao_hoi",          # Chào hỏi
    "ask_price",         # Hỏi giá sản phẩm 
    "ask_promotion",     # Hỏi khuyến mãi 
    "order_product",     # Đặt hàng/mua sản phẩm
    "kiem_tra_don_hang", # Kiểm tra đơn hàng (Tích hợp CRM)
    "tam_biet",          # Tạm biệt/Kết thúc phiên
    "small_talk",        # Cho phép các câu xã giao đơn giản
]

class IntentWhitelist:
    """
    Lớp kiểm tra xem Intent được nhận diện có nằm trong danh sách các chủ đề 
    nghiệp vụ được hỗ trợ hay không (Whitelist Approach).
    """
    
    def __init__(self, log_callback: Optional[Callable] = None):
        self.log = log_callback or print
        self.allowed_intents: Set[str] = set(ALLOWED_TOPIC_INTENTS)
        
    def is_intent_supported(self, intent: str) -> bool:
        """
        Kiểm tra xem Intent có nằm trong Whitelist không.
        Các intent Fallback (no_match, fallback, fallback_no_speech) vẫn được 
        xem là True để Dialog Manager xử lý bằng cơ chế Fallback tiêu chuẩn.
        """
        if intent in ["no_match", "fallback", "fallback_no_speech", "error_nlu"]:
            return True 

        return intent in self.allowed_intents

    def get_unsupported_response(self) -> str:
        """Trả về phản hồi tiêu chuẩn khi câu hỏi nằm ngoài chủ đề cho phép."""
        return (
            "Xin lỗi, tôi là trợ lý AI chuyên về sản phẩm, khuyến mãi và đơn hàng của cửa hàng. "
            "Hiện tại, tôi không thể trả lời các câu hỏi về chủ đề này. Bạn có muốn hỏi về sản phẩm không?"
        )