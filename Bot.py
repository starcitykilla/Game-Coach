# bot.py
import time
import queue
import cv2
import threading
import asyncio
import http.server
import socketserver
import json
import os
from twitchio.ext import commands
import config
from engines import ScoutBrain, VoiceEngine, VisionEngine, AIEngine

class CommanderBot(commands.Bot):
    def __init__(self, log_callback):
        """Initializes the bot, connects to Twitch, and boots up all the sub-engines."""
        super().__init__(token=config.TWITCH_TOKEN, prefix='!', initial_channels=[config.CHANNEL_NAME])
        self.log_callback = log_callback # Sends messages back to the GUI text box
        
        # Boot up the Engines
        self.brain = ScoutBrain()                                  
        self.voice = VoiceEngine()          
        self.eyes = VisionEngine(camera_index=config.CAMERA_INDEX) 
        self.strategist = AIEngine(api_key=config.GEMINI_API_KEY)  
        
        self.chat_queue = queue.PriorityQueue() 
        self.running = True                     
        
        self.voice_enabled = True
        self.chat_enabled = True
        self.current_game = "Madden"
        
        # Hardcoded Identity (Pulled from config.py)
        self.streamer_name = config.STREAMER_NAME
        self.gamer_tag = config.GAMERTAG
        
        # Dynamic State Variables
        self.current_opponent = None
        self.last_chat_time = 0
        self.current_bet_display = None 
        self.recent_chat_log = [] # Holds the last 5 Twitch messages for the Commentator

        # Start the local web server for OBS to read from
        threading.Thread(target=self.start_web_server, daemon=True).start()

    def start_web_server(self):
        """Hosts stream_data.json on Port 8000 so the OBS Browser Source can read it."""
        PORT = 8000
        Handler = http.server.SimpleHTTPRequestHandler
        socketserver.TCPServer.allow_reuse_address = True # Prevents "Port in Use" crash
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            self.log_callback("SYSTEM", f"🌐 OBS Server is running on port {PORT}")
            httpd.serve_forever()

    def update_overlay(self):
        """Saves current state to a JSON file so the HTML overlay updates live."""
        try:
            notes = self.brain.get_scout_notes(self.current_opponent) if self.current_game == "Madden" and self.current_opponent else []
            data = {
                "persona": "Tactical Booth",
                "opponent": self.current_opponent,
                "notes": notes[:3] if notes else ["No scouting data available yet."],
                "market": self.brain.current_market if self.brain.current_market else None,
                "market_display": self.current_bet_display if self.brain.current_market else None,
                "leaderboard": self.brain.get_leaderboard(5) # Sends the Top 5 Whales
            }
            with open(os.path.join(os.getcwd(), "stream_data.json"), "w") as f:
                json.dump(data, f)
        except Exception as e:
            self.log_callback("ERROR", f"Overlay update failed: {e}")

    async def event_ready(self):
        """Fires when the bot successfully logs into Twitch."""
        self.log_callback("SYSTEM", f"✅ Online as {self.nick}")
        self.update_overlay()
        # Start all background tasks
        threading.Thread(target=self.game_loop, daemon=True).start()
        asyncio.create_task(self.chat_dispatcher())
        asyncio.create_task(self.auto_sportsbook_loop())

    async def event_message(self, message):
        """Listens to every single message in chat for commands or VIP questions."""
        if message.echo: return 

        author = message.author.name.lower() if message.author else ""
        msg_text = message.content.lower()

        # Save chat for the Commentator AI
        self.recent_chat_log.append(f"{author}: {msg_text}")
        if len(self.recent_chat_log) > 5: self.recent_chat_log.pop(0) # Keep only the last 5

        # Custom VIP Question Handler (Checks for specific Twitch Channel Point Reward)
        reward_id = message.tags.get('custom-reward-id') if message.tags else None
        VIP_REWARD_ID = "YOUR-SECRET-ID-HERE" 
        
        if reward_id == VIP_REWARD_ID:
            question_text = msg_text.strip(" ,?:")
            if question_text:
                self.log_callback("CHAT_Q", f"💎 VIP @{author} asks: {question_text}")
                formatted_question = f"Twitch VIP @{author} asks: '{question_text}'"
                # Send question to AI on a separate thread to avoid freezing chat
                threading.Thread(target=self.trigger_analysis, kwargs={'user_question': formatted_question}, daemon=True).start()

        # Pass message to the command processor (!bet, !bankroll, etc.)
        await self.handle_commands(message)

    async def chat_dispatcher(self):
        """Ensures the bot doesn't spam Twitch chat too fast (prevents bans)."""
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            now = time.time()
            if not self.chat_queue.empty():
                timestamp, message = self.chat_queue.queue[0]
                if now >= timestamp:
                    self.chat_queue.get() 
                    if channel and self.chat_enabled:
                        chat_text = f"🎙️ Booth: {message}"
                        if len(chat_text) > 495: chat_text = chat_text[:492] + "..." 
                        await channel.send(chat_text)
                        self.log_callback("BOT_CHAT", f"Sent: {chat_text}")
            await asyncio.sleep(1)

    async def auto_sportsbook_loop(self):
        """Wakes up every 10 minutes to auto-generate a prop bet."""
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            await asyncio.sleep(600) # 600 seconds = 10 minutes
            
            if not self.eyes: continue
            frame = self.eyes.get_frame()
            if frame is None: continue

            cv2.imwrite("temp_auto_bet.jpg", cv2.resize(frame, (640, 360)))
            self.log_callback("SPORTSBOOK", "Auto-Bookie is waking up...")

            bet_data = await asyncio.to_thread(self.strategist.generate_auto_prop, "temp_auto_bet.jpg", self.current_game, self.streamer_name, self.gamer_tag)
            
            if bet_data:
                self.current_bet_display = bet_data 
                market_dict = {key: data["odds"] for key, data in bet_data["options"].items()}
                self.brain.open_market(market_dict)
                self.update_overlay()
                
                lock_time = bet_data.get("lock_seconds", 120) 
                
                announcement = f"🚨 THE AI CASINO IS OPEN: {bet_data['question']} 🚨 "
                for key, data in bet_data["options"].items(): announcement += f"| !bet {key} [amount] for {data['text']} ({data['odds']}x) "
                announcement += f"| ⏳ LOCKING IN {lock_time} SECONDS!"
                
                if channel: await channel.send(announcement)
                await asyncio.sleep(lock_time)
                
                self.brain.lock_market()
                if channel: await channel.send("🔒 THE AUTO-BOOKIE HAS LOCKED THE MARKET! No more bets.")

    def trigger_analysis(self, user_question=None):
        """The core analysis chain: Eyes -> Brain -> Voice/Chat."""
        if not self.eyes: return
        frame = self.eyes.get_frame()
        if frame is None: return

        # Compress image to save AI processing time
        cv2.imwrite("temp_frame.jpg", cv2.resize(frame, (640, 360)))
        
        self.voice.set_voice("en-US-ChristopherNeural") 
            
        if user_question: self.log_callback("AI", f"🧠 Answering VIP Question...")
        else: self.log_callback("AI", f"🧠 The Booth is analyzing the field...")

        # 1. Grab fast OCR text data locally
        ocr_text = self.eyes.read_screen_text()
        
        # 2. Check if we have past notes on this opponent
        notes = self.brain.get_scout_notes(self.current_opponent) if self.current_game == "Madden" and self.current_opponent else None
        
        # 3. Format the recent chat log into a readable string for the Commentator
        chat_string = "\n".join(self.recent_chat_log)
        
        # 4. Send Image + OCR Text + Memory + Chat to Gemini
        data = self.strategist.analyze("temp_frame.jpg", self.current_game, self.streamer_name, self.gamer_tag, user_question, notes, ocr_text, chat_string)
        
        if data:
            # 5. Safely Update Opponent Target (Ignore Menus)
            if "opponent_tag" in data and data["opponent_tag"]:
                cleaned_tag = str(data["opponent_tag"]).strip()
                if cleaned_tag.lower() not in ["unknown", "none", "n/a", "null", ""]:
                    if self.current_opponent != cleaned_tag:
                        self.current_opponent = cleaned_tag
                        self.log_callback("SYSTEM", f"🎯 Target locked: {self.current_opponent}")
                        self.update_overlay()
            
            # 6. Save Scouting Notes to Database
            if "scouting_note" in data and self.current_game == "Madden" and self.current_opponent:
                cleaned_note = str(data["scouting_note"]).strip()
                if cleaned_note.lower() not in ["unknown", "none", "n/a", "null", ""]:
                    self.brain.add_scout_note(self.current_opponent, cleaned_note)
                    self.update_overlay() 

            # 7. Speak the tactical advice out loud to the streamer
            if "advice" in data:
                self.log_callback("COACH", f"🗣 {data['advice']}")
                if self.voice_enabled: self.voice.say(data['advice'])
            
            # 8. Send the hype commentary to the Twitch chat queue
            if "commentary" in data:
                now = time.time()
                # Cooldown prevents the bot from talking to itself too much
                if user_question or (now - self.last_chat_time > config.CHAT_COOLDOWN):
                    post_time = time.time() + (0 if user_question else config.STREAM_DELAY)
                    self.chat_queue.put((post_time, data['commentary']))
                    if not user_question: self.last_chat_time = now
        else:
            self.log_callback("ERROR", "❌ AI Failed! Check terminal.")

    def game_loop(self):
        """The primary heartbeat of the bot. Runs analysis based on the set interval."""
        self.log_callback("SYSTEM", "👀 Watch Loop Started")
        last_scan = 0
        while self.running:
            now = time.time()
            if now - last_scan > config.ANALYSIS_INTERVAL:
                last_scan = now
                self.trigger_analysis() 
            time.sleep(0.1)

    # -------------------------------------------------------------------------
    # TWITCH COMMANDS (!bankroll, !bet, !oddsmaker, etc.)
    # -------------------------------------------------------------------------

    @commands.command(name='bankroll')
    async def check_bankroll(self, ctx: commands.Context):
        """Lets a viewer check their balance."""
        user = ctx.author.name.lower()
        balance = self.brain.get_bankroll(user)
        await ctx.send(f"💰 @{user}, you have ${balance}.")
        
    @commands.command(name='leaderboard')
    async def show_leaderboard(self, ctx: commands.Context):
        """Prints the top 3 wealthiest viewers in Twitch chat."""
        top_players = self.brain.get_leaderboard(3)
        if not top_players:
            await ctx.send("🏆 The Virtual Vegas leaderboard is currently empty!")
            return
            
        announcement = "🏆 VIRTUAL VEGAS HIGH ROLLERS: "
        for i, (user, bankroll) in enumerate(top_players):
            announcement += f"{i+1}. @{user} (${bankroll}) | "
        await ctx.send(announcement)

    @commands.command(name='oddsmaker')
    async def create_market(self, ctx: commands.Context):
        """Streamer ONLY command: Forces an instant mid-game prop bet."""
        if not ctx.author.is_broadcaster: return
        
        if not self.eyes: return
        frame = self.eyes.get_frame()
        if frame is None: return
        
        cv2.imwrite("temp_bet.jpg", cv2.resize(frame, (640, 360)))
        self.log_callback("SPORTSBOOK", "🎲 Manual trigger! Oddsmaker analyzing...")
        
        # Run in thread so chat doesn't freeze while waiting for Gemini
        threading.Thread(target=self._run_manual_oddsmaker_thread, daemon=True).start()

    def _run_manual_oddsmaker_thread(self):
        bet_data = self.strategist.generate_prop_bet("temp_bet.jpg", self.current_game, self.streamer_name, self.gamer_tag)
        if bet_data:
            self.current_bet_display = bet_data 
            market_dict = {key: data["odds"] for key, data in bet_data["options"].items()}
            self.brain.open_market(market_dict)
            self.update_overlay()
            
            announcement = f"🚨 LIVE PROP: {bet_data['question']} 🚨 "
            for key, data in bet_data["options"].items(): announcement += f"| Type '!bet {key} [amount]' for {data['text']} ({data['odds']}x) "
            
            self.chat_queue.put((time.time(), announcement))
            self.log_callback("SPORTSBOOK", "New Market Opened via Command Center!")

    @commands.command(name='startgame')
    async def start_game_market(self, ctx: commands.Context):
        """Streamer ONLY command: Creates a Pre-Game Parlay bet."""
        if not ctx.author.is_broadcaster: return
        frame = self.eyes.get_frame()
        if frame is None: return
        cv2.imwrite("temp_bet.jpg", cv2.resize(frame, (640, 360)))
        
        await ctx.send("🎲 Oddsmaker is reading the rosters to build the Pre-Game Parlay...")
        bet_data = self.strategist.generate_game_props("temp_bet.jpg", self.current_game, self.streamer_name, self.gamer_tag)
        
        if bet_data:
            self.current_bet_display = bet_data
            market_dict = {key: data["odds"] for key, data in bet_data["options"].items()}
            self.brain.open_market(market_dict)
            self.update_overlay()
            announcement = f"🚨 PRE-GAME PROPS: {bet_data['question']} 🚨 "
            for key, data in bet_data["options"].items(): announcement += f"| Type '!bet {key} [amount]' for {data['text']} ({data['odds']}x) "
            await ctx.send(announcement)

    @commands.command(name='lock')
    async def lock_market(self, ctx: commands.Context):
        """Streamer ONLY command: Manually freezes the sportsbook."""
        if not ctx.author.is_broadcaster: return
        self.brain.lock_market()
        await ctx.send("🔒 THE SPORTSBOOK IS NOW LOCKED! No more bets can be placed.")
        self.log_callback("SPORTSBOOK", "Market Locked!")

    @commands.command(name='bet')
    async def place_bet(self, ctx: commands.Context):
        """Handles viewer bets formatted as: !bet [option] [amount]"""
        user = ctx.author.name.lower()
        parts = ctx.message.content.split()
        if len(parts) != 3:
            await ctx.send(f"⚠️ @{user}, use format: !bet [a/b/c] [amount]")
            return
            
        prediction = parts[1].lower()
        try:
            amount = int(parts[2])
            if amount <= 0: raise ValueError
        except ValueError:
            await ctx.send(f"⚠️ @{user}, invalid dollar amount.")
            return

        success, new_balance, result_code = self.brain.place_bet(user, prediction, amount)
        if success: await ctx.send(f"🎟️ @{user} locked in ${amount} on option {prediction.upper()} (Pays {result_code}x). Balance: ${new_balance}")
        elif result_code == "locked": await ctx.send(f"🛑 @{user}, too late! The market is locked.")
        elif result_code == "invalid": await ctx.send(f"❌ @{user}, that is not a valid option.")
        elif result_code == "funds": await ctx.send(f"❌ @{user}, insufficient funds! You have ${new_balance}.")

    @commands.command(name='result')
    async def resolve_bet(self, ctx: commands.Context):
        """Streamer ONLY command: Pays out the winning option (e.g., !result a)"""
        if not ctx.author.is_broadcaster: return
        parts = ctx.message.content.split()
        if len(parts) != 2: return
            
        winning_option = parts[1].lower()
        winners_count, total_paid = self.brain.resolve_bets(winning_option)
        self.update_overlay()
        
        if winners_count > 0: await ctx.send(f"🏁 Option {winning_option.upper()} wins! Paid out ${total_paid} to {winners_count} winners.")
        else: await ctx.send(f"🏁 Option {winning_option.upper()} wins! The house sweeps the board.")

