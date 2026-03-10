import cv2
import time
import threading
import collections
import pytesseract
import concurrent.futures


class VisionEngine:
    def __init__(self, camera_index=0):
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.frame_buffer = collections.deque(maxlen=90)
        self.current_frame = None
        self.running = True
        threading.Thread(target=self._update_loop, daemon=True).start()

    def _update_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                self.current_frame = frame
                self.frame_buffer.append(frame)
            time.sleep(0.01)

    def get_frame(self):
        return self.current_frame

    def get_buffered_frame(self, frames_back=45):
        return self.current_frame if len(self.frame_buffer) < frames_back else self.frame_buffer[
            len(self.frame_buffer) - frames_back]

    def read_screen_text(self):
        if (frame := self.get_frame()) is None: return None
        gray = cv2.cvtColor(cv2.resize(frame, (1280, 720)), cv2.COLOR_BGR2GRAY)

        big_subs = cv2.resize(gray[500:650, 200:1080], None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        _, clean_subs = cv2.threshold(cv2.GaussianBlur(big_subs, (5, 5), 0), 0, 255,
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, clean_ui = cv2.threshold(cv2.GaussianBlur(gray, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        zones = {"tl": clean_ui[0:120, 0:640], "tr": clean_ui[0:120, 640:1280], "subs": clean_subs,
                 "bot": clean_ui[630:720, 0:1280]}

        def read_zone(zone): return pytesseract.image_to_string(zone, config=r'--oem 3 --psm 11').strip()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            res = {key: executor.submit(read_zone, zone) for key, zone in zones.items()}
        return f"TOP LEFT: {res['tl'].result()} | TOP RIGHT: {res['tr'].result()} | SUBTITLES: {res['subs'].result()} | BOTTOM: {res['bot'].result()}"

    def __del__(self):
        self.running = False
        if self.cap.isOpened(): self.cap.release()
