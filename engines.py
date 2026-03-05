import sqlite3
import json
import time
import queue
import threading
import cv2
import pytesseract
from PIL import Image             
from google import genai          
from google.genai import types
import asyncio
import os
import pyaudio
import numpy as np
import collections
from vosk import Model, KaldiRecognizer
from supabase import create_client, Client
import config

# ==============================================================================
# 1. THE SCOUT (Hybrid Edge-to-Cloud Engine)
# ==============================================================================
class ScoutBrain:
    def __init__(self, db_name="scout.db"):
        # --- THE EDGE: Local SQLite for active stream tracking & VAR ---
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("CREATE TABLE IF NOT EXISTS active_bets (username TEXT PRIMARY KEY, prediction TEXT, amount INTEGER, multiplier REAL)")
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS bet_history 
                               (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                                market_question TEXT, 
                                winning_option TEXT, 
                                total_payout INTEGER,
                                resolution_frame TEXT,
                                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        self.conn.commit()
        
        # --- THE CLOUD: Supabase for Global Bankrolls & Hive Mind ---
        self.supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        
        # RAM Cache to prevent stream lag
        self.scout_cache = {}        
        
        self.current_market = {}     
        self.current_question = ""   
        self.market_locked = False   

    # --- GLOBAL ECONOMY METHODS (SUPABASE) ---
    def get_bankroll(self, username):
        res = self.supabase.table('viewers').select('bankroll').eq('username', username).execute()
        if res.data:
            return res.data[0]['bankroll']
        else:
            self.supabase.table('viewers').insert({'username': username, 'bankroll': 1000}).execute()
            return 1000

    def add_funds(self, username, amount):
        current_balance = self.get_bankroll(username)
        new_balance = current_balance + amount
        self.supabase.table('viewers').update({'bankroll': new_balance}).eq('username', username).execute()
        
    def get_leaderboard(self, limit=5):
        res = self.supabase.table('viewers').select('username, bankroll').order('bankroll', desc=True).limit(limit).execute()
        return [(row['username'], row['bankroll']) for row in res.data]

    # --- SPORTSBOOK METHODS (LOCAL RAM/SQLITE) ---
    def open_market(self, options_dict, question_text="Unknown Market"):
        self.current_market = options_dict
        self.current_question = question_text
        self.market_locked = False
        self.cursor.execute("DELETE FROM active_bets") 
        self.conn.commit()

    def lock_market(self):
        self.market_locked = True

    def place_bet(self, username, prediction, amount):
        balance = self.get_bankroll(username) # Checks the cloud
        if self.market_locked: return False, balance, "locked" 
        if prediction not in self.current_market: return False, balance, "invalid"
        if balance < amount: return False, balance, "funds"
        
        multiplier = self.current_market[prediction]
        new_balance = balance - amount
        
        # Update Cloud Bankroll
        self.supabase.table('viewers').update({'bankroll': new_balance}).eq('username', username).execute()
        
        # Log active bet locally
        self.cursor.execute("INSERT OR REPLACE INTO active_bets (username, prediction, amount, multiplier) VALUES (?, ?, ?, ?)", (username, prediction, amount, multiplier))
        self.conn.commit()
        return True, new_balance, multiplier

    def resolve_bets(self, winning_prediction, frame_path=None):
        # 1. Self-Cleaning VAR Data (Local)
        self.cursor.execute("SELECT resolution_frame FROM bet_history WHERE timestamp <= date('now', '-30 day') AND resolution_frame IS NOT NULL")
        old_frames = self.cursor.fetchall()
        for (path,) in old_frames:
            if os.path.exists(path):
                try: os.remove(path)
                except Exception: pass
        self.cursor.execute("DELETE FROM bet_history WHERE timestamp <= date('now', '-30 day')")
        
        if winning_prediction not in self.current_market: return 0, 0 
        
        self.cursor.execute("SELECT username, amount, multiplier FROM active_bets WHERE prediction = ?", (winning_prediction,))
        winners = self.cursor.fetchall()
        
        total_paid = 0
        for user, amount, multiplier in winners:
            payout = int(amount * multiplier)
            self.add_funds(user, payout) # Pays out via Cloud
            total_paid += payout
            
        # Log to Local Ledger
        self.cursor.execute("INSERT INTO bet_history (market_question, winning_option, total_payout, resolution_frame) VALUES (?, ?, ?, ?)", 
                            (self.current_question, winning_prediction, total_paid, frame_path))
                            
        self.cursor.execute("DELETE FROM active_bets")
        self.current_market = {} 
        self.current_question = ""
        self.conn.commit()
        return len(winners), total_paid

    # --- HIVE MIND SCOUTING (SUPABASE + RAM CACHE) ---
    def get_scout_notes(self, opponent_tag):
        if not opponent_tag: return []
        # If we haven't scouted this guy yet this stream, pull from the Cloud
        if opponent_tag not in self.scout_cache:
            res = self.supabase.table('scouting_reports').select('note').eq('opponent_tag', opponent_tag).order('created_at', desc=True).limit(5).execute()
            self.scout_cache[opponent_tag] = [row['note'] for row in res.data]
            
        return self.scout_cache[opponent_tag]

    def add_scout_note(self, opponent_tag, note):
        if not opponent_tag: return
        # Push to Cloud
        self.supabase.table('scouting_reports').insert({'opponent_tag': opponent_tag, 'game_title': 'Madden', 'note': note, 'author': 'AI_Booth'}).execute()
        
        # Update Local RAM Cache
        if opponent_tag not in self.scout_cache:
            self.scout_cache[opponent_tag] = []
        self.scout_cache[opponent_tag].insert(0, note)
        self.scout_cache[opponent_tag] = self.scout_cache[opponent_tag][:5]

# ==============================================================================
# 2. THE EARS (Local Audio Transcription via Vosk)
# ==============================================================================
class AudioEngine:
    def __init__(self, model_path="model"):
        self.transcript = []
        self.running = True
        self.current_volume = 0 
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
                self.current_volume = int(np.abs(audio_data).mean())
                
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "")
                    if text:
                        self.transcript.append(text)
                        if len(self.transcript) > 5:
                            self.transcript.pop(0)
            except Exception:
                pass

    def get_transcript(self):
        return " ".join(self.transcript)

    def __del__(self):
        self.running = False
        if hasattr(self, 'stream'): self.stream.stop_stream(); self.stream.close()
        if hasattr(self, 'p'): self.p.terminate()

