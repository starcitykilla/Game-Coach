import customtkinter as ctk
import threading
import queue
import cv2
import time
import asyncio
from PIL import Image
from bot import CommanderBot
import config
import logging
import faulthandler

# Open the log file in append mode so we don't overwrite it
crash_file = open('bot_errors.log', 'a')

# Tell the OS to dump fatal C-level crashes (like SIGABRT) directly into our file
faulthandler.enable(file=crash_file)

# Set up the diary for the bot
logging.basicConfig(
    filename='bot_errors.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# A quick test message to make sure it works when you start the bot
logging.info("Bot is starting up!")

log_queue = queue.Queue()


def log_to_gui(type, message):
    log_queue.put((type, message))


class CommanderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("BMG's Virtual Vegas Software 🎰")
        self.geometry("1280x800")
        ctk.set_appearance_mode("Dark")
        self.bot = None
        self._init_layout()
        self.start_bot_thread()
        self.update_video()
        self.check_logs()

    def _init_layout(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.frame_video = ctk.CTkFrame(self)
        self.frame_video.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.lbl_video = ctk.CTkLabel(self.frame_video, text="Starting Camera...", font=("Consolas", 20))
        self.lbl_video.pack(fill="both", expand=True)

        self.frame_right = ctk.CTkFrame(self, width=300)
        self.frame_right.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        ctk.CTkLabel(self.frame_right, text="COMMAND CENTER", font=("Impact", 24)).pack(pady=10)

        self.frame_audio_dash = ctk.CTkFrame(self.frame_right, fg_color="transparent")
        self.frame_audio_dash.pack(pady=5)
        self.lbl_audio_indicator = ctk.CTkLabel(self.frame_audio_dash, text="🔴", font=("Arial", 20))
        self.lbl_audio_indicator.pack(side="left", padx=5)
        ctk.CTkLabel(self.frame_audio_dash, text="Game Audio Feed", font=("Arial", 12, "bold")).pack(side="left")

        # --- THE CLIP BUTTON ---
        self.btn_clip = ctk.CTkButton(self.frame_right, text="🎬 CLIP THAT!", fg_color="#1E90FF", hover_color="#0000CD",
                                      height=50, font=("Arial", 16, "bold"), command=self.run_manual_clip)
        self.btn_clip.pack(pady=15, padx=10, fill="x")

        self.btn_listen = ctk.CTkButton(self.frame_right, text="🎲 RUN ODDSMAKER", fg_color="red", hover_color="#8B0000",
                                        height=40, font=("Arial", 14, "bold"), command=self.run_oddsmaker)
        self.btn_listen.pack(pady=5, padx=10, fill="x")

        self.txt_chat = ctk.CTkTextbox(self.frame_right, height=250)
        self.txt_chat.pack(fill="both", expand=True, padx=5, pady=15)

    def start_bot_thread(self):
        threading.Thread(target=self.run_bot_logic, daemon=True).start()

    def run_bot_logic(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.bot = CommanderBot(log_callback=log_to_gui)
        try:
            loop.run_until_complete(self.bot.start())
        except KeyboardInterrupt:
            loop.run_until_complete(self.bot.close())
        finally:
            loop.close()

    def run_oddsmaker(self):
        if self.bot: threading.Thread(target=self.bot._run_manual_oddsmaker_thread, daemon=True).start()

    def run_manual_clip(self):
        if self.bot: self.bot.trigger_manual_clip()

    def check_logs(self):
        while not log_queue.empty():
            type, msg = log_queue.get()
            self.txt_chat.insert("end", f"[{type}] {msg}\n")
            self.txt_chat.see("end")
        self.after(100, self.check_logs)

    def update_video(self):
        if self.bot and hasattr(self.bot, 'eyes') and self.bot.eyes:
            frame = self.bot.eyes.get_frame()
            if frame is not None:
                frame = cv2.resize(frame, (480, 270))
                img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(480, 270))
                self.lbl_video.configure(image=ctk_img, text="")

        if self.bot and hasattr(self.bot, 'ears') and self.bot.ears:
            if self.bot.ears.current_volume > 50:
                self.lbl_audio_indicator.configure(text="🟢")
            else:
                self.lbl_audio_indicator.configure(text="🔴")

        self.after(33, self.update_video)


if __name__ == "__main__":
    app = CommanderGUI()
    app.mainloop()
