import customtkinter as ctk

class AIInputWindow:
    def __init__(self, parent, bot):
        self.window = ctk.CTkToplevel(parent)
        self.window.title("AI Diagnostic Feed 📡")
        self.window.geometry("550x650")
        self.window.attributes('-topmost', True) 
        self.bot = bot

        ctk.CTkLabel(self.window, text="🎙️ LIVE AUDIO TRANSCRIPT", font=("Impact", 18), text_color="#00FF00").pack(pady=(15, 5))
        self.txt_audio = ctk.CTkTextbox(self.window, height=150, wrap="word", font=("Consolas", 14), fg_color="black", text_color="#00FF00", border_color="#00FF00", border_width=2)
        self.txt_audio.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(self.window, text="👁️ LATEST OCR READ", font=("Impact", 18), text_color="#00FFFF").pack(pady=(15, 5))
        self.txt_ocr = ctk.CTkTextbox(self.window, height=300, wrap="word", font=("Consolas", 14), fg_color="black", text_color="#00FFFF", border_color="#00FFFF", border_width=2)
        self.txt_ocr.pack(fill="both", expand=True, padx=15, pady=5)

        self.update_feed()

    def update_feed(self):
        if self.window.winfo_exists() and self.bot:
            audio_text = self.bot.ears.get_transcript() if getattr(self.bot, 'ears', None) else "Audio Engine Offline..."
            ocr_text = getattr(self.bot, 'last_ocr_text', "Waiting for the first visual scan...")

            if self.txt_audio.get("1.0", "end-1c").strip() != audio_text.strip():
                self.txt_audio.delete("1.0", "end")
                self.txt_audio.insert("end", audio_text)
                self.txt_audio.see("end")

            if self.txt_ocr.get("1.0", "end-1c").strip() != ocr_text.strip():
                self.txt_ocr.delete("1.0", "end")
                self.txt_ocr.insert("end", ocr_text)

            self.window.after(1000, self.update_feed)
