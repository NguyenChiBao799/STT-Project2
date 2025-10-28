# training_module.py
import json
import time
import numpy as np
import random
import os
# Các thư viện sklearn được sử dụng để minh họa logic training
# from sklearn.model_selection import train_test_split
# from sklearn.feature_extraction.text import TfidfVectorizer
# from sklearn.linear_model import LogisticRegression
# from sklearn.metrics import classification_report

# Giả định: Dữ liệu huấn luyện mẫu
TRAINING_DATA_MOCK = [
    ("Sản phẩm A có khuyến mãi không?", "ask_promotion"),
    ("Giá của sản phẩm B là bao nhiêu?", "ask_price"),
    ("Tôi muốn mua sản phẩm C", "order_product"),
    ("Có giảm giá cho sản phẩm này không?", "ask_promotion"),
    ("Kiểm tra giá sản phẩm D", "ask_price"),
    ("Đơn hàng của tôi ở đâu?", "check_status"),
    ("Sản phẩm nào đang hot?", "ask_trending"),
    ("Tôi muốn đặt hàng gấp", "order_product")
]

class ModelTrainer:
    """
    Quản lý luồng huấn luyện và đánh giá mô hình NLU (Intent Classifier) đơn giản (Mock).
    """
    
    def __init__(self, log_callback, model_output_path="nlu_model.pkl"):
        self.log = log_callback
        self.model_output_path = model_output_path
        self.is_trained = os.path.exists(model_output_path) # Giả lập kiểm tra
        self.log(f"🤖 [TRAINING] Khởi tạo ModelTrainer. Đã có mô hình: {self.is_trained}", color="yellow")
        
    def train_nlu_model(self):
        """Mô phỏng quy trình huấn luyện, đánh giá và lưu mô hình."""
        
        self.log("🤖 [TRAINING] Bắt đầu mô phỏng huấn luyện mô hình NLU...", color="yellow")
        
        # 1. Tải và chuẩn bị dữ liệu (Mock)
        texts = [data[0] for data in TRAINING_DATA_MOCK]
        intents = [data[1] for data in TRAINING_DATA_MOCK]
        
        self.log(f"📚 [TRAINING] Đã tải {len(texts)} mẫu dữ liệu.", color="yellow")
        time.sleep(1) # Giả lập thời gian chuẩn bị
        
        # 2. Huấn luyện (Mô phỏng)
        self.log("⚙️ [TRAINING] Đang mô phỏng huấn luyện Logistic Regression...", color="yellow")
        time.sleep(random.uniform(2, 4)) # Giả lập thời gian huấn luyện
        
        # 3. Đánh giá (Mô phỏng)
        # Bỏ qua logic sklearn thực tế, chỉ ghi log thành công
        self.log("✅ [TRAINING] Đánh giá mô phỏng hoàn tất. Độ chính xác: 95.0%", color="green")
        
        self.is_trained = True
        
        # 4. Lưu mô hình (Mô phỏng)
        try:
            # Tạo file giả lập mô hình
            with open(self.model_output_path, 'w') as f:
                f.write("Mock NLU Model Content")
            self.log(f"💾 [TRAINING] Mô hình được lưu tại: {self.model_output_path}", color="green")
        except Exception as e:
            self.log(f"❌ [TRAINING] Lỗi khi lưu mô hình: {e}", color="red")
            return False
        
        return True

    def mock_predict(self, text):
        """Mô phỏng dự đoán ý định (chỉ dùng để kiểm tra tính năng huấn luyện)."""
        if not self.is_trained:
            return "fallback"

        # Dùng logic mock đơn giản cho mục đích minh họa
        if "khuyến mãi" in text.lower() or "giảm giá" in text.lower():
            return "ask_promotion"
        elif "giá" in text.lower():
            return "ask_price"
        else:
            return "check_status"
