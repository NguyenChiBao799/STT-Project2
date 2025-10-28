# test_rtc_stream.py

import pytest
import asyncio
from typing import AsyncGenerator, List, Tuple
import time 
import os # THÊM
import uuid # THÊM

# Import class cần kiểm thử và hằng số
from rtc_integration_layer import RTCStreamProcessor, RECORDING_DIR 

# ==================== CÁC HÀM HỖ TRỢ KIỂM THỬ ====================

async def mock_audio_stream(num_chunks: int, chunk_size: int = 4096) -> AsyncGenerator[bytes, None]:
    """Tạo một Async Generator giả lập luồng audio (bytes)."""
    for i in range(num_chunks):
        yield b'\x00' * chunk_size
        # Tối ưu: Chỉ nhường quyền điều khiển event loop
        await asyncio.sleep(0) 

async def collect_output_stream(output_stream: AsyncGenerator[bytes, None]) -> List[bytes]:
    """Tiêu thụ và thu thập tất cả chunks từ luồng đầu ra."""
    chunks = []
    async for chunk in output_stream:
        chunks.append(chunk)
    return chunks

# ==================== FIXTURES ====================

@pytest.fixture
def rtc_processor() -> RTCStreamProcessor:
    """Fixture khởi tạo RTCStreamProcessor với hàm log câm."""
    def mock_log(message, color=None):
        pass 
    return RTCStreamProcessor(log_callback=mock_log)

# ==================== CÁC TRƯỜNG HỢP KIỂM THỬ CHÍNH ====================

@pytest.mark.asyncio
async def test_successful_order_request(rtc_processor: RTCStreamProcessor):
    NUM_CHUNKS = 100 
    session_id = str(uuid.uuid4())
    expected_filename = os.path.join(RECORDING_DIR, f"{session_id}_input.wav")
    
    # Dọn dẹp môi trường
    if os.path.exists(expected_filename):
        os.remove(expected_filename)

    input_stream = mock_audio_stream(NUM_CHUNKS)
    # ⚠️ THAY ĐỔI: Truyền session_id
    output_stream = rtc_processor.handle_rtc_session(input_stream, session_id=session_id)
    output_chunks = await collect_output_stream(output_stream)
    
    # 1. Xác minh file ghi âm
    assert os.path.exists(expected_filename), f"File ghi âm {expected_filename} không được tạo."
    assert os.path.getsize(expected_filename) > 44, "File ghi âm quá nhỏ."
    os.remove(expected_filename) # Xóa file sau khi kiểm thử

    # 2. Xác minh logic RTC
    assert len(output_chunks) > 0
    full_output = b"".join(output_chunks).decode('utf-8')
    assert "audio_chunk_for_Đã tìm thấy y" in full_output

@pytest.mark.asyncio
async def test_unrecognized_request(rtc_processor: RTCStreamProcessor):
    NUM_CHUNKS = 0 
    session_id = str(uuid.uuid4())
    expected_filename = os.path.join(RECORDING_DIR, f"{session_id}_input.wav")
    
    if os.path.exists(expected_filename):
        os.remove(expected_filename)

    input_stream = mock_audio_stream(NUM_CHUNKS)
    # ⚠️ THAY ĐỔI: Truyền session_id
    output_stream = rtc_processor.handle_rtc_session(input_stream, session_id=session_id)
    output_chunks = await collect_output_stream(output_stream)
    
    # 1. Xác minh file ghi âm (File sẽ rất nhỏ do không có chunk audio, nhưng vẫn phải có header)
    assert os.path.exists(expected_filename), f"File ghi âm {expected_filename} không được tạo."
    # Khi NUM_CHUNKS = 0, file vẫn được tạo với header WAV (44 bytes)
    assert os.path.getsize(expected_filename) == 44, "File ghi âm phải có kích thước header chuẩn (44 bytes)."
    os.remove(expected_filename) 
    
    # 2. Xác minh logic RTC
    assert len(output_chunks) > 0
    full_output = b"".join(output_chunks).decode('utf-8')
    assert "audio_chunk_for_Tôi không h" in full_output


@pytest.mark.asyncio
async def test_latency_is_acceptable(rtc_processor: RTCStreamProcessor):
    """
    Kiểm tra tổng thời gian xử lý có nằm trong giới hạn đã xiết chặt (1.0s).
    """
    NUM_CHUNKS = 5
    session_id = str(uuid.uuid4())
    expected_filename = os.path.join(RECORDING_DIR, f"{session_id}_input.wav")
    
    start_time = time.time()
    
    input_stream = mock_audio_stream(NUM_CHUNKS)
    # ⚠️ THAY ĐỔI: Truyền session_id
    output_stream = rtc_processor.handle_rtc_session(input_stream, session_id=session_id)
    
    await collect_output_stream(output_stream)
    
    duration = time.time() - start_time
    MAX_DURATION_SECONDS = 1.0 
    
    # 1. Xác minh file ghi âm và xóa nó
    assert os.path.exists(expected_filename), f"File ghi âm {expected_filename} không được tạo trong test latency."
    os.remove(expected_filename)
    
    # 2. Xác minh latency
    assert duration < MAX_DURATION_SECONDS, f"Thời gian xử lý quá lâu: {duration:.3f}s (Max: {MAX_DURATION_SECONDS}s)"