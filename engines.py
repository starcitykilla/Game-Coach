# engines.py
import sqlite3
import json
import time
import queue
import threading
import cv2
import speech_recognition as sr
from PIL import Image             
from google import genai          
from google.genai import types
import edge_tts
import asyncio
import pygame
import os

# ==========================================
# 1. THE SCOUT (Memory & Sportsbook Engine)
# ==========================================
class ScoutBrain:
    def __init__(self, db_name="scout.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        self.cursor.execute("CREATE TABLE IF NOT EXISTS viewers (username TEXT PRIMARY KEY, chat_count INTEGER DEFAULT 0, bankroll INTEGER DEFAULT 1000)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS custom_personas (name TEXT PRIMARY KEY, description TEXT)") 
        self.cursor.execute("CREATE TABLE IF NOT EXISTS active_bets (username TEXT PRIMARY KEY, prediction TEXT, amount INTEGER, multiplier REAL)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS reward_claims (username TEXT, reward_name TEXT, PRIMARY KEY(username, reward_name))")
        
        self.cursor.execute("CREATE TABLE IF NOT EXISTS film_room (id INTEGER PRIMARY KEY AUTOINCREMENT, opponent_tag TEXT, note TEXT)")
        self.conn.commit()
        
        self.current_market = {} 

    def get_bankroll(self, username):
        self.cursor.execute("INSERT OR IGNORE INTO viewers (username) VALUES (?)", (username,))
        self.cursor.execute("SELECT bankroll FROM viewers WHERE username = ?", (username,))
        self.conn.commit()
        return self.cursor.fetchone()[0]

    def open_market(self, options_dict):
        self.current_market = options_dict
        self.cursor.execute("DELETE FROM active_bets") 
        self.conn.commit()

    def place_bet(self, username, prediction, amount):
        balance = self.get_bankroll(username)
        if prediction not in self.current_market: return False, balance, "invalid"
        if balance < amount: return False, balance, "funds"
            
        multiplier = self.current_market[prediction]
        new_balance = balance - amount
        
        self.cursor.execute("UPDATE viewers SET bankroll = ? WHERE username = ?", (new_balance, username))
        self.cursor.execute("INSERT OR REPLACE INTO active_bets (username, prediction, amount, multiplier) VALUES (?, ?, ?, ?)", (username, prediction, amount, multiplier))
        self.conn.commit()
        return True, new_balance, multiplier

    def resolve_bets(self, winning_prediction):
        if winning_prediction not in self.current_market: return 0, 0 
            
        self.cursor.execute("SELECT username, amount, multiplier FROM active_bets WHERE prediction = ?", (winning_prediction,))
        winners = self.cursor.fetchall()
        
        total_paid = 0
        for user, amount, multiplier in winners:
            payout = int(amount * multiplier)
            self.cursor.execute("UPDATE viewers SET bankroll = bankroll + ? WHERE username = ?", (payout, user))
            total_paid += payout
            
        self.cursor.execute("DELETE FROM active_bets")
        self.current_market = {} 
        self.conn.commit()
        return len(winners), total_paid

    def purchase_reward(self, username, cost, reward_name, is_one_time=False):
        balance = self.get_bankroll(username)
        if balance < cost: return "funds"

        if is_one_time:
            self.cursor.execute("SELECT 1 FROM reward_claims WHERE username = ? AND reward_name = ?", (username, reward_name))
            if self.cursor.fetchone(): return "claimed"

        new_balance = balance - cost
        self.cursor.execute("UPDATE viewers SET bankroll = ? WHERE username = ?", (new_balance, username))
        
        if is_one_time:
            self.cursor.execute("INSERT INTO reward_claims (username, reward_name) VALUES (?, ?)", (username, reward_name))
            
        self.conn.commit()
        return "success"

    def save_persona(self, name, description):
        self.cursor.execute("INSERT OR REPLACE INTO custom_personas (name, description) VALUES (?, ?)", (name, description))
        self.conn.commit()

    def get_custom_personas(self):
        self.cursor.execute("SELECT name, description FROM custom_personas")
        return {row[0]: row[1] for row in self.cursor.fetchall()}

    def add_scout_note(self, opponent_tag, note):
        if not opponent_tag: return
        self.cursor.execute("INSERT INTO film_room (opponent_tag, note) VALUES (?, ?)", (opponent_tag, note))
        self.cursor.execute("DELETE FROM film_room WHERE id NOT IN (SELECT id FROM film_room WHERE opponent_tag = ? ORDER BY id DESC LIMIT 5)", (opponent_tag,))
        self.conn.commit()

    def get_scout_notes(self, opponent_tag):
        if not opponent_tag: return []
        self.cursor.execute("SELECT note FROM film_room WHERE opponent_tag = ? ORDER BY id DESC", (opponent_tag,))
        return [row[0] for row in self.cursor.fetchall()]

# ==========================================
# 2. THE VOICE (Edge-TTS)
# ==========================================
class VoiceEngine:
    def __init__(self):
        self.queue = queue.Queue()
        self.current_voice = "en-US-ChristopherNeural"
        pygame.mixer.init()
        threading.Thread(target=self._worker, daemon=True).start()

    def set_voice(self, voice_id):
        self.current_voice = voice_id

    def say(self, text):
        self.queue.put(text)

    def _worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while True:
            text = self.queue.get()
            if text is None: break
            try:
                communicate = edge_tts.Communicate(text, self.current_voice)
                audio_file = "temp_speech.mp3"
                loop.run_until_complete(communicate.save(audio_file))
                
                pygame.mixer.music.load(audio_file)
                pygame.mixer.music.play()
                
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            except Exception as e:
                print(f"❌ Edge-TTS Error: {e}")
            self.queue.task_done()

# ==========================================
# 3. THE EARS (Speech Recognition)
# ==========================================
class EarEngine:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.mic = None

    def list_microphones(self):
        return sr.Microphone.list_microphone_names()

    def set_microphone(self, index):
        self.mic = sr.Microphone(device_index=index)
        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)

    def listen_once(self):
        if not self.mic: return None
        try:
            with self.mic as source:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                return self.recognizer.recognize_google(audio)
        except: return None 

