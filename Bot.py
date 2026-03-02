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
import aiohttp
from twitchio.ext import commands
import config
from engines import ScoutBrain, AudioEngine, VisionEngine, AIEngine

class CommanderBot(commands.Bot):
    def __init__(self, log_callback):
        super().__init__(token=config.TWITCH_TOKEN, prefix='!', initial_channels=[config.CHANNEL_NAME])
        self.log_callback = log_callback 
        
        self.brain = ScoutBrain()                                  
        self.ears = AudioEngine()          
        self.eyes = VisionEngine(camera_index=config.CAMERA_INDEX) 
        self.strategist = AIEngine(api_key=config.GEMINI_API_KEY)  
        
        self.chat_queue = queue.PriorityQueue() 
        self.running = True                     
        self.chat_enabled = True
        self.current_game = "Madden"
        
        self.streamer_name = config.STREAMER_NAME
        self.gamer_tag = config.GAMERTAG
        
        self.current_opponent = None
        self.last_chat_time = 0
        self.current_bet_display = None 
        self.recent_chat_log = [] 
        
        self.active_viewers = {}  
        self.claimed_users = set() 
        self.last_tripwire_time = 0 # Prevents API spam during a single play

        threading.Thread(target=self.start_web_server, daemon=True).start()

    def start_web_server(self):
        PORT = 8000
        Handler = http.server.SimpleHTTPRequestHandler
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            self.log_callback("SYSTEM", f"🌐 OBS Server is running on port {PORT}")
            httpd.serve_forever()

    def update_overlay(self):
        try:
            notes = self.brain.get_scout_notes(self.current_opponent) if self.current_game == "Madden" and self.current_opponent else []
            data = {
                "persona": "Tactical Booth",
                "opponent": self.current_opponent,
                "notes": notes[:3] if notes else ["No scouting data available yet."],
                "market": self.brain.current_market if self.brain.current_market else None,
                "market_display": self.current_bet_display if self.brain.current_market else None,
                "leaderboard": self.brain.get_leaderboard(5)
            }
            with open(os.path.join(os.getcwd(), "stream_data.json"), "w") as f:
                json.dump(data, f)
        except Exception as e:
            self.log_callback("ERROR", f"Overlay update failed: {e}")

    async def create_twitch_highlight(self, reason):
        token = config.TWITCH_TOKEN.replace("oauth:", "")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("[https://id.twitch.tv/oauth2/validate](https://id.twitch.tv/oauth2/validate)", headers={"Authorization": f"OAuth {token}"}) as resp:
                    val_data = await resp.json()
                    client_id = val_data.get("client_id")
                    user_id = val_data.get("user_id")
                    
                    if not client_id or not user_id:
                        self.log_callback("ERROR", "⚠️ Highlight failed: Token invalid or missing scopes.")
                        return

                helix_headers = {
                    "Authorization": f"Bearer {token}",
                    "Client-Id": client_id,
                    "Content-Type": "application/json"
                }

                marker_payload = {"user_id": user_id, "description": reason[:140]}
                async with session.post("[https://api.twitch.tv/helix/streams/markers](https://api.twitch.tv/helix/streams/markers)", headers=helix_headers, json=marker_payload) as resp:
                    if resp.status == 200:
                        self.log_callback("SYSTEM", "🔖 Stream Marker placed perfectly!")
                    else:
                        self.log_callback("ERROR", f"⚠️ Marker failed. Need 'channel:manage:broadcast' scope.")

                clip_payload = {"broadcaster_id": user_id}
                async with session.post("[https://api.twitch.tv/helix/clips](https://api.twitch.tv/helix/clips)", headers=helix_headers, json=clip_payload) as resp:
                    if resp.status == 202:
                        clip_data = await resp.json()
                        clip_id = clip_data["data"][0]["id"]
                        self.log_callback("SYSTEM", f"🎬 Clip captured! ID: {clip_id}")
                        channel = self.get_channel(config.CHANNEL_NAME)
                        if channel: 
                            await channel.send(f"🎬 The Booth caught that on tape! [https://clips.twitch.tv/](https://clips.twitch.tv/){clip_id}")
                    else:
                        self.log_callback("ERROR", f"⚠️ Clip failed. Need 'clips:edit' scope.")
        except Exception as e:
             self.log_callback("ERROR", f"⚠️ Highlight API Error: {e}")

    async def event_ready(self):
        self.log_callback("SYSTEM", f"✅ Online as {self.nick}")
        self.update_overlay()
        threading.Thread(target=self.game_loop, daemon=True).start()
        asyncio.create_task(self.chat_dispatcher())
        asyncio.create_task(self.auto_sportsbook_loop())
        asyncio.create_task(self.watcher_payout_loop())
        asyncio.create_task(self.edge_tripwire_loop())

    async def edge_tripwire_loop(self):
        """Spins every 1 second locally. Only calls the AI if a tripwire is hit."""
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            await asyncio.sleep(1) 
            
            now = time.time()
            if now - self.last_tripwire_time < 20: 
                continue 
                
            if not self.eyes or not self.ears: continue

            audio_text = self.ears.get_transcript().lower()
            ocr_text = self.eyes.read_screen_text() or ""

            tripwire_words = ["touchdown", "intercept", "fumble", "sacked", "it's good", "final score", "flag", "turnover"]
            triggered = any(word in audio_text for word in tripwire_words) or any(word in ocr_text.lower() for word in tripwire_words)

            if triggered:
                self.last_tripwire_time = now
                self.log_callback("TRIPWIRE", "🚨 Edge Tripwire Triggered! Pulling dashcam footage...")
                
                frame = self.eyes.get_buffered_frame(45)
                if frame is None: continue
                cv2.imwrite("temp_tripwire.jpg", cv2.resize(frame, (640, 360)))

                if self.current_bet_display:
                    result = await asyncio.to_thread(self.strategist.check_bet_resolution, "temp_tripwire.jpg", self.current_game, self.current_bet_display, ocr_text)
                    if result and result.get("status") == "resolved" and result.get("winning_key"):
                        win_key = result["winning_key"].lower()
                        winners, payout = self.brain.resolve_bets(win_key)
                        self.current_bet_display = None
                        self.update_overlay()
                        if channel: 
                            if winners > 0: await channel.send(f"🏁 AI REFEREE: Option {win_key.upper()} wins! Paid out ${payout} to {winners} viewers.")
                            else: await channel.send(f"🏁 AI REFEREE: Option {win_key.upper()} wins! The house sweeps.")

                threading.Thread(target=self._run_tripwire_analysis, args=(ocr_text, audio_text), daemon=True).start()

    def _run_tripwire_analysis(self, ocr_text, audio_text):
        chat_string = "\n".join(self.recent_chat_log)
        notes = self.brain.get_scout_notes(self.current_opponent) if self.current_game == "Madden" and self.current_opponent else None
        
        data = self.strategist.analyze("temp_tripwire.jpg", self.current_game, self.streamer_name, self.gamer_tag, None, notes, ocr_text, chat_string, audio_text)
        
        if data:
            if data.get("highlight_play") == True:
                note = data.get("scouting_note", "Massive play detected by Edge Tripwire!")
                asyncio.run_coroutine_threadsafe(self.create_twitch_highlight(note), self.loop)
                
            if "commentary" in data:
                self.chat_queue.put((time.time() + config.STREAM_DELAY, data['commentary']))

    async def watcher_payout_loop(self):
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            await asyncio.sleep(900) 
            now = time.time()
            payout_amount = 100
            paid_count = 0
            
            for user, last_seen in list(self.active_viewers.items()):
                if now - last_seen < 1800: 
                    self.brain.add_funds(user, payout_amount)
                    paid_count += 1
                else:
                    del self.active_viewers[user]
            
            if paid_count > 0 and channel:
                await channel.send(f"💸 VIRTUAL VEGAS PAYOUT: Dropped ${payout_amount} into the accounts of {paid_count} active viewers! Keep watching and chatting to earn more.")
                self.log_callback("ECONOMY", f"Paid ${payout_amount} to {paid_count} viewers.")

    async def event_message(self, message):
        if message.echo: return 

        author = message.author.name.lower() if message.author else ""
        msg_text = message.content.lower()

        if author == "pokemoncommunitygame":
            if "a wild" in msg_text and "appears" in msg_text:
                self.log_callback("POKEMON", "🚨 Wild Pokemon spotted! Winding up throw...")
                await asyncio.sleep(2.5) 
                await message.channel.send("!pokecatch")
                self.log_callback("POKEMON", "🔴 Threw a Pokeball!")
            
            elif f"@{self.nick.lower()}" in msg_text and ("don't have" in msg_text or "0x" in msg_text or "don't own" in msg_text):
                self.log_callback("POKEMON", "🛒 Out of balls! Auto-buying 10 Pokeballs...")
                await message.channel.send("!shop buy pokeball 10")
                await asyncio.sleep(2.0)
                await message.channel.send("!pokecatch") 
                self.log_callback("POKEMON", "🔴 Restocked and threw a Pokeball!")

        if hasattr(config, 'BLACKLISTED_USERS') and author in config.BLACKLISTED_USERS:
            return

        if author: self.active_viewers[author] = time.time() 

        self.recent_chat_log.append(f"{author}: {msg_text}")
        if len(self.recent_chat_log) > 5: self.recent_chat_log.pop(0) 

        reward_id = message.tags.get('custom-reward-id') if message.tags else None
        VIP_REWARD_ID = "YOUR-SECRET-ID-HERE" 
        
        if reward_id == VIP_REWARD_ID:
            question_text = msg_text.strip(" ,?:")
            if question_text:
                self.log_callback("CHAT_Q", f"💎 VIP @{author} asks: {question_text}")
                formatted_question = f"Twitch VIP @{author} asks: '{question_text}'"
                threading.Thread(target=self.trigger_analysis, kwargs={'user_question': formatted_question}, daemon=True).start()

        await self.handle_commands(message)

    async def chat_dispatcher(self):
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
        channel = self.get_channel(config.CHANNEL_NAME)
        while self.running:
            await asyncio.sleep(600) 
            if not self.eyes: continue
            frame = self.eyes.get_frame()
            if frame is None: continue

            cv2.imwrite("temp_auto_bet.jpg", cv2.resize(frame, (640, 360)))
            self.log_callback("SPORTSBOOK", "Auto-Bookie is waking up...")

            audio_transcript = self.ears.get_transcript()
            bet_data = await asyncio.to_thread(self.strategist.generate_auto_prop, "temp_auto_bet.jpg", self.current_game, self.streamer_name, self.gamer_tag, audio_transcript)
            
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
        if not self.eyes: return
        frame = self.eyes.get_frame()
        if frame is None: return

        cv2.imwrite("temp_frame.jpg", cv2.resize(frame, (640, 360)))
        
        if user_question: self.log_callback("AI", f"🧠 Answering VIP Question...")
        else: self.log_callback("AI", f"🧠 The Booth is analyzing the field...")

        ocr_text = self.eyes.read_screen_text()
        audio_transcript = self.ears.get_transcript() 
        notes = self.brain.get_scout_notes(self.current_opponent) if self.current_game == "Madden" and self.current_opponent else None
        chat_string = "\n".join(self.recent_chat_log)
        
        data = self.strategist.analyze("temp_frame.jpg", self.current_game, self.streamer_name, self.gamer_tag, user_question, notes, ocr_text, chat_string, audio_transcript)
        
        if data:
            if "opponent_tag" in data and data["opponent_tag"]:
                cleaned_tag = str(data["opponent_tag"]).strip()
                if cleaned_tag.lower() not in ["unknown", "none", "n/a", "null", ""]:
                    if self.current_opponent != cleaned_tag:
                        self.current_opponent = cleaned_tag
                        self.log_callback("SYSTEM", f"🎯 Target locked: {self.current_opponent}")
                        self.update_overlay()
            
            if "scouting_note" in data and self.current_game == "Madden" and self.current_opponent:
                cleaned_note = str(data["scouting_note"]).strip()
                if cleaned_note.lower() not in ["unknown", "none", "n/a", "null", ""]:
                    self.brain.add_scout_note(self.current_opponent, cleaned_note)
                    self.update_overlay() 

            if data.get("highlight_play") == True:
                note = data.get("scouting_note", "Massive play detected by AI!")
                asyncio.run_coroutine_threadsafe(self.create_twitch_highlight(note), self.loop)
            
            if "commentary" in data:
                now = time.time()
                if user_question or (now - self.last_chat_time > config.CHAT_COOLDOWN):
                    post_time = time.time() + (0 if user_question else config.STREAM_DELAY)
                    self.chat_queue.put((post_time, data['commentary']))
                    if not user_question: self.last_chat_time = now
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

    # --- TWITCH COMMANDS ---
    @commands.command(name='claim')
    async def claim_bonus(self, ctx: commands.Context):
        user = ctx.author.name.lower()
        if user in self.claimed_users:
            await ctx.send(f"🛑 @{user}, you already claimed your bonus this stream! Keep watching to earn passive payouts every 15 minutes.")
            return
        self.brain.add_funds(user, 500)
        self.claimed_users.add(user)
        await ctx.send(f"🎁 @{user} claimed their $500 starting bonus! Type '!bankroll' to check your balance, and '!bet' to play the sportsbook.")

    @commands.command(name='bankroll')
    async def check_bankroll(self, ctx: commands.Context):
        user = ctx.author.name.lower()
        balance = self.brain.get_bankroll(user)
        await ctx.send(f"💰 @{user}, you have ${balance}.")
        
    @commands.command(name='leaderboard')
    async def show_leaderboard(self, ctx: commands.Context):
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
        if not ctx.author.is_broadcaster: return
        if not self.eyes: return
        frame = self.eyes.get_frame()
        if frame is None: return
        cv2.imwrite("temp_bet.jpg", cv2.resize(frame, (640, 360)))
        self.log_callback("SPORTSBOOK", "🎲 Manual trigger! Oddsmaker analyzing...")
        threading.Thread(target=self._run_manual_oddsmaker_thread, daemon=True).start()

    def _run_manual_oddsmaker_thread(self):
        audio_transcript = self.ears.get_transcript()
        bet_data = self.strategist.generate_prop_bet("temp_bet.jpg", self.current_game, self.streamer_name, self.gamer_tag, audio_transcript)
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
        if not ctx.author.is_broadcaster: return
        self.brain.lock_market()
        await ctx.send("🔒 THE SPORTSBOOK IS NOW LOCKED! No more bets can be placed.")
        self.log_callback("SPORTSBOOK", "Market Locked!")

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
        elif result_code == "locked": await ctx.send(f"🛑 @{user}, too late! The market is locked.")
        elif result_code == "invalid": await ctx.send(f"❌ @{user}, that is not a valid option.")
        elif result_code == "funds": await ctx.send(f"❌ @{user}, insufficient funds! You have ${new_balance}.")

    @commands.command(name='result')
    async def resolve_bet(self, ctx: commands.Context):
        if not ctx.author.is_broadcaster: return
        parts = ctx.message.content.split()
        if len(parts) != 2: return
        winning_option = parts[1].lower()
        winners_count, total_paid = self.brain.resolve_bets(winning_option)
        self.current_bet_display = None
        self.update_overlay()
        if winners_count > 0: await ctx.send(f"🏁 Option {winning_option.upper()} wins! Paid out ${total_paid} to {winners_count} winners.")
        else: await ctx.send(f"🏁 Option {winning_option.upper()} wins! The house sweeps the board.")
        
    @commands.command(name='purgeuser')
    async def purge_user(self, ctx: commands.Context):
        if not ctx.author.is_broadcaster: return
        parts = ctx.message.content.split()
        if len(parts) != 2: return
            
        target = parts[1].lower()
        self.brain.cursor.execute("DELETE FROM viewers WHERE username = ?", (target,))
        self.brain.conn.commit()
        if target in self.active_viewers: del self.active_viewers[target]
        if target in self.claimed_users: self.claimed_users.remove(target)
            
        self.update_overlay()
        await ctx.send(f"🧹 BMG ADMIN: Purged @{target} from the Virtual Vegas database.")
        self.log_callback("SYSTEM", f"Purged {target} from DB.")
