import json
import threading
import pyaudio
import numpy as np
from vosk import Model, KaldiRecognizer, SetLogLevel
from ctypes import cdll, c_char_p, c_int, CFUNCTYPE

ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)


def py_error_handler(filename, line, function, err, fmt): pass


c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)


class AudioEngine:
    """Local, offline speech-to-text transcriber using Vosk, equipped with vocal isolation filters."""

    def __init__(self, model_path="model"):
        self.transcript = []
        self.current_partial = ""
        self.running = True
        self.current_volume = 0

        SetLogLevel(-1)
        try:
            asound = cdll.LoadLibrary('libasound.so')
            asound.snd_lib_error_set_handler(c_error_handler)
        except OSError:
            pass

        try:
            self.model = Model(model_path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.p = pyaudio.PyAudio()
            self.stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True,
                                      frames_per_buffer=8000)
            self.stream.start_stream()
            threading.Thread(target=self._listen_loop, daemon=True).start()
        except Exception as e:
            print(f"⚠️ AudioEngine failed to start: {e}")
            self.running = False

    def _listen_loop(self):
        while self.running:
            try:
                # 1. Grab the raw audio chunk from the PS5/Mic
                raw_data = self.stream.read(4000, exception_on_overflow=False)
                audio_data = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32)

                self.current_volume = int(np.abs(audio_data).mean())

                # --- THE VOCAL ISOLATION FILTERS ---

                # Filter A: Pre-Emphasis (Boosts vocal clarity, dampens deep bass)
                # This mathematically subtracts the previous audio sample from the current one
                audio_data[1:] = audio_data[1:] - 0.95 * audio_data[:-1]

                # Filter B: The Noise Gate (Crush background hum to pure silence)
                # NOTE: If Vosk stops hearing you, lower this 300 to 150. If it hears too much noise, raise it to 500!
                noise_threshold = 300
                audio_data = np.where(np.abs(audio_data) < noise_threshold, 0, audio_data)

                # 2. Convert the freshly filtered audio back into bytes for Vosk
                filtered_data = audio_data.astype(np.int16).tobytes()

                # 3. Feed the clean, filtered audio into the AI
                if self.recognizer.AcceptWaveform(filtered_data):
                    text = json.loads(self.recognizer.Result()).get("text", "")
                    if text:
                        self.transcript.append(text)
                        if len(self.transcript) > 5: self.transcript.pop(0)
                    self.current_partial = ""
                else:
                    partial = json.loads(self.recognizer.PartialResult()).get("partial", "")
                    if partial:
                        self.current_partial = partial

            except Exception:
                pass

    def get_transcript(self):
        full_text = " ".join(self.transcript)
        if self.current_partial:
            full_text += f" {self.current_partial}..."
        return full_text.strip()

    def __del__(self):
        self.running = False
        if hasattr(self, 'stream'): self.stream.stop_stream(); self.stream.close()
        if hasattr(self, 'p'): self.p.terminate()
