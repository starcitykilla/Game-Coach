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
from engines import ScoutBrain, VoiceEngine, VisionEngine, AIEngine, EarEngine

class CommanderBot(commands.Bot):
    def __init__(self, log_callback):
        super().__init__(token=config.TWITCH_TOKEN, prefix='!', initial_channels=[config.CHANNEL_NAME])
        self.log_callback = log_callback
        
        self.brain = ScoutBrain()                                  
        self.voice = VoiceEngine()          
        self.eyes = VisionEngine(camera_index=config.CAMERA_INDEX) 
        self.ears = EarEngine()                                    
        self.strategist = AIEngine(api_key=config.GEMINI_API_KEY)  
        
        self.chat_queue = queue.PriorityQueue() 
        self.running = True                     
        
        self.voice_enabled = True
        self.chat_enabled = True
        self.current_game = "Madden"
        self.current_persona = "Play-by-Play Announcer"
        self.gamer_tag = "Krzy Budz"
        self.current_opponent = None
        self.last_chat_time = 0

        threading.Thread(target=self.start_web_server, daemon=True).start()

    def start_web_server(self):
        PORT = 8000
        Handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            self.log_callback("SYSTEM", f"🌐 OBS Server running at http://localhost:{PORT}/overlay.html")
            httpd.serve_forever()

    def update_overlay(self):
        try:
            notes = self.brain.get_scout_notes(self.current_opponent) if self.current_game == "Madden" and self.current_opponent else []
            data = {
                "persona": self.current_persona,
                "opponent": self.current_opponent,
                "notes": notes[:3] if notes else ["No scouting data available yet."],
                "market": self.brain.current_market if self.brain.current_market else None
            }
            with open(os.path.join(os.getcwd(), "stream_data.json"), "w") as f:
                json.dump(data, f)
        except Exception as e:
            self.log_callback("ERROR", f"Overlay update failed: {e}")

    async def event_ready(self):
        self.log_callback("SYSTEM", f"✅ Online as {self.nick}")
        self.update_overlay()
        threading.Thread(target=self.game_loop, daemon=True).start()
        asyncio.create_task(self.chat_dispatcher())

    async def chat_dispatcher(self):
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            now = time.time()
            if not self.chat_queue.empty():
                timestamp, message = self.chat_queue.queue[0]
                if now >= timestamp:
                    self.chat_queue.get() 
                    if channel and self.chat_enabled:
                        await channel.send(f"🤖 Coach: {message}")
                        self.log_callback("BOT_CHAT", f"Sent: {message}")
            await asyncio.sleep(1)

    def trigger_analysis(self, user_question=None):
        if not self.eyes: return
        frame = self.eyes.get_frame()
        if frame is None: return

        small_frame = cv2.resize(frame, (640, 360))
        cv2.imwrite("temp_frame.jpg", small_frame)
        
        if self.current_persona in config.CHARACTER_ROSTER:
            ai_instructions = config.CHARACTER_ROSTER[self.current_persona][0]
            voice_id = config.CHARACTER_ROSTER[self.current_persona][1]
            self.voice.set_voice(voice_id)
        else:
            ai_instructions = self.current_persona 
            self.voice.set_voice("en-US-ChristopherNeural") 
            
        if user_question: self.log_callback("AI", f"🧠 Asking {self.current_persona}...")
        else: self.log_callback("AI", f"🧠 Watching ({self.current_persona})...")

        notes = self.brain.get_scout_notes(self.current_opponent) if self.current_game == "Madden" and self.current_opponent else None
        data = self.strategist.analyze("temp_frame.jpg", self.current_game, ai_instructions, self.gamer_tag, user_question, notes)
        
        if data:
            if "opponent_tag" in data and data["opponent_tag"] and data["opponent_tag"].lower() != "unknown":
                if self.current_opponent != data["opponent_tag"]:
                    self.current_opponent = data["opponent_tag"]
                    self.log_callback("SYSTEM", f"🎯 Target locked: {self.current_opponent}")
                    self.update_overlay()
            
            if "scouting_note" in data and self.current_game == "Madden" and self.current_opponent:
                self.brain.add_scout_note(self.current_opponent, data["scouting_note"])
                self.update_overlay() 

            if "advice" in data:
                self.log_callback("COACH", f"🗣 {data['advice']}")
                if self.voice_enabled: self.voice.say(data['advice'])
            
            if "commentary" in data:
                now = time.time()
                if user_question or (now - self.last_chat_time > config.CHAT_COOLDOWN):
                    post_time = time.time() + (0 if user_question else config.STREAM_DELAY)
                    self.chat_queue.put((post_time, data['commentary']))
                    if not user_question: 
                        self.last_chat_time = now
                        self.log_callback("SYSTEM", f"⏳ Chat on cooldown for {config.CHAT_COOLDOWN}s")
                else:
                    time_left = int(config.CHAT_COOLDOWN - (now - self.last_chat_time))
                    self.log_callback("SYSTEM", f"⏳ Chat skipped (Cooldown: {time_left}s left)")
        else:
            self.log_callback("ERROR", "❌ AI Failed! Check terminal.")

    def game_loop(self):
        self.log_callback("SYSTEM", "👀 Watch Loop Started")
        last_scan = 0
        while self.running:
            now = time.time()
            if now - last_scan > config.ANALYSIS_INTERVAL:
                last_scan = now
                self.trigger_analysis() 
            time.sleep(0.1)

    def process_voice_command(self):
        self.log_callback("EARS", "👂 Listening to you...")
        user_text = self.ears.listen_once()
        if user_text:
            self.log_callback("EARS", f"You said: '{user_text}'")
            self.trigger_analysis(user_question=user_text)
        else:
            self.log_callback("EARS", "❌ Didn't catch that.")

    @commands.command(name='bankroll')
    async def check_bankroll(self, ctx: commands.Context):
        user = ctx.author.name.lower()
        balance = self.brain.get_bankroll(user)
        await ctx.send(f"💰 @{user}, you have ${balance}.")

    @commands.command(name='oddsmaker')
    async def create_market(self, ctx: commands.Context):
        if not ctx.author.is_broadcaster: return
        frame = self.eyes.get_frame()
        if frame is None: return
        cv2.imwrite("temp_bet.jpg", cv2.resize(frame, (640, 360)))
        await ctx.send("🎲 AI Oddsmaker is analyzing the field...")
        bet_data = self.strategist.generate_prop_bet("temp_bet.jpg", self.current_game, self.gamer_tag)
        
        if bet_data:
            market_dict = {key: data["odds"] for key, data in bet_data["options"].items()}
            self.brain.open_market(market_dict)
            self.update_overlay()
            announcement = f"🚨 NEW PROP BET: {bet_data['question']} 🚨 "
            for key, data in bet_data["options"].items(): announcement += f"| Type '!bet {key} [amount]' for {data['text']} (Pays {data['odds']}x) "
            await ctx.send(announcement)
            self.log_callback("SPORTSBOOK", "New Market Opened!")

    @commands.command(name='bet')
    async def place_bet(self, ctx: commands.Context):
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
        elif result_code == "invalid": await ctx.send(f"❌ @{user}, that is not a valid option right now.")
        elif result_code == "funds": await ctx.send(f"❌ @{user}, insufficient funds! You have ${new_balance}.")

    @commands.command(name='result')
    async def resolve_bet(self, ctx: commands.Context):
        if not ctx.author.is_broadcaster: return
        parts = ctx.message.content.split()
        if len(parts) != 2: return
            
        winning_option = parts[1].lower()
        winners_count, total_paid = self.brain.resolve_bets(winning_option)
        self.update_overlay()
        
        if winners_count > 0: await ctx.send(f"🏁 Option {winning_option.upper()} wins! Paid out ${total_paid} to {winners_count} winners.")
        else: await ctx.send(f"🏁 Option {winning_option.upper()} wins! The house sweeps the board.")

    @commands.command(name='buy')
    async def store_buy(self, ctx: commands.Context):
        user = ctx.author.name.lower()
        parts = ctx.message.content.split()
        
        if len(parts) < 2:
            await ctx.send("🏪 STORE: !buy roast ($2k) | !buy persona [name] ($5k) | !buy ticket ($10k, 1-Time VIP Analysis)")
            return
            
        item = parts[1].lower()
        
        if item == "roast":
            cost = 2000
            status = self.brain.purchase_reward(user, cost, "roast", is_one_time=False)
            if status == "success":
                await ctx.send(f"🔥 @{user} bought a ROAST! The Coach is winding up...")
                self.trigger_analysis(user_question="Forget the nice advice. Roast my current gameplay or screen setup absolutely flawlessly. Be brutal but funny.")
            elif status == "funds": await ctx.send(f"❌ @{user}, you need ${cost} for a roast!")
                
        elif item == "persona":
            if len(parts) < 3:
                await ctx.send("⚠️ Format: !buy persona [Character Name]")
                return
            cost = 5000
            new_persona = " ".join(parts[2:])
            status = self.brain.purchase_reward(user, cost, "persona", is_one_time=False)
            if status == "success":
                self.current_persona = new_persona
                self.update_overlay()
                await ctx.send(f"🎭 @{user} hijacked the Coach! Persona is now: {new_persona}!")
                self.log_callback("STORE", f"Persona hijacked to: {new_persona}")
            elif status == "funds": await ctx.send(f"❌ @{user}, you need ${cost} to hijack the persona!")
                
        elif item == "ticket":
            cost = 10000
            status = self.brain.purchase_reward(user, cost, "ticket", is_one_time=True)
            if status == "success":
                await ctx.send(f"🎟️ VIP UNLOCKED! @{user} bought the 1-Time Ticket Analysis! Please post your parlay/ticket link in chat for the Coach to review live!")
                self.log_callback("STORE", f"🚨 VIP TICKET CLAIMED BY {user}!")
            elif status == "funds": await ctx.send(f"❌ @{user}, you need ${cost} for the VIP Ticket Analysis!")
            elif status == "claimed": await ctx.send(f"🛑 @{user}, you have ALREADY claimed your one-time VIP Ticket Analysis!")
        else:
            await ctx.send(f"❌ @{user}, unknown item. Type !buy to see the store.")
