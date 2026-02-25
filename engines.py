# engines.py
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
import edge_tts
import asyncio
import pygame
import os

# ==============================================================================
# 1. THE SCOUT (Database & Memory Engine)
# Handles all SQLite database interactions: Viewers, Bankrolls, and Opponent Notes.
# ==============================================================================
class ScoutBrain:
    def __init__(self, db_name="scout.db"):
        """Initializes the database and creates the tables if they don't exist yet."""
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        # Build the foundational tables for the economy and scouting
        self.cursor.execute("CREATE TABLE IF NOT EXISTS viewers (username TEXT PRIMARY KEY, chat_count INTEGER DEFAULT 0, bankroll INTEGER DEFAULT 1000)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS active_bets (username TEXT PRIMARY KEY, prediction TEXT, amount INTEGER, multiplier REAL)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS film_room (id INTEGER PRIMARY KEY AUTOINCREMENT, opponent_tag TEXT, note TEXT)")
        self.conn.commit()
        
        self.current_market = {}     # Holds the active betting options and odds
        self.market_locked = False   # Prevents betting after the timer expires

    def get_bankroll(self, username):
        """Fetches a user's balance. If they are new, it gives them the default $1000."""
        self.cursor.execute("INSERT OR IGNORE INTO viewers (username) VALUES (?)", (username,))
        self.cursor.execute("SELECT bankroll FROM viewers WHERE username = ?", (username,))
        self.conn.commit()
        return self.cursor.fetchone()[0]
        
    def get_leaderboard(self, limit=5):
        """Fetches the wealthiest viewers in the channel for the OBS Overlay."""
        self.cursor.execute("SELECT username, bankroll FROM viewers ORDER BY bankroll DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()

    def open_market(self, options_dict):
        """Starts a new betting round and clears out any old bets."""
        self.current_market = options_dict
        self.market_locked = False
        self.cursor.execute("DELETE FROM active_bets") 
        self.conn.commit()

    def lock_market(self):
        """Freezes the sportsbook so viewers can't place late bets."""
        self.market_locked = True

    def place_bet(self, username, prediction, amount):
        """Processes a viewer's bet. Returns success status, new balance, and error codes."""
        balance = self.get_bankroll(username)
        if self.market_locked: return False, balance, "locked" 
        if prediction not in self.current_market: return False, balance, "invalid"
        if balance < amount: return False, balance, "funds"
            
        multiplier = self.current_market[prediction]
        new_balance = balance - amount
        
        # Deduct money and save the bet ticket
        self.cursor.execute("UPDATE viewers SET bankroll = ? WHERE username = ?", (new_balance, username))
        self.cursor.execute("INSERT OR REPLACE INTO active_bets (username, prediction, amount, multiplier) VALUES (?, ?, ?, ?)", (username, prediction, amount, multiplier))
        self.conn.commit()
        return True, new_balance, multiplier

    def resolve_bets(self, winning_prediction):
        """Pays out the winners when the streamer manually ends the bet."""
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

    def add_scout_note(self, opponent_tag, note):
        """Saves a 1-sentence observation about the opponent to the Film Room."""
        if not opponent_tag: return
        self.cursor.execute("INSERT INTO film_room (opponent_tag, note) VALUES (?, ?)", (opponent_tag, note))
        # Keep the database clean: Only save the 5 most recent notes per opponent
        self.cursor.execute("DELETE FROM film_room WHERE id NOT IN (SELECT id FROM film_room WHERE opponent_tag = ? ORDER BY id DESC LIMIT 5)", (opponent_tag,))
        self.conn.commit()

    def get_scout_notes(self, opponent_tag):
        """Retrieves past observations about an opponent so the AI remembers them."""
        if not opponent_tag: return []
        self.cursor.execute("SELECT note FROM film_room WHERE opponent_tag = ? ORDER BY id DESC", (opponent_tag,))
        return [row[0] for row in self.cursor.fetchall()]

# ==============================================================================
# 2. THE VOICE (Text-to-Speech Engine)
# Converts text to audio. Runs on a separate thread so it doesn't freeze the bot.
# ==============================================================================
class VoiceEngine:
    def __init__(self):
        self.queue = queue.Queue()
        self.current_voice = "en-US-ChristopherNeural"
        pygame.mixer.init()
        threading.Thread(target=self._worker, daemon=True).start()

    def set_voice(self, voice_id):
        self.current_voice = voice_id

    def say(self, text):
        """Adds text to the speech queue to be spoken aloud."""
        self.queue.put(text)

    def _worker(self):
        """Background loop that continuously checks the queue for things to say."""
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
                while pygame.mixer.music.get_busy(): time.sleep(0.1) # Wait until done speaking
            except Exception as e: 
                print(f"❌ Edge-TTS Error: {e}")
            self.queue.task_done()

# ==============================================================================
# 3. THE VISION (Camera & Local OCR Engine)
# Captures the screen and uses Tesseract to read text locally (saving API tokens).
# ==============================================================================
class VisionEngine:
    def __init__(self, camera_index=0):
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.current_frame = None
        self.running = True
        threading.Thread(target=self._update_loop, daemon=True).start()

    def _update_loop(self):
        """Constantly pulls the newest frame from the capture card."""
        while self.running:
            ret, frame = self.cap.read()
            if ret: self.current_frame = frame
            time.sleep(0.01)

    def get_frame(self): 
        return self.current_frame
        
    def read_screen_text(self):
        """Slices the frame into 3 Zones and reads the text instantly using local OCR."""
        frame = self.get_frame()
        if frame is None: return None

        # THE FIX: Force the image to 1280x720 so our coordinates NEVER miss
        frame = cv2.resize(frame, (1280, 720))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # ROI (Region of Interest) ZONES for Madden 25 UI
        zone_top = gray[10:90, 0:1280]       # Top Banners (Gamertags)
        zone_bottom = gray[630:720, 0:1280]  # Bottom Scoreboard
        zone_center = gray[280:440, 300:980] # Dead Center (Pop-ups)

        # --psm 11 tells Tesseract to look for scattered game text
        custom_config = r'--oem 3 --psm 11'
        text_top = pytesseract.image_to_string(zone_top, config=custom_config).strip()
        text_bottom = pytesseract.image_to_string(zone_bottom, config=custom_config).strip()
        text_center = pytesseract.image_to_string(zone_center, config=custom_config).strip()

        return f"TOP BANNER (Gamertags): {text_top} | SCOREBOARD: {text_bottom} | POPUPS: {text_center}"
    
    def __del__(self):
        self.running = False
        if self.cap.isOpened(): self.cap.release()

# ==============================================================================
# 4. THE STRATEGIST (Gemini AI Engine)
# Handles all communication with the Google Gemini API for coaching and betting.
# ==============================================================================
class AIEngine:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model = 'gemini-2.5-flash' 

    def _clean_json(self, text):
        """Strips markdown formatting from the AI response to prevent JSON crashes."""
        text = text.strip()
        if text.startswith("```json"): text = text[7:]
        elif text.startswith("```"): text = text[3:]
        if text.endswith("```"): text = text[:-3]
        return text.strip()

    def generate_prop_bet(self, image_path, game_type, streamer_name, gamer_tag):
        """Generates a live, mid-game prop bet based on the current situation."""
        prompt = f"""
        Look at this gameplay of {game_type}. You are coaching '{streamer_name}'. 
        Their Gamertag is '{gamer_tag}'.
        Act as a Vegas oddsmaker. Generate a live prop bet with 2 to 4 options (a, b, c, d) with decimal odds.
        Output strict JSON: {{"question": "What happens?", "options": {{"a": {{"text": "TD", "odds": 2.5}}}} }}
        """
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7))
            return json.loads(self._clean_json(response.text))
        except Exception as e: return None

    def generate_game_props(self, image_path, game_type, streamer_name, gamer_tag):
        """Generates a Pre-Game parlay (Over/Under bets) for the whole match."""
        prompt = f"""
        Look at this opening screen of {game_type}. You are coaching '{streamer_name}'. 
        Their Gamertag is '{gamer_tag}'.
        Act as a Vegas oddsmaker. Generate a "Pre-Game Parlay" prop bet with 3 specific Over/Under options.
        Output strict JSON: {{"question": "Pre-Game Prop: Which hits?", "options": {{"a": {{"text": "Over 2.5 Pass TDs", "odds": 1.9}}}} }}
        """
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7))
            return json.loads(self._clean_json(response.text))
        except Exception as e: return None

    def generate_auto_prop(self, image_path, game_type, streamer_name, gamer_tag):
        """Auto-generates a bet on a timer and calculates how long it should stay open."""
        prompt = f"""
        Look at this gameplay of {game_type}. You are coaching '{streamer_name}'. 
        Their Gamertag is '{gamer_tag}'.
        Act as a Vegas oddsmaker. Generate a specific prop bet with 2 to 4 options.
        Determine exactly how many seconds this bet should stay open to build suspense.
        Output strict JSON: {{"question": "What happens?", "lock_seconds": 90, "options": {{"a": {{"text": "TD", "odds": 2.5}}}} }}
        """
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.8))
            return json.loads(self._clean_json(response.text))
        except Exception as e: return None

    def analyze(self, image_path, game_type, streamer_name, gamer_tag, user_question=None, scout_notes=None, ocr_text=None, recent_chat=None):
        """The Master Broadcast Booth function. Returns both spoken advice and chat commentary."""
        
        # THE TANDEM DUO PROMPT: Forces the AI to split its brain into two roles.
        persona_rules = f"""
        CRITICAL INSTRUCTION: You are operating as TWO distinct AI personalities working in tandem in a broadcast booth:
        1. THE TACTICAL COACH (Generates the "advice" field): Speak directly to the streamer, '{streamer_name}'. Provide high-level, cutthroat {game_type} strategy. Be analytical and sharp.
        2. THE COLOR COMMENTATOR (Generates the "commentary" field): Speak directly to the Twitch Chat viewers. Describe the on-screen action, hype up the stream, and WELCOME/SHOUT OUT the viewers seen in the recent chat log. Keep it engaging.
        """
        
        player_context = f"The visual Gamertag on screen is '{gamer_tag}'."
        game_rules = f"They are playing {game_type}."
        
        # Injects the locally gathered OCR data and Twitch Chat straight into the prompt
        ocr_context = f"CRITICAL UI DATA (Trust this text over the image): {ocr_text}\n" if ocr_text else ""
        chat_context = f"RECENT TWITCH CHAT LOG:\n{recent_chat}\n" if recent_chat else "No recent chat.\n"
        
        if game_type == "Madden":
            game_rules += f"""
            CRITICAL MADDEN INSTRUCTIONS:
            - TEAM DETECTION: Read the OCR SCOREBOARD text. Determine which team '{streamer_name}' is controlling, and which team the opponent controls. 
            - OPPONENT PROFILING: Scan the top banners for the active opponent. Find the tag that is NOT '{gamer_tag}'. IF YOU ARE IN A MENU, output exactly "None".
            - SITUATIONAL FOOTBALL: Read the Quarter, Game Clock, Play Clock, Down, and Distance from the UI Data provided. 
            - Scan defensive shells pre-snap.
            - Output JSON: {{"advice": "spoken", "commentary": "chat (MAX 400 CHARS)", "opponent_tag": "tag", "scouting_note": "note", "streamer_team": "team", "opponent_team": "team"}}
            """
            
        # Combines the last 5 database notes into a memory block
        memory_context = "PAST OBSERVATIONS OF OPPONENT:\n" + "\n".join([str(note) for note in scout_notes if note]) if scout_notes else ""

        if user_question: prompt = f"{persona_rules}\n{player_context}\n{game_rules}\n{ocr_context}{chat_context}{memory_context}\nViewer Asked: '{user_question}'. Answer them. Output strict JSON."
        else: prompt = f"{persona_rules}\n{player_context}\n{game_rules}\n{ocr_context}{chat_context}{memory_context}\nAnalyze screen. Output strict JSON."
        
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(model=self.model, contents=[prompt, img], config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.8))
            return json.loads(self._clean_json(response.text))
        except Exception as e: return None