# ==========================================
# 4. THE VISION (OpenCV)
# ==========================================
class VisionEngine:
    def __init__(self, camera_index=0):
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.current_frame = None
        self.running = True
        threading.Thread(target=self._update_loop, daemon=True).start()

    def _update_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret: self.current_frame = frame
            time.sleep(0.01)

    def get_frame(self): return self.current_frame
    
    def __del__(self):
        self.running = False
        if self.cap.isOpened(): self.cap.release()

# ==========================================
# 5. THE STRATEGIST (Gemini 2.5 Flash)
# ==========================================
class AIEngine:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model = 'gemini-2.5-flash' 

    def _clean_json(self, text):
        text = text.strip()
        if text.startswith("```json"): text = text[7:]
        elif text.startswith("```"): text = text[3:]
        if text.endswith("```"): text = text[:-3]
        return text.strip()

    def build_custom_persona(self, user_request):
        prompt = f"""
        Research the following character, person, or archetype using Google Search: "{user_request}"
        Write a 3-sentence persona description that completely embodies them. 
        Include their exact tone, slang, catchphrases, and attitude.
        Do not include markdown, just the raw text of the persona.
        """
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.8, tools=[{"google_search": {}}])
            )
            return response.text.strip()
        except Exception as e:
            print(f"❌ Gemini Error: {e}")
            return None

    def generate_prop_bet(self, image_path, game_type, gamer_tag):
        prompt = f"""
        Look at this gameplay of {game_type}. The main player is '{gamer_tag}'.
        Act as a Vegas oddsmaker. Generate a live prop bet for Twitch chat with 2 to 4 options (labeled a, b, c, d).
        Assign realistic decimal odds to each option based on how likely it is to happen on screen right now.
        
        Output strict JSON in this exact format:
        {{
            "question": "What happens on this drive?",
            "options": {{
                "a": {{"text": "Touchdown", "odds": 2.5}},
                "b": {{"text": "Field Goal", "odds": 1.8}},
                "c": {{"text": "Turnover", "odds": 5.0}}
            }}
        }}
        """
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, img],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7)
            )
            clean_text = self._clean_json(response.text)
            return json.loads(clean_text)
        except Exception as e:
            print(f"❌ Gemini Error: {e}")
            return None

    def analyze(self, image_path, game_type, personality_prompt, gamer_tag, user_question=None, scout_notes=None):
        persona_rules = f"""
        CRITICAL INSTRUCTION: You MUST completely impersonate this character/persona: {personality_prompt}.
        Speak exactly like them. Use their catchphrases, tone, slang, and attitude. Do NOT break character.
        """
        
        player_context = f"The player you are coaching has the Gamertag: '{gamer_tag}'. You must root for them." if gamer_tag else "You are coaching the player."
        game_rules = f"They are currently playing {game_type}."
        
        if game_type == "Madden":
            game_rules += f"""
            CRITICAL MADDEN INSTRUCTIONS:
            - Scan the defensive shell pre-snap. Are there 1 or 2 high safeties? Identify Cover 2, Cover 3, Cover 4, or Man.
            - PLAYER IDENTIFICATION: Look for a ring under a player's feet. GREEN ring = the player you are coaching. RED ring = the human opponent. GRAY ring = CPU.
            - SITUATIONAL FOOTBALL: Read the scoreboard. Find the Down, Distance, Score, and Time remaining. Tailor advice strictly to this context.
            - X-FACTORS: Scan for glowing 'X' or Star icons. Warn the player to double-team or avoid them.
            - PLAY CLOCK: If under 5 seconds, urgently tell them to snap the ball.
            - STAMINA: If the user's green stamina ring is draining rapidly on a return, warn them to cover the ball.
            - OPPONENT PROFILING: Scan the scoreboard for the opponent's Gamertag (the text that is NOT '{gamer_tag}'). Output it exactly in a JSON field called "opponent_tag".
            - Output an extra JSON field called "scouting_note" containing a 1-sentence observation of the opponent's current tendency or personnel.
            """
            
        memory_context = ""
        if scout_notes and len(scout_notes) > 0:
            memory_context = "PAST OBSERVATIONS OF THIS OPPONENT:\n" + "\n".join(scout_notes) + "\nUse these past tendencies to predict what they might do next."

        if user_question:
            prompt = f"""
            {persona_rules}
            {player_context}
            {game_rules}
            {memory_context}
            They asked: "{user_question}"
            Answer them directly. Output JSON: {{"advice": "Spoken answer", "commentary": "Twitch chat comment", "opponent_tag": "Gamertag here", "scouting_note": "1-sentence observation"}}
            """
        else:
            prompt = f"""
            {persona_rules}
            {player_context}
            {game_rules}
            {memory_context}
            Analyze the screen. Output JSON: {{"advice": "Spoken tip", "commentary": "Twitch comment", "opponent_tag": "Gamertag here", "scouting_note": "1-sentence observation"}}
            """
        
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, img],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.8)
            )
            clean_text = self._clean_json(response.text)
            return json.loads(clean_text)
        except Exception as e:
            print(f"❌ Gemini Error: {e}")
            return None
