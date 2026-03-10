import time
import queue
import cv2
import threading
import asyncio
import http.server
import socketserver
import json
import os
import uuid
from twitchio.ext import commands

import config
from db_engine import ScoutBrain
from audio_engine import AudioEngine
from vision_engine import VisionEngine
from ai_engine import AIEngine
from voice_engine import VoiceEngine

class CommanderBot(commands.Bot):
    def __init__(self, log_callback):
        super().__init__(token=config.TWITCH_TOKEN, prefix='!', initial_channels=[config.CHANNEL_NAME])
        self.log_callback = log_callback

        self.brain = ScoutBrain()
        self.ears = AudioEngine()
        self.eyes = VisionEngine(camera_index=config.CAMERA_INDEX)
        self.strategist = AIEngine(api_key=config.GEMINI_API_KEY)
        self.voice = VoiceEngine() 

        self.chat_queue, self.running, self.chat_enabled = queue.PriorityQueue(), True, True
        self.current_game, self.current_opponent = "Detecting Game...", None
        self.current_bet_display, self.recent_chat_log = None, []
        self.active_viewers, self.last_tripwire_time, self.last_chat_time = {}, 0, 0
        
        self.last_ocr_text = "Waiting for initial scan..." 
        self.encounter_count = 0
        self.death_count = 0
        self.viewer_coach_requests = 0 

        self.bounty_board = {
            "fakepunt": {"cost": 5000, "desc": "Force Coach to run a Fake Punt on 4th Down!"},
            "blitz": {"cost": 3000, "desc": "Engage Eight! Coach MUST run an all-out blitz next defensive play."}
        }

        os.makedirs("bet_history_frames", exist_ok=True)
        threading.Thread(target=self.start_web_server, daemon=True).start()

    def start_web_server(self):
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args): pass 
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", 8000), QuietHandler) as httpd:
            self.log_callback("SYSTEM", "🌐 OBS Server running on port 8000")
            httpd.serve_forever()

    def update_overlay(self):
        threading.Thread(target=self._write_overlay_file, daemon=True).start()

    def _write_overlay_file(self):
        try:
            notes = self.brain.get_scout_notes(self.current_opponent, self.current_game) if self.current_opponent else []
            data = {"persona": "Tactical Booth", "opponent": self.current_opponent, "notes": notes[:3] if notes else ["No scouting data available yet."], "market": self.brain.current_market, "market_display": self.current_bet_display, "leaderboard": self.brain.get_leaderboard(5)}
            with open(os.path.join(os.getcwd(), "stream_data.json"), "w") as f: json.dump(data, f)
        except Exception as e: self.log_callback("ERROR", f"Overlay update failed: {e}")

    def trigger_manual_clip(self):
        self.log_callback("SYSTEM", "🎬 MANUAL CLIP INITIATED!")

    async def event_ready(self):
        self.log_callback("SYSTEM", f"✅ Online as {self.nick}")
        self.update_overlay()
        threading.Thread(target=self.game_loop, daemon=True).start()
        for task in [self.chat_dispatcher, self.auto_sportsbook_loop, self.ai_referee_loop, self.watcher_payout_loop, self.edge_tripwire_loop, self.wake_word_loop]:
            asyncio.create_task(task())

    async def auto_sportsbook_loop(self):
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            await asyncio.sleep(600)
            if not getattr(self, 'eyes', None) or self.eyes.get_frame() is None: continue
            auto_img = f"temp_auto_bet_{uuid.uuid4().hex}.jpg"
            cv2.imwrite(auto_img, cv2.resize(self.eyes.get_frame(), (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 60])
            bet_data = await asyncio.to_thread(self.strategist.generate_auto_prop, auto_img, self.current_game, config.STREAMER_NAME, config.GAMERTAG, self.ears.get_transcript())
            if os.path.exists(auto_img): os.remove(auto_img)

            if bet_data:
                self.current_bet_display = bet_data
                self.brain.open_market({k: v["odds"] for k, v in bet_data["options"].items()}, bet_data['question'])
                self.update_overlay()
                lock_time = 15 
                announcement = f"🚨 AI CASINO OPEN: {bet_data['question']} 🚨 " + " | ".join([f"!bet {k} [amt] ({v['odds']}x)" for k, v in bet_data["options"].items()])
                if channel: await channel.send(f"{announcement} | ⏳ LOCKING IN {lock_time} SECONDS!")
                await asyncio.sleep(lock_time)
                self.brain.lock_market()
                if channel: await channel.send("🔒 MARKET LOCKED!")

    async def ai_referee_loop(self):
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
        while self.running:
            await asyncio.sleep(1)
            if time.time() - self.last_tripwire_time < 20 or not self.eyes or not self.ears: continue
            audio, ocr = self.ears.get_transcript().lower(), (self.eyes.read_screen_text() or "").lower()
            self.last_ocr_text = ocr
            trip_words = ["touchdown", "intercept", "fumble", "sacked", "turnover"]
            if any(w in audio for w in trip_words) or any(w in ocr for w in trip_words):
                self.last_tripwire_time = time.time()
                if frame := self.eyes.get_buffered_frame(45):
                    trip_img = f"temp_trip_{uuid.uuid4().hex}.jpg"
                    cv2.imwrite(trip_img, cv2.resize(frame, (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 60])
                    threading.Thread(target=self._run_tripwire_analysis, args=(ocr, audio, trip_img), daemon=True).start()

    def _run_tripwire_analysis(self, ocr_text, audio_text, img_path):
        data = self.strategist.analyze(img_path, self.current_game, config.STREAMER_NAME, config.GAMERTAG, self.current_opponent, None, self.brain.get_scout_notes(self.current_opponent, self.current_game) if self.current_opponent else None, ocr_text, "\n".join(self.recent_chat_log), audio_text)
        if os.path.exists(img_path): os.remove(img_path)
        if data and "commentary" in data: self.chat_queue.put((time.time() + config.STREAM_DELAY, data['commentary']))

    async def watcher_payout_loop(self):
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            await asyncio.sleep(900)
            paid = sum(1 for user, last in list(self.active_viewers.items()) if time.time() - last < 1800 and not self.brain.add_funds(user, 100))
            if paid > 0 and channel: await channel.send(f"💸 VEGAS PAYOUT: Dropped $100 into {paid} active viewer accounts!")

    async def wake_word_loop(self):
        while self.running:
            await asyncio.sleep(1) 
            if not getattr(self, 'ears', None): continue

            transcript = self.ears.get_transcript().lower()
            wake_word = "hey coach"
            
            if wake_word in transcript:
                self.log_callback("SYSTEM", "🎙️ Wake Word Detected!")
                parts = transcript.split(wake_word)
                if len(parts) > 1:
                    question = parts[-1].strip()
                    if len(question) > 5:
                        self.log_callback("SYSTEM", f"🗣️ Streamer asked: {question}")
                        self.ears.transcript = []
                        self.ears.current_partial = ""
                        threading.Thread(target=self.trigger_analysis, args=(f"Streamer asked: {question}",), daemon=True).start()
                    else:
                        await asyncio.sleep(2)

    async def chat_dispatcher(self):
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            if not self.chat_queue.empty() and time.time() >= self.chat_queue.queue[0][0]:
                _, message = self.chat_queue.get()
                
                self.voice.speak(message)
                
                if channel and self.chat_enabled:
                    chunks = [message[i:i+490] for i in range(0, len(message), 490)]
                    for chunk in chunks:
                        await channel.send(f"🎙️ Booth: {chunk}")
                        await asyncio.sleep(1.5) 
            await asyncio.sleep(1)

    def trigger_analysis(self, user_question=None):
        if not self.eyes or (frame := self.eyes.get_frame()) is None: return

        temp_img = f"temp_frame_{uuid.uuid4().hex}.jpg"
        cv2.imwrite(temp_img, cv2.resize(frame, (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 60])

        self.last_ocr_text = self.eyes.read_screen_text()
        death_triggers = ["you died", "slain", "defendants", "eliminated"]
        if any(trigger in self.last_ocr_text.lower() for trigger in death_triggers):
            self.death_count += 1
            self.log_callback("SYSTEM", f"💀 DEATH DETECTED! Total deaths: {self.death_count}")

        data = self.strategist.analyze(
            temp_img, self.current_game, config.STREAMER_NAME, config.GAMERTAG, 
            self.current_opponent, user_question, 
            self.brain.get_scout_notes(self.current_opponent, self.current_game) if self.current_opponent else None, 
            self.last_ocr_text, "\n".join(self.recent_chat_log), self.ears.get_transcript(),
            self.encounter_count, self.death_count
        )
        if os.path.exists(temp_img): os.remove(temp_img)

        if data:
            if "game_type" in data and data["game_type"] != self.current_game:
                self.current_game = data["game_type"]
                if "Menu" in self.current_game or "Lobby" in self.current_game:
                    self.current_opponent, self.encounter_count, self.death_count = None, 0, 0
                    self.update_overlay()

            tag = str(data.get("opponent_tag", "")).strip()
            if tag.lower() not in ["unknown", "none", "n/a", "null", ""]:
                if self.current_opponent is None:
                    self.current_opponent, self.encounter_count = tag, 1
                    self.update_overlay()
                elif "Menu" in self.current_game or "Lobby" in self.current_game:
                    if self.current_opponent != tag:
                        self.current_opponent, self.encounter_count, self.death_count = tag, 1, 0
                        self.update_overlay()
                elif self.current_opponent == tag:
                    self.encounter_count += 1 

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

    @commands.command(name='heycoach')
    async def ask_coach(self, ctx: commands.Context):
        parts = ctx.message.content.split(' ', 1)
        if len(parts) < 2:
            await ctx.send(f"@{ctx.author.name}, ask a question! (e.g., !heycoach what build is he using?)")
            return

        question = parts[1]

        if self.viewer_coach_requests >= 3:
            await ctx.send(f"🚫 @{ctx.author.name}, the Coach is completely out of timeouts for this stream!")
            return

        self.viewer_coach_requests += 1
        timeouts_left = 3 - self.viewer_coach_requests
        await ctx.send(f"🧠 Coach heard you, @{ctx.author.name}! Let me look... ({timeouts_left} timeouts left)")

        self.log_callback("SYSTEM", f"🗣️ Viewer {ctx.author.name} asked: {question}")
        threading.Thread(
            target=self.trigger_analysis, 
            args=(f"!Viewer '{ctx.author.name}' asked: {question}",), 
            daemon=True
        ).start()
