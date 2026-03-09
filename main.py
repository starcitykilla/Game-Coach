import customtkinter as ctk
import threading
import queue
import cv2
import asyncio
from PIL import Image
import logging
import faulthandler

from bot import CommanderBot
from ai_input import AIInputWindow

# Dump fatal crashes cleanly
faulthandler.enable(file=open('bot_errors.log', 'a'))
logging.basicConfig(filename='bot_errors.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
log_queue = queue.Queue()

def log_to_gui(type, message): log_queue.put((type, message))

class CommanderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("BMG's Virtual Vegas Software 🎰")
        self.geometry("1280x800")
        ctk.set_appearance_mode("Dark")
        self.bot, self.current_ctk_image, self.coach_window, self.ai_input_window = None, None, None, None
        
        self._init_layout()
        threading.Thread(target=self.run_bot_logic, daemon=True).start()
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

        # Audio Indicator
        self.frame_audio_dash = ctk.CTkFrame(self.frame_right, fg_color="transparent")
        self.frame_audio_dash.pack(pady=5)
        self.lbl_audio_indicator = ctk.CTkLabel(self.frame_audio_dash, text="●", font=("Arial", 24), text_color="#FF0000")
        self.lbl_audio_indicator.pack(side="left", padx=5)
        ctk.CTkLabel(self.frame_audio_dash, text="Game Audio Feed", font=("Arial", 12, "bold")).pack(side="left")

        # Control Buttons
        ctk.CTkButton(self.frame_right, text="🎬 CLIP THAT!", fg_color="#1E90FF", height=50, font=("Arial", 16, "bold"), command=lambda: self.bot and self.bot.trigger_manual_clip()).pack(pady=15, padx=10, fill="x")
        ctk.CTkButton(self.frame_right, text="🧠 LAUNCH TACTICAL BOOTH", fg_color="#FF8C00", height=40, font=("Arial", 14, "bold"), command=self.open_coach_popout).pack(pady=5, padx=10, fill="x")
        ctk.CTkButton(self.frame_right, text="📡 VIEW AI INPUTS", fg_color="#8A2BE2", height=40, font=("Arial", 14, "bold"), command=self.open_ai_input_popout).pack(pady=5, padx=10, fill="x")

        self.txt_chat = ctk.CTkTextbox(self.frame_right, height=250)
        self.txt_chat.pack(fill="both", expand=True, padx=5, pady=15)

    def run_bot_logic(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.bot = CommanderBot(log_callback=log_to_gui)
        try: self.bot.run()
        except Exception as e: log_to_gui("CRASH", f"Bot Thread Died: {e}")
        finally: loop.close()

    def open_coach_popout(self):
        if self.coach_window and self.coach_window.winfo_exists(): return self.coach_window.focus()
        self.coach_window = ctk.CTkToplevel(self)
        self.coach_window.title("Tactical Booth Pop-Out")
        self.coach_window.geometry("400x250")
        self.coach_window.attributes('-topmost', True) 
        self.txt_coach_notes = ctk.CTkTextbox(self.coach_window, wrap="word", font=("Arial", 16, "bold"), fg_color="black", text_color="white", border_color="yellow", border_width=2)
        self.txt_coach_notes.pack(fill="both", expand=True, padx=10, pady=10)
        self.update_coach_popout()

    def update_coach_popout(self):
        if self.coach_window and self.coach_window.winfo_exists():
            text = "Waiting for game data..."
            if self.bot and self.bot.current_opponent:
                notes = self.bot.brain.get_scout_notes(self.bot.current_opponent, self.bot.current_game)
                text = f"🎯 TARGET: {self.bot.current_opponent.upper()}\n" + ("-"*30) + "\n\n"
                text += "\n\n".join([f"🔥 {n}" for n in notes[:3]]) if notes else text + "Scanning..."
            if self.txt_coach_notes.get("1.0", "end-1c").strip() != text.strip():
                self.txt_coach_notes.delete("1.0", "end"); self.txt_coach_notes.insert("end", text)
            self.after(2000, self.update_coach_popout)

    def open_ai_input_popout(self):
        if self.ai_input_window and self.ai_input_window.window.winfo_exists(): return self.ai_input_window.window.focus()
        self.ai_input_window = AIInputWindow(self, self.bot)

    def check_logs(self):
        while not log_queue.empty():
            type, msg = log_queue.get()
            self.txt_chat.insert("end", f"[{type}] {msg}\n")
            self.txt_chat.see("end")
        self.after(100, self.check_logs)

    def update_video(self):
        if self.bot and getattr(self.bot, 'eyes', None) and self.bot.eyes.get_frame() is not None:
            pil_img = Image.fromarray(cv2.cvtColor(cv2.resize(self.bot.eyes.get_frame(), (480, 270)), cv2.COLOR_BGR2RGB))
            if self.current_ctk_image is None:
                self.current_ctk_image = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(480, 270))
                self.lbl_video.configure(image=self.current_ctk_image, text="")
            else: self.current_ctk_image.configure(light_image=pil_img, dark_image=pil_img)

        if self.bot and getattr(self.bot, 'ears', None):
            self.lbl_audio_indicator.configure(text_color="#00FF00" if self.bot.ears.current_volume > 50 else "#FF0000")
        self.after(33, self.update_video)

if __name__ == "__main__":
    app = CommanderGUI()
    app.mainloop()