# ==============================================================================
# 3. THE VISION (Camera & Local OCR Engine with Dashcam Buffer)
# ==============================================================================
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
        if len(self.frame_buffer) < frames_back:
            return self.current_frame 
        return self.frame_buffer[len(self.frame_buffer) - frames_back]
        
    def read_screen_text(self):
        frame = self.get_frame()
        if frame is None: return None
        frame = cv2.resize(frame, (1280, 720))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        zone_top = gray[10:90, 0:1280]       
        zone_bottom = gray[630:720, 0:1280]  
        zone_center = gray[280:440, 300:980] 
        custom_config = r'--oem 3 --psm 11'
        text_top = pytesseract.image_to_string(zone_top, config=custom_config).strip()
        text_bottom = pytesseract.image_to_string(zone_bottom, config=custom_config).strip()
        text_center = pytesseract.image_to_string(zone_center, config=custom_config).strip()
        return f"TOP BANNER: {text_top} | SCORE: {text_bottom} | POPUPS: {text_center}"
    
    def __del__(self):
        self.running = False
        if self.cap.isOpened(): self.cap.release()

# ==============================================================================
# 4. THE STRATEGIST (Gemini AI Engine)
# ==============================================================================
class AIEngine:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model = 'gemini-2.5-flash' 

    def _clean_json(self, text):
        text = text.strip()
        # Reformatted to prevent horizontal copy-paste cutoff issues
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
            
        if text.endswith("```"):
            text = text[:-3]
            
        return text.strip()

    def generate_prop_bet(self, image_path, game_type, streamer_name, gamer_tag, audio_context=""):
        prompt = f"""
        Look at this gameplay of {game_type}. You are coaching '{streamer_name}'. Gamertag: '{gamer_tag}'.
        Recent Game Audio: "{audio_context}"
        Act as a Vegas oddsmaker. Generate a live prop bet with 2 to 4 options (a, b, c, d) with decimal odds.
        Output strict JSON: {{"question": "What happens?", "options": {{"a": {{"text": "TD", "odds": 2.5}}}} }}
        """
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7))
            return json.loads(self._clean_json(response.text))
        except Exception: return None

    def generate_game_props(self, image_path, game_type, streamer_name, gamer_tag):
        prompt = f"""
        Look at this opening screen of {game_type}. You are coaching '{streamer_name}'. Gamertag: '{gamer_tag}'.
        Act as a Vegas oddsmaker. Generate a "Pre-Game Parlay" prop bet with 3 specific Over/Under options.
        Output strict JSON: {{"question": "Pre-Game Prop: Which hits?", "options": {{"a": {{"text": "Over 2.5 Pass TDs", "odds": 1.9}}}} }}
        """
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7))
            return json.loads(self._clean_json(response.text))
        except Exception: return None

    def generate_auto_prop(self, image_path, game_type, streamer_name, gamer_tag, audio_context=""):
        prompt = f"""
        Look at this gameplay of {game_type}. You are coaching '{streamer_name}'. Gamertag: '{gamer_tag}'.
        Recent Game Audio: "{audio_context}"
        Act as a Vegas oddsmaker. Generate a specific prop bet with 2 to 4 options. Determine exactly how many seconds this bet should stay open to build suspense.
        Output strict JSON: {{"question": "What happens?", "lock_seconds": 90, "options": {{"a": {{"text": "TD", "odds": 2.5}}}} }}
        """
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.8))
            return json.loads(self._clean_json(response.text))
        except Exception: return None

    def check_bet_resolution(self, image_path, game_type, active_bet, ocr_text=""):
        prompt = f"""
        You are a Vegas referee watching {game_type}.
        The current active prop bet is: "{active_bet['question']}"
        The betting options are: {active_bet['options']}
        CRITICAL UI DATA: {ocr_text}
        
        Look at the image and the UI data. Has the explicit outcome of this bet happened yet?
        If you are 100% certain an option has won, set "status" to "resolved" and "winning_key" to the winning option's letter (e.g., "a", "b").
        If the bet is still ongoing, or you aren't absolutely sure yet, set "status" to "pending" and "winning_key" to null.
        Output strict JSON: {{"status": "pending", "winning_key": null, "reason": "brief explanation"}}
        """
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(
                model=self.model, 
                contents=[prompt, img], 
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
            )
            return json.loads(self._clean_json(response.text))
        except Exception as e: 
            return None

    def analyze(self, image_path, game_type, streamer_name, gamer_tag, user_question=None, scout_notes=None, ocr_text=None, recent_chat=None, audio_context=""):
        persona_rules = f"""
        CRITICAL INSTRUCTION: You are a hype Color Commentator for '{streamer_name}'. 
        Speak directly to the Twitch Chat viewers. Describe the on-screen action, hype up the stream, and WELCOME/SHOUT OUT the viewers seen in the chat log.
        """
        player_context = f"The visual Gamertag on screen is '{gamer_tag}'."
        game_rules = f"They are playing {game_type}."
        
        ocr_context = f"CRITICAL UI DATA (Trust this text): {ocr_text}\n" if ocr_text else ""
        chat_context = f"RECENT TWITCH CHAT LOG:\n{recent_chat}\n" if recent_chat else "No recent chat.\n"
        audio_prompt = f"RECENT GAME AUDIO (Announcers/Action):\n{audio_context}\n" if audio_context else ""
        
        if game_type == "Madden":
            game_rules += f"""
            CRITICAL MADDEN INSTRUCTIONS:
            - OPPONENT PROFILING: Scan the top banners. Find the tag that is NOT '{gamer_tag}'. IF YOU ARE IN A MENU, output exactly "None".
            - HIGHLIGHT DETECTION: If the Audio or OCR indicates a massive, game-changing play just happened (Touchdown, Interception, Fumble, Game Winner), set "highlight_play" to true. Otherwise, false.
            - Output JSON: {{"commentary": "chat (MAX 400 CHARS)", "opponent_tag": "tag", "scouting_note": "note", "highlight_play": false}}
            """
            
        memory_context = "PAST OBSERVATIONS OF OPPONENT:\n" + "\n".join([str(note) for note in scout_notes if note]) if scout_notes else ""

        prompt = f"{persona_rules}\n{player_context}\n{game_rules}\n{ocr_context}{audio_prompt}{chat_context}{memory_context}\n"
        if user_question: prompt += f"Viewer Asked: '{user_question}'. Answer them. Output strict JSON."
        else: prompt += "Analyze screen. Output strict JSON."
        
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.8))
            return json.loads(self._clean_json(response.text))
        except Exception: return None
