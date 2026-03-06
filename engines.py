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

       self.supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
       self.scout_cache = {}        
       self.current_market = {}     
       self.current_question = ""   
       self.market_locked = False   

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

   def open_market(self, options_dict, question_text="Unknown Market"):
       self.current_market = options_dict
       self.current_question = question_text
       self.market_locked = False
       self.cursor.execute("DELETE FROM active_bets")
       self.conn.commit()

   def lock_market(self):
       self.market_locked = True

   def place_bet(self, username, prediction, amount):
       balance = self.get_bankroll(username)
       if self.market_locked: return False, balance, "locked"
       if prediction not in self.current_market: return False, balance, "invalid"
       if balance < amount: return False, balance, "funds"

       multiplier = self.current_market[prediction]
       new_balance = balance - amount

       self.supabase.table('viewers').update({'bankroll': new_balance}).eq('username', username).execute()
       self.cursor.execute("INSERT OR REPLACE INTO active_bets (username, prediction, amount, multiplier) VALUES (?, ?, ?, ?)", (username, prediction, amount, multiplier))
       self.conn.commit()
       return True, new_balance, multiplier

   def resolve_bets(self, winning_prediction, frame_path=None):
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
           self.add_funds(user, payout)
           total_paid += payout

       self.cursor.execute("INSERT INTO bet_history (market_question, winning_option, total_payout, resolution_frame) VALUES (?, ?, ?, ?)",
                           (self.current_question, winning_prediction, total_paid, frame_path))

       self.cursor.execute("DELETE FROM active_bets")
       self.current_market = {}
       self.current_question = ""
       self.conn.commit()
       return len(winners), total_paid

   def get_scout_notes(self, opponent_tag):
       if not opponent_tag: return []
       if opponent_tag not in self.scout_cache:
           res = self.supabase.table('scouting_reports').select('note').eq('opponent_tag', opponent_tag).order('created_at', desc=True).limit(5).execute()
           self.scout_cache[opponent_tag] = [row['note'] for row in res.data]
       return self.scout_cache[opponent_tag]

   def add_scout_note(self, opponent_tag, note):
       if not opponent_tag: return
       self.supabase.table('scouting_reports').insert({'opponent_tag': opponent_tag, 'game_title': 'Madden', 'note': note, 'author': 'AI_Booth'}).execute()

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

       zone_top_left = gray[0:120, 0:640]       
       zone_top_right = gray[0:120, 640:1280]  
       zone_bottom = gray[630:720, 0:1280]  
       zone_center = gray[280:440, 300:980]

       custom_config = r'--oem 3 --psm 11'
       text_top_left = pytesseract.image_to_string(zone_top_left, config=custom_config).strip()
       text_top_right = pytesseract.image_to_string(zone_top_right, config=custom_config).strip()
       text_bottom = pytesseract.image_to_string(zone_bottom, config=custom_config).strip()
       text_center = pytesseract.image_to_string(zone_center, config=custom_config).strip()

       return f"TOP LEFT TAGS: {text_top_left} | TOP RIGHT TAGS: {text_top_right} | SCOREBOARD: {text_bottom} | POPUPS: {text_center}"

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
       text = text.replace('```json', '')
       text = text.replace('```', '')
       return text.strip()

   def generate_prop_bet(self, image_path, game_type, streamer_name, gamer_tag, audio_context=""):
       prompt = f"""
       Look at this gameplay of {game_type}. You are coaching '{streamer_name}' (Gamertag: '{gamer_tag}').
       Act as a Vegas oddsmaker. DO NOT generate bets for a single play. Generate a live prop bet for the outcome of the ENTIRE CURRENT OR NEXT DRIVE.
       Examples: Touchdown, Field Goal, Punt, Turnover.
       Generate 2 to 4 options (a, b, c, d) with decimal odds.
       Output strict JSON: {{"question": "Result of this Drive?", "options": {{"a": {{"text": "Touchdown", "odds": 3.5}}, "b": {{"text": "Punt", "odds": 1.5}}}} }}
       """
       try:
           img = Image.open(image_path)
           response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7))
           return json.loads(self._clean_json(response.text))
       except Exception: return None

   def generate_game_props(self, image_path, game_type, streamer_name, gamer_tag):
       prompt = f"""
       Look at this opening screen of {game_type}. You are coaching '{streamer_name}' (Gamertag: '{gamer_tag}').
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
       Look at this gameplay of {game_type}. You are coaching '{streamer_name}' (Gamertag: '{gamer_tag}').
       Act as a Vegas oddsmaker. DO NOT generate bets for a single play. Generate a live prop bet for the outcome of the ENTIRE CURRENT OR NEXT DRIVE.
       Examples: Touchdown, Field Goal, Punt, Turnover.
       Determine exactly how many seconds this bet should stay open to build suspense. Since drives take a while, 60 to 90 seconds is perfect.
       Output strict JSON: {{"question": "Result of this Drive?", "lock_seconds": 60, "options": {{"a": {{"text": "Touchdown", "odds": 3.5}}, "b": {{"text": "Punt", "odds": 1.5}}}} }}
       """
       try:
           img = Image.open(image_path)
           response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.8))
           return json.loads(self._clean_json(response.text))
       except Exception: return None

   def check_bet_resolution(self, image_path, game_type, active_bet, ocr_text=""):
       prompt = f"""
       You are an expert Vegas referee watching {game_type}.
       The current active prop bet is: "{active_bet['question']}"
       The betting options are: {active_bet['options']}
       CRITICAL UI DATA: {ocr_text}

       *CRITICAL REFEREE RULE FOR DRIVES*: These bets are usually about the entire DRIVE. A drive ONLY ends when there is a Touchdown, a Field Goal attempt, a Punt, or a Turnover.
       If they are just getting a first down or running a normal mid-drive play, the bet is still "pending".
       If the visual action shows one of those drive-ending events (like a Touchdown celebration or the Punt team on the field), rule it as resolved immediately!

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

   # --- MASSIVE UPGRADE: Passed "current_opponent" so the AI remembers the baseline! ---
   def analyze(self, image_path, game_type, streamer_name, gamer_tag, current_opponent=None, user_question=None, scout_notes=None, ocr_text=None, recent_chat=None, audio_context=""):

       opponent_memory = f"STICKY MEMORY PROTOCOL: You are CURRENTLY playing against '{current_opponent}'. " if current_opponent and current_opponent != "CPU" else ""

       prompt = f"""
       CRITICAL INSTRUCTION: You are a hype Color Commentator for '{streamer_name}'.
       IDENTITY RULE: The visual Gamertag on screen for the streamer is '{gamer_tag}'.

       TASK 1: AUTO-DETECT THE GAME. Is this 'Madden', 'NBA 2K', 'College Football', 'Menu/Lobby', or something else? Return this in the "game_type" key.

       TASK 2: IDENTIFY THE OPPONENT & TEAM IDENTITY (BANNER MATCH PROTOCOL).
       {opponent_memory}
       - Gamertags DO NOT appear on every screen. If they are hidden right now, DO NOT guess and DO NOT default to CPU. Just output the currently remembered opponent.
       - Look at the TOP of the image for Gamertag Banners. ONLY change the "opponent_tag" if you CLEARLY see a NEW opponent's Gamertag, or if you are back in a main 'Menu/Lobby' (set opponent to 'None').
       - To find out which team '{streamer_name}' is playing as, find the top banner with '{gamer_tag}', look at the team logo next to it, and match that logo to the main scoreboard at the bottom.

       TASK 3: Generate hype commentary about the on-screen action for the Twitch Chat. ONLY set "highlight_play" to true if the STREAMER makes a huge play. Ignore opponent plays.

       CRITICAL UI DATA: {ocr_text}
       RECENT GAME AUDIO:\n{audio_context}
       RECENT TWITCH CHAT LOG:\n{recent_chat}
       PAST OBSERVATIONS OF OPPONENT:\n{scout_notes}
       """

       if user_question: prompt += f"\nViewer Asked: '{user_question}'. Answer them."

       prompt += """
       Output strict JSON EXACTLY like this:
       {"game_type": "Detected Game Here", "commentary": "chat text (MAX 400 CHARS)", "opponent_tag": "tag or CPU", "scouting_note": "tactical note here", "highlight_play": false}
       """

       try:
           img = Image.open(image_path)
           response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.8))
           return json.loads(self._clean_json(response.text))
       except Exception: return None
