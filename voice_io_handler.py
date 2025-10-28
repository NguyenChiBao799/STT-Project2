# voice_io_handler.py
import pyaudio
import wave
import os
import time 
import numpy as np 
import threading
from pathlib import Path
from typing import Optional, Dict, Callable 

try:
    # Import necessary constants safely
    from config_db import (
        SAMPLE_RATE, CHANNELS, AUDIO_FILE, CHUNK_SIZE
    )
except ImportError:
    # Fallback constants if config_db fails
    SAMPLE_RATE, CHANNELS, AUDIO_FILE, CHUNK_SIZE = 16000, 1, "user_input.wav", 1024
    print("⚠️ [IO] Failed to import from config_db, using fallback audio settings.")


class VoiceIOHandler:
    """
    Quản lý đầu vào (ghi âm WAV) và đầu ra (phát WAV) audio bằng PyAudio.
    Sử dụng stream callback để ghi âm non-blocking.
    """

    def __init__(self, log_callback: Callable, audio_file: str):
        self.log = log_callback
        self.audio_file = audio_file
        self.p: Optional[pyaudio.PyAudio] = None
        self.record_stream = None
        self.play_stream = None
        self.audio_frames = []
        self.is_recording_active = threading.Event()
        self.stop_event = threading.Event() # For stopping recording thread
        self.initial_error: Optional[str] = None # Store initialization error
        self._is_ready = False

        try:
            self.log("Initializing PyAudio...", "yellow")
            self.p = pyaudio.PyAudio()
            self._is_ready = True
            self.log("✅ [IO] PyAudio initialized successfully.", "green")

        except Exception as e:
            self.initial_error = f"PyAudio Init Error: {e}"
            self.log(f"❌ [IO] PyAudio initialization failed: {e}", "red")
            self._is_ready = False

    def is_ready(self) -> bool:
        return self._is_ready

    def get_initial_error(self) -> Optional[str]:
        return self.initial_error
    
    # -------------------- Ghi Âm --------------------

    def start_recording(self) -> bool:
        if not self._is_ready or self.is_recording_active.is_set():
            return False

        self.audio_frames = []
        self.is_recording_active.set()
        self.stop_event.clear() # Clear stop signal

        try:
            self.record_stream = self.p.open(format=pyaudio.paInt16,
                                             channels=CHANNELS,
                                             rate=SAMPLE_RATE,
                                             input=True,
                                             frames_per_buffer=CHUNK_SIZE,
                                             stream_callback=self._recording_callback)

            self.log("🎤 [IO] Recording started...", "blue")
            return True
        except Exception as e:
            self.is_recording_active.clear()
            self.log(f"❌ [IO] Error starting recording stream: {e}", "red")
            self.initial_error = f"Recording Start Error: {e}"
            return False

    def _recording_callback(self, in_data, frame_count, time_info, status):
        """Hàm callback của PyAudio stream."""
        if status:
            self.log(f"⚠️ [IO] Recording stream status warning: {status}", "orange")
        
        if self.is_recording_active.is_set():
            self.audio_frames.append(in_data)
            return (in_data, pyaudio.paContinue)
        else:
            return (in_data, pyaudio.paComplete)

    def stop_recording(self) -> Optional[str]:
        if not self.is_recording_active.is_set():
            self.log("⚠️ [IO] Stop recording called, but not active.", "orange")
            return None

        self.is_recording_active.clear()
        self.stop_event.set() # Signal main thread to wait for stream to complete
        self.log("🛑 [IO] Recording stop initiated. Waiting for stream to close...", "yellow")

        # Give the stream a moment to finish its current buffer
        time.sleep(0.5) 
        
        if self.record_stream:
            try:
                if self.record_stream.is_active():
                    self.record_stream.stop_stream()
                self.record_stream.close()
                self.record_stream = None
            except Exception as e:
                self.log(f"⚠️ [IO] Error closing recording stream: {e}", "orange")

        if not self.audio_frames:
            self.log("❌ [IO] No audio frames were recorded.", "red")
            return None
            
        # Lưu file WAV
        try:
            with wave.open(self.audio_file, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16))
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b''.join(self.audio_frames))
            
            self.log(f"💾 [IO] Audio saved to: {self.audio_file}", "green")
            return self.audio_file
        except Exception as e:
            self.log(f"❌ [IO] Error saving WAV file: {e}", "red")
            self.initial_error = f"WAV Save Error: {e}"
            return None
        finally:
            self.audio_frames = [] # Clear frames

    # -------------------- Phát Audio --------------------
    
    def play_audio_response(self, file_path: str):
        """Phát file WAV (blocking)."""
        if not os.path.exists(file_path):
            self.log(f"❌ [IO] Playback file not found: {file_path}", "red")
            return

        self.log(f"🔈 [IO] Playing audio: {Path(file_path).name}", "purple")
        
        wf = None
        stream = None
        try:
            # Sẽ thất bại nếu file_path không phải là WAV hợp lệ (không có WAV header)
            wf = wave.open(file_path, 'rb')
            
            # Open stream
            self.play_stream = self.p.open(format=self.p.get_format_from_width(wf.getsampwidth()),
                                            channels=wf.getnchannels(),
                                            rate=wf.getframerate(),
                                            output=True)
            stream = self.play_stream

            # Read data
            data = wf.readframes(CHUNK_SIZE)
            while data:
                # Kiểm tra nếu terminate được gọi trong khi đang phát
                if self.stop_event.is_set(): break 
                stream.write(data)
                data = wf.readframes(CHUNK_SIZE)

            self.log("✅ [IO] Playback finished.", "green")

        except Exception as e:
            self.log(f"❌ [IO] Error playing audio file '{file_path}': {e}", "red")
            self.initial_error = f"Playback Error: {e}" 
        finally:
            # Ensure resources are closed
            if stream:
                try: stream.close()
                except Exception: pass
            if wf:
                try: wf.close()
                except Exception: pass
            self.play_stream = None 

    def terminate(self):
        """Dọn dẹp tài nguyên PyAudio."""
        # Stop any active streams first
        self.stop_event.set() 
        time.sleep(0.1) 
        
        # Close recording stream
        if self.record_stream:
             try: 
                 if self.record_stream.is_active(): self.record_stream.stop_stream()
                 self.record_stream.close()
             except Exception: pass
             self.record_stream = None
        
        # Close playback stream
        if self.play_stream:
             try: 
                 if self.play_stream.is_active(): self.play_stream.stop_stream()
                 self.play_stream.close()
             except Exception: pass
             self.play_stream = None

        if self.p:
            self.log("🧹 [IO] Terminating PyAudio.", "yellow")
            try:
                self.p.terminate()
            except Exception as e:
                 self.log(f"⚠️ [IO] Error terminating PyAudio: {e}", "orange")
            self.p = None