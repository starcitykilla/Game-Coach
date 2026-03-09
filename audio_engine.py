import json
import threading
import pyaudio
import numpy as np
from vosk import Model, KaldiRecognizer, SetLogLevel
from ctypes import cdll, c_char_p, c_int, CFUNCTYPE

class AudioEngine:
    """Local, offline speech-to-text transcriber using Vosk."""
    def __init__(self, model_path="model"):
        self.transcript = []
        self.running = True
        self.current_volume = 0
        
        # Mute Vosk and Linux ALSA terminal spam
        SetLogLevel(-1) 
        ERROR_HANDLER = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
        try:
            asound = cdll.LoadLibrary('libasound.so')
            asound.snd_lib_error_set_handler(ERROR_HANDLER(lambda *args: None))
        except OSError: pass

        try:
            self.model = Model(model_path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.p = pyaudio.PyAudio()
            self.stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=8000)
            self.stream.start_stream()
            threading.Thread(target=self._listen_loop, daemon=True).start()
        except Exception as e:
            print(f"⚠️ AudioEngine failed to start: {e}")
            self.running = False

    def _listen_loop(self):
        while self.running:
            try:
                data = self.stream.read(4000, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                self.current_volume = int(np.abs(audio_data).mean()) # Used for GUI indicator

                if self.recognizer.AcceptWaveform(data):
                    text = json.loads(self.recognizer.Result()).get("text", "")
                    if text:
                        self.transcript.append(text)
                        if len(self.transcript) > 5: self.transcript.pop(0)
            except Exception: pass

    def get_transcript(self):
        return " ".join(self.transcript)

    def __del__(self):
        self.running = False
        if hasattr(self, 'stream'): self.stream.stop_stream(); self.stream.close()
        if hasattr(self, 'p'): self.p.terminate()
