# main.py
import customtkinter as ctk
import threading
import queue
import cv2
import time
import asyncio
from PIL import Image
from bot import CommanderBot
import config

# Global queue to pass log messages from the bot thread to the GUI thread safely
log_queue = queue.Queue()

def log_to_gui(type, message):
    """Callback function given to the bot to push text into the GUI console."""
    log_queue.put((type, message))

class CommanderGUI(ctk.CTk):
    def __init__(self):
        """Constructs the master window and sets up the layout."""
        super().__init__()
        
        self.title("BMG's Virtual Vegas Software 🎰")
        self.geometry("1280x800")
        ctk.set_appearance_mode("Dark")
        
        self.bot = None
        
        # Build the Visuals
        self._init_layout()
        
        # Start the bot on a separate thread so the GUI doesn't freeze
        self.start_bot_thread()
        
        # Start GUI background loops
        self.update_video()
        self.check_logs()

    def _init_layout(self):
        """Creates the grid layout: Video on the left, Controls on the right."""
        self.grid_columnconfigure(0, weight=3) # Video takes 75% of screen
        self.grid_columnconfigure(1, weight=1) # Controls take 25%
        self.grid_rowconfigure(0, weight=1)

        # --- LEFT SIDE: THE VIDEO FEED ---
        self.frame_video = ctk.CTkFrame(self)
        self.frame_video.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.lbl_video = ctk.CTkLabel(self.frame_video, text="Starting Camera...", font=("Consolas", 20))
        self.lbl_video.pack(fill="both", expand=True)

        # --- RIGHT SIDE: THE CONTROL DECK ---
        self.frame_right = ctk.CTkFrame(self, width=300)
        self.frame_right.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        ctk.CTkLabel(self.frame_right, text="COMMAND CENTER", font=("Impact", 24)).pack(pady=10)

        # THE BIG RED BUTTON: Forces a live prop bet instantly
        self.btn_listen = ctk.CTkButton(self.frame_right, text="🎲 RUN ODDSMAKER", fg_color="red", height=40, command=self.run_oddsmaker)
        self.btn_listen.pack(pady=25, padx=10, fill="x")

        # GAME SELECTOR
        ctk.CTkLabel(self.frame_right, text="Game Type:", font=("Arial", 12, "bold")).pack(pady=(10,0))
        self.combo_game = ctk.CTkComboBox(self.frame_right, values=config.GAMES_ROSTER, command=self.update_settings)
        self.combo_game.pack(pady=5)
        
        # THE CONSOLE TEXT BOX
        self.txt_chat = ctk.CTkTextbox(self.frame_right, height=250)
        self.txt_chat.pack(fill="both", expand=True, padx=5, pady=10)

    def start_bot_thread(self):
        """Fires up the bot logic without halting the user interface."""
        threading.Thread(target=self.run_bot_logic, daemon=True).start()

    def run_bot_logic(self):
        """Establishes the asyncio loop required by TwitchIO."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.bot = CommanderBot(log_callback=log_to_gui)
        try: loop.run_until_complete(self.bot.start())
        except KeyboardInterrupt: loop.run_until_complete(self.bot.close())
        finally: loop.close()

    def run_oddsmaker(self): 
        """Tells the bot to execute the Oddsmaker function when the red button is clicked."""
        if self.bot: self.bot.trigger_manual_oddsmaker()

    def update_settings(self, _=None):
        """Updates bot variables live if dropdowns are changed in the GUI."""
        if self.bot:
            self.bot.current_game = self.combo_game.get()
            if hasattr(self.bot, 'update_overlay'): self.bot.update_overlay()

    def check_logs(self):
        """Pulls messages from the queue and prints them to the console box."""
        while not log_queue.empty():
            type, msg = log_queue.get()
            self.txt_chat.insert("end", f"[{type}] {msg}\n")
            self.txt_chat.see("end") # Auto-scroll to bottom
        self.after(100, self.check_logs) # Check again in 100ms

    def update_video(self):
        """Pulls the latest frame from VisionEngine and paints it on the screen."""
        if self.bot and hasattr(self.bot, 'eyes') and self.bot.eyes:
            frame = self.bot.eyes.get_frame()
            if frame is not None:
                frame = cv2.resize(frame, (480, 270))
                img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(480, 270))
                self.lbl_video.configure(image=ctk_img, text="")
        self.after(33, self.update_video) # Refresh at ~30 FPS

if __name__ == "__main__":
    app = CommanderGUI()
    app.mainloop()

