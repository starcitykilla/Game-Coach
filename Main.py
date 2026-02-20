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

log_queue = queue.Queue()

def log_to_gui(type, message):
    log_queue.put((type, message))

class PersonaBuilderPopup(ctk.CTkToplevel):
    def __init__(self, parent_gui):
        super().__init__(parent_gui)
        self.title("AI Lab - Build Custom Coach")
        self.geometry("500x420")
        self.parent = parent_gui
        self.attributes('-topmost', True) 
        
        ctk.CTkLabel(self, text="Who do you want to coach you?", font=("Impact", 18)).pack(pady=10)
        self.entry_name = ctk.CTkEntry(self, width=400, placeholder_text="e.g., Deadpool, A 1920s Mobster, A Pirate")
        self.entry_name.pack(pady=5)
        self.btn_research = ctk.CTkButton(self, text="🔍 Research & Generate Profile", command=self.generate)
        self.btn_research.pack(pady=10)
        self.txt_result = ctk.CTkTextbox(self, width=450, height=150, wrap="word")
        self.txt_result.pack(pady=10)
        self.btn_save = ctk.CTkButton(self, text="💾 Approve & Save to Database", command=self.save_persona, state="disabled", fg_color="green")
        self.btn_save.pack(pady=5)
        
        self.generated_profile = ""

    def generate(self):
        name = self.entry_name.get()
        if not name: return
        self.txt_result.delete("0.0", "end")
        self.txt_result.insert("end", f"Firing up Web Crawler to research '{name}'...\nPlease wait 3-5 seconds.")
        self.update() 
        threading.Thread(target=self._run_generation, args=(name,), daemon=True).start()

    def _run_generation(self, name):
        result = self.parent.bot.strategist.build_custom_persona(name)
        self.txt_result.delete("0.0", "end")
        if result:
            self.generated_profile = result
            self.txt_result.insert("end", result)
            self.btn_save.configure(state="normal") 
        else:
            self.txt_result.insert("end", "❌ Error: Could not connect to Google Search.")

    def save_persona(self):
        name = self.entry_name.get()
        self.parent.bot.brain.save_persona(name, self.generated_profile)
        self.parent.refresh_persona_list()
        self.parent.combo_persona.set(name)
        self.parent.update_settings()
        self.destroy() 

class CommanderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("BlindMan Gaming Command Center 🤖")
        self.geometry("1280x800")
        ctk.set_appearance_mode("Dark")
        
        self.bot = None
        self._init_layout()
        self.start_bot_thread()
        self.update_video()
        self.check_logs()
        self.check_bot_ready()

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

        ctk.CTkLabel(self.frame_right, text="Your Gamertag:", font=("Arial", 12, "bold")).pack(pady=(10,0))
        self.entry_tag = ctk.CTkEntry(self.frame_right, placeholder_text="Enter Gamertag...")
        self.entry_tag.insert(0, "Krzy Budz") 
        self.entry_tag.pack(pady=5)
        self.entry_tag.bind("<KeyRelease>", self.update_settings)

        ctk.CTkLabel(self.frame_right, text="🎤 Select Microphone", font=("Arial", 12, "bold")).pack(pady=(10,0))
        self.combo_mic = ctk.CTkComboBox(self.frame_right, values=["Detecting..."], command=self.change_mic)
        self.combo_mic.pack(pady=5)

        self.btn_listen = ctk.CTkButton(self.frame_right, text="🎤 ASK COACH (Push to Talk)", fg_color="red", height=40, command=self.ask_coach)
        self.btn_listen.pack(pady=15, padx=10, fill="x")

        ctk.CTkLabel(self.frame_right, text="Game Type:", font=("Arial", 12, "bold")).pack(pady=(10,0))
        self.combo_game = ctk.CTkComboBox(self.frame_right, values=config.GAMES_ROSTER, command=self.update_settings)
        self.combo_game.pack(pady=5)
        
        ctk.CTkLabel(self.frame_right, text="Coach Personality:", font=("Arial", 12, "bold")).pack(pady=(10,0))
        self.combo_persona = ctk.CTkComboBox(self.frame_right, values=["Loading..."], command=self.update_settings)
        self.combo_persona.pack(pady=5)
        
        self.btn_custom = ctk.CTkButton(self.frame_right, text="➕ Create Custom Coach", command=self.open_persona_builder, fg_color="#5e17eb")
        self.btn_custom.pack(pady=(5, 15))

        self.txt_chat = ctk.CTkTextbox(self.frame_right, height=250)
        self.txt_chat.pack(fill="both", expand=True, padx=5, pady=10)

    def start_bot_thread(self):
        threading.Thread(target=self.run_bot_logic, daemon=True).start()

    def run_bot_logic(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.bot = CommanderBot(log_callback=log_to_gui)
        
        mics = self.bot.ears.list_microphones()
        self.combo_mic.configure(values=mics)
        if mics: self.change_mic(mics[0])

        try:
            loop.run_until_complete(self.bot.start())
        except KeyboardInterrupt:
            loop.run_until_complete(self.bot.close())
        finally:
            loop.close()

    def ask_coach(self): 
        threading.Thread(target=self.bot.process_voice_command, daemon=True).start()

    def change_mic(self, choice):
        if self.bot:
            mics = self.bot.ears.list_microphones()
            if choice in mics:
                idx = mics.index(choice)
                self.bot.ears.set_microphone(idx)
                log_to_gui("SYSTEM", f"🎤 Mic set to: {choice}")

    def update_settings(self, _=None):
        if self.bot:
            self.bot.current_game = self.combo_game.get()
            self.bot.gamer_tag = self.entry_tag.get()
            selected_name = self.combo_persona.get()
            customs = self.bot.brain.get_custom_personas()
            
            if selected_name in customs: 
                self.bot.current_persona = customs[selected_name]
            else: 
                self.bot.current_persona = selected_name
                
            if hasattr(self.bot, 'update_overlay'):
                self.bot.update_overlay()

    def open_persona_builder(self): 
        PersonaBuilderPopup(self)

    def refresh_persona_list(self):
        base_personas = list(config.CHARACTER_ROSTER.keys())
        if self.bot and self.bot.brain:
            customs = list(self.bot.brain.get_custom_personas().keys())
            self.combo_persona.configure(values=base_personas + customs)

    def check_bot_ready(self):
        if self.bot and hasattr(self.bot, 'brain'): 
            self.refresh_persona_list()
        else: 
            self.after(500, self.check_bot_ready)

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
        self.after(33, self.update_video)

if __name__ == "__main__":
    app = CommanderGUI()
    app.mainloop()
