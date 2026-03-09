import cv2
import time
import threading
import collections
import pytesseract
import concurrent.futures

class VisionEngine:
    """Captures gameplay frames and reads UI text simultaneously using multithreading."""
    def __init__(self, camera_index=0):
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        # Keeps the last 90 frames so we can grab highlight clips retroactively
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
        if len(self.frame_buffer) < frames_back: return self.current_frame
        return self.frame_buffer[len(self.frame_buffer) - frames_back]

    def read_screen_text(self):
        """Reads 4 zones of the screen simultaneously to prevent lag."""
        frame = self.get_frame()
        if frame is None: return None
        gray = cv2.cvtColor(cv2.resize(frame, (1280, 720)), cv2.COLOR_BGR2GRAY)

        zones = {
            "tl": gray[0:120, 0:640],     "tr": gray[0:120, 640:1280],
            "bot": gray[630:720, 0:1280], "cen": gray[280:440, 300:980]
        }

        def read_zone(zone): return pytesseract.image_to_string(zone, config=r'--oem 3 --psm 11').strip()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = {key: executor.submit(read_zone, zone) for key, zone in zones.items()}
            
        return f"TOP LEFT: {results['tl'].result()} | TOP RIGHT: {results['tr'].result()} | BOTTOM: {results['bot'].result()} | CENTER: {results['cen'].result()}"

    def __del__(self):
        self.running = False
        if self.cap.isOpened(): self.cap.release()
