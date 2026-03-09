import sqlite3
import threading
import os
from supabase import create_client, Client
import config

class ScoutBrain:
    """Manages the Virtual Vegas economy and stores AI scouting reports."""
    def __init__(self, db_name="scout.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        # Local SQLite tables for lightning-fast active bet processing
        self.cursor.execute("CREATE TABLE IF NOT EXISTS active_bets (username TEXT PRIMARY KEY, prediction TEXT, amount INTEGER, multiplier REAL)")
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS bet_history
                               (id INTEGER PRIMARY KEY AUTOINCREMENT, market_question TEXT, winning_option TEXT, 
                               total_payout INTEGER, resolution_frame TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        self.conn.commit()

        self.supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        
        # High-Speed Memory Caches to prevent stream lag during network calls
        self.bankroll_cache = {}     
        self.scout_cache = {}        
        
        # Market State
        self.current_market = {}     
        self.current_question = ""   
        self.market_locked = False   

    def get_bankroll(self, username):
        """Fetches viewer balance, preferring the fast local cache."""
        if username in self.bankroll_cache:
            return self.bankroll_cache[username]
            
        try: # Armored read to prevent Cloudflare/Network crashes
            res = self.supabase.table('viewers').select('bankroll').eq('username', username).execute()
            balance = res.data[0]['bankroll'] if res.data else 1000
            if not res.data:
                self.supabase.table('viewers').insert({'username': username, 'bankroll': balance}).execute()
        except Exception as e:
            print(f"⚠️ DB READ ERROR (Bankroll): {e}")
            balance = 1000 
            
        self.bankroll_cache[username] = balance
        return balance

    def add_funds(self, username, amount):
        """Instantly updates local memory, pushes to cloud in background."""
        new_balance = self.get_bankroll(username) + amount
        self.bankroll_cache[username] = new_balance
        threading.Thread(target=self._background_supabase_update, args=(username, new_balance), daemon=True).start()

    def _background_supabase_update(self, username, new_balance):
        try:
            self.supabase.table('viewers').update({'bankroll': new_balance}).eq('username', username).execute()
        except Exception as e:
            print(f"⚠️ DB SYNC ERROR for {username}: {e}")

    def get_leaderboard(self, limit=5):
        try:
            res = self.supabase.table('viewers').select('username, bankroll').order('bankroll', desc=True).limit(limit).execute()
            return [(row['username'], row['bankroll']) for row in res.data]
        except Exception as e:
            print(f"⚠️ DB READ ERROR (Leaderboard): {e}")
            return [] 

    def open_market(self, options_dict, question_text="Unknown Market"):
        self.current_market, self.current_question, self.market_locked = options_dict, question_text, False
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
        self.add_funds(username, -amount)
        
        self.cursor.execute("INSERT OR REPLACE INTO active_bets (username, prediction, amount, multiplier) VALUES (?, ?, ?, ?)", 
                            (username, prediction, amount, multiplier))
        self.conn.commit()
        return True, self.bankroll_cache[username], multiplier

    def resolve_bets(self, winning_prediction, frame_path=None):
        """Pays out winners and cleans up local database memory."""
        self.cursor.execute("DELETE FROM bet_history WHERE timestamp <= date('now', '-30 day')")
        if winning_prediction not in self.current_market: return 0, 0

        self.cursor.execute("SELECT username, amount, multiplier FROM active_bets WHERE prediction = ?", (winning_prediction,))
        winners = self.cursor.fetchall()

        total_paid = sum(int(amt * mult) for _, amt, mult in winners)
        for user, amt, mult in winners:
            self.add_funds(user, int(amt * mult)) 

        self.cursor.execute("INSERT INTO bet_history (market_question, winning_option, total_payout, resolution_frame) VALUES (?, ?, ?, ?)",
                            (self.current_question, winning_prediction, total_paid, frame_path))
        self.cursor.execute("DELETE FROM active_bets")
        self.current_market, self.current_question = {}, ""
        self.conn.commit()
        return len(winners), total_paid

    def get_scout_notes(self, opponent_tag, game_title=None):
        """Pulls tactical advice for the current opponent/boss."""
        if not opponent_tag: return []
        cache_key = f"{game_title}_{opponent_tag}"
        if cache_key not in self.scout_cache:
            try:
                res = self.supabase.table('scouting_reports').select('note').eq('opponent_tag', opponent_tag).order('created_at', desc=True).limit(5).execute()
                self.scout_cache[cache_key] = [row['note'] for row in res.data]
            except Exception as e:
                print(f"⚠️ DB READ ERROR (Scout Notes): {e}")
                return [] 
        return self.scout_cache[cache_key]

    def add_scout_note(self, opponent_tag, game_title, note):
        if not opponent_tag: return
        try:
            self.supabase.table('scouting_reports').insert({'opponent_tag': opponent_tag, 'game_title': game_title, 'note': note, 'author': 'AI_Booth'}).execute()
        except Exception as e:
            print(f"⚠️ DB SCOUTING ERROR: {e}")

        cache_key = f"{game_title}_{opponent_tag}"
        if cache_key not in self.scout_cache: self.scout_cache[cache_key] = []
        self.scout_cache[cache_key].insert(0, note)
        self.scout_cache[cache_key] = self.scout_cache[cache_key][:5]
