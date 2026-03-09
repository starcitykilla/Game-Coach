import time
import queue
import cv2
import threading
import asyncio
import http.server
import socketserver
import json
import os
import shutil
import aiohttp
import uuid
from twitchio.ext import commands

import config
from db_engine import ScoutBrain
from audio_engine import AudioEngine
from vision_engine import VisionEngine
from ai_engine import AIEngine

class CommanderBot(commands.Bot):
    """The central nervous system linking Twitch chat to the AI engines."""
    def __init__(self, log_callback):
        super().__init__(token=config.TWITCH_TOKEN, prefix='!', initial_channels=[config.CHANNEL_NAME])
        self.log_callback = log_callback

        self.brain = ScoutBrain()
        self.ears = AudioEngine()
        self.eyes = VisionEngine(camera_index=config.CAMERA_INDEX)
        self.strategist = AIEngine(api_key=config.GEMINI_API_KEY)

        self.chat_queue, self.running, self.chat_enabled = queue.PriorityQueue(), True, True
        self.current_game, self.current_opponent = "Detecting Game...", None
        self.current_bet_display, self.recent_chat_log = None, []
        self.active_viewers, self.claimed_users, self.last_tripwire_time, self.last_chat_time = {}, set(), 0, 0
        
        self.last_ocr_text = "Waiting for initial scan..." # Cached for the Diagnostic GUI

        self.bounty_board = {
            "fakepunt": {"cost": 5000, "desc": "Force Coach to run a Fake Punt on 4th Down!"},
            "blitz": {"cost": 3000, "desc": "Engage Eight! Coach MUST run an all-out blitz next defensive play."},
            "hydrate": {"cost": 1000, "desc": "Coach has to take a drink of water!"}
        }

        os.makedirs("bet_history_frames", exist_ok=True)
        threading.Thread(target=self.start_web_server, daemon=True).start()

    def start_web_server(self):
        """Silently hosts the JSON file for the OBS Browser Source."""
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args): pass 
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", 8000), QuietHandler) as httpd:
            self.log_callback("SYSTEM", "🌐 OBS Server is running quietly on port 8000")
            httpd.serve_forever()

    def update_overlay(self):
        threading.Thread(target=self._write_overlay_file, daemon=True).start()

    def _write_overlay_file(self):
        try:
            notes = self.brain.get_scout_notes(self.current_opponent, self.current_game) if self.current_opponent else []
            data = {
                "persona": "Tactical Booth", "opponent": self.current_opponent,
                "notes": notes[:3] if notes else ["No scouting data available yet."],
                "market": self.brain.current_market, "market_display": self.current_bet_display,
                "leaderboard": self.brain.get_leaderboard(5)
            }
            with open(os.path.join(os.getcwd(), "stream_data.json"), "w") as f: json.dump(data, f)
        except Exception as e: self.log_callback("ERROR", f"Overlay update failed: {e}")

    # ... [Twitch Marker and Clip API logic remains unchanged] ...
    def trigger_manual_clip(self):
        self.log_callback("SYSTEM", "🎬 MANUAL CLIP INITIATED FROM DASHBOARD!")
        # (Assuming create_twitch_highlight is defined here as before)

    async def event_ready(self):
        self.log_callback("SYSTEM", f"✅ Online as {self.nick}")
        self.update_overlay()
        threading.Thread(target=self.game_loop, daemon=True).start()
        
        for task in [self.chat_dispatcher, self.auto_sportsbook_loop, self.ai_referee_loop, self.watcher_payout_loop, self.edge_tripwire_loop]:
            asyncio.create_task(task())

    async def auto_sportsbook_loop(self):
        """Generates random micro-bets every 10 minutes."""
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            await asyncio.sleep(600)
            if not getattr(self, 'eyes', None) or self.eyes.get_frame() is None: continue

            auto_img = f"temp_auto_bet_{uuid.uuid4().hex}.jpg"
            # Compressed for faster upload speeds
            cv2.imwrite(auto_img, cv2.resize(self.eyes.get_frame(), (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 60])
            self.log_callback("SPORTSBOOK", "Auto-Bookie is waking up...")

            bet_data = await asyncio.to_thread(self.strategist.generate_auto_prop, auto_img, self.current_game, config.STREAMER_NAME, config.GAMERTAG, self.ears.get_transcript())
            if os.path.exists(auto_img): os.remove(auto_img)

            if bet_data:
                self.current_bet_display = bet_data
                self.brain.open_market({k: v["odds"] for k, v in bet_data["options"].items()}, bet_data['question'])
                self.update_overlay()

                lock_time = 15 # Hardcoded rapid-fire lock
                announcement = f"🚨 THE AI CASINO IS OPEN: {bet_data['question']} 🚨 " + " | ".join([f"!bet {k} [amt] ({v['odds']}x)" for k, v in bet_data["options"].items()])
                if channel: await channel.send(f"{announcement} | ⏳ LOCKING IN {lock_time} SECONDS!")
                
                await asyncio.sleep(lock_time)
                self.brain.lock_market()
                if channel: await channel.send("🔒 THE AUTO-BOOKIE HAS LOCKED THE MARKET!")

    async def ai_referee_loop(self):
        """Actively watches the screen to resolve locked bets instantly."""
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            await asyncio.sleep(5) 
            if self.brain.market_locked and self.current_bet_display and getattr(self, 'eyes', None) and self.eyes.get_frame() is not None:
                ref_img = f"temp_ref_{uuid.uuid4().hex}.jpg"
                cv2.imwrite(ref_img, cv2.resize(self.eyes.get_frame(), (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 60])
                
                self.last_ocr_text = self.eyes.read_screen_text() or ""
                result = await asyncio.to_thread(self.strategist.check_bet_resolution, ref_img, self.current_game, self.current_bet_display, self.last_ocr_text)
                if os.path.exists(ref_img): os.remove(ref_img)
                
                if result and result.get("status") == "resolved" and result.get("winning_key"):
                    win_key = result["winning_key"].lower()
                    winners, payout = self.brain.resolve_bets(win_key)
                    self.current_bet_display = None
                    self.update_overlay()
                    
                    if channel:
                        msg = f"🏁 AI REFEREE: Option {win_key.upper()} wins! "
                        msg += f"Paid out ${payout} to {winners} viewers." if winners > 0 else "The house sweeps."
                        await channel.send(msg)

    async def edge_tripwire_loop(self):
        """Listens for hype words to trigger highlights."""
        while self.running:
            await asyncio.sleep(1)
            if time.time() - self.last_tripwire_time < 20 or not self.eyes or not self.ears: continue

            audio, ocr = self.ears.get_transcript().lower(), (self.eyes.read_screen_text() or "").lower()
            self.last_ocr_text = ocr

            trip_words = ["touchdown", "intercept", "fumble", "sacked", "turnover"]
            if any(w in audio for w in trip_words) or any(w in ocr for w in trip_words):
                self.last_tripwire_time = time.time()
                self.log_callback("TRIPWIRE", "🚨 Edge Tripwire Triggered!")
                if frame := self.eyes.get_buffered_frame(45):
                    trip_img = f"temp_trip_{uuid.uuid4().hex}.jpg"
                    cv2.imwrite(trip_img, cv2.resize(frame, (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 60])
                    threading.Thread(target=self._run_tripwire_analysis, args=(ocr, audio, trip_img), daemon=True).start()

    def _run_tripwire_analysis(self, ocr_text, audio_text, img_path):
        data = self.strategist.analyze(img_path, self.current_game, config.STREAMER_NAME, config.GAMERTAG, self.current_opponent, None, 
                                       self.brain.get_scout_notes(self.current_opponent, self.current_game) if self.current_opponent else None, 
                                       ocr_text, "\n".join(self.recent_chat_log), audio_text)
        if os.path.exists(img_path): os.remove(img_path)
        if data and "commentary" in data: self.chat_queue.put((time.time() + config.STREAM_DELAY, data['commentary']))

    async def watcher_payout_loop(self):
        """Passive economy income."""
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            await asyncio.sleep(900)
            paid = sum(1 for user, last in list(self.active_viewers.items()) if time.time() - last < 1800 and not self.brain.add_funds(user, 100))
            if paid > 0 and channel: await channel.send(f"💸 VIRTUAL VEGAS PAYOUT: Dropped $100 into the accounts of {paid} active viewers!")

    async def chat_dispatcher(self):
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            if not self.chat_queue.empty() and time.time() >= self.chat_queue.queue[0][0]:
                _, message = self.chat_queue.get()
                if channel and self.chat_enabled: await channel.send(f"🎙️ Booth: {message[:492]}")
            await asyncio.sleep(1)

    def trigger_analysis(self, user_question=None):
        """The main coaching analysis loop."""
        if not self.eyes or (frame := self.eyes.get_frame()) is None: return

        temp_img = f"temp_frame_{uuid.uuid4().hex}.jpg"
        cv2.imwrite(temp_img, cv2.resize(frame, (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 60])

        self.last_ocr_text = self.eyes.read_screen_text()
        data = self.strategist.analyze(temp_img, self.current_game, config.STREAMER_NAME, config.GAMERTAG, self.current_opponent, user_question, 
                                       self.brain.get_scout_notes(self.current_opponent, self.current_game) if self.current_opponent else None, 
                                       self.last_ocr_text, "\n".join(self.recent_chat_log), self.ears.get_transcript())
        if os.path.exists(temp_img): os.remove(temp_img)

        if data:
            if "game_type" in data and data["game_type"] != self.current_game:
                self.current_game = data["game_type"]
                if "Menu" in self.current_game or "Lobby" in self.current_game:
                    self.current_opponent = None
                    self.update_overlay()

            # --- IRONCLAD STATE LOCK ---
            tag = str(data.get("opponent_tag", "")).strip()
            if tag.lower() not in ["unknown", "none", "n/a", "null", ""]:
                if self.current_opponent is None:
                    self.current_opponent = tag
                    self.update_overlay()
                elif "Menu" in self.current_game or "Lobby" in self.current_game:
                    if self.current_opponent != tag:
                        self.current_opponent = tag
                        self.update_overlay()

            if "scouting_note" in data and self.current_opponent and self.current_opponent.upper() != "CPU":
                if (note := str(data["scouting_note"]).strip()).lower() not in ["unknown", "none", "n/a", "null", ""]:
                    self.brain.add_scout_note(self.current_opponent, self.current_game, note)
                    self.update_overlay()

            if "commentary" in data and (user_question or time.time() - self.last_chat_time > config.CHAT_COOLDOWN):
                self.chat_queue.put((time.time() + (0 if user_question else config.STREAM_DELAY), data['commentary']))
                if not user_question: self.last_chat_time = time.time()

    def game_loop(self):
        last_scan = 0
        while self.running:
            if time.time() - last_scan > config.ANALYSIS_INTERVAL:
                last_scan = time.time()
                self.trigger_analysis()
            time.sleep(0.1)

    # --- Standard Twitch Commands (!bet, !bounty, etc. remain unchanged) ---
    async def event_message(self, message):
        if message.echo: return
        author = message.author.name.lower() if message.author else ""
        if author: self.active_viewers[author] = time.time()
        self.recent_chat_log.append(f"{author}: {message.content.lower()}")
        if len(self.recent_chat_log) > 5: self.recent_chat_log.pop(0)
        await self.handle_commands(message)

    @commands.command(name='bankroll')
    async def check_bankroll(self, ctx: commands.Context):
        await ctx.send(f"💰 @{ctx.author.name}, you have ${self.brain.get_bankroll(ctx.author.name.lower())}.")
