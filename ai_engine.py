import json
from PIL import Image             
from google import genai          
from google.genai import types

class AIEngine:
    """The brain that generates commentary, scouting notes, and prop bets."""
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model = 'gemini-2.5-flash'

    def _clean_json(self, text):
        return text.strip().replace('```json', '').replace('```', '').strip()

    def _safe_generate(self, prompt, image_path, temp=0.8):
        """Armored wrapper for API calls to catch dropped connections."""
        try:
            img = Image.open(image_path)
            response = self.client.models.generate_content(
                model=self.model, contents=[prompt, img], 
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=temp)
            )
            return json.loads(self._clean_json(response.text))
        except Exception as e:
            print(f"⚠️ AI STRATEGIST ERROR: {e}")
            return None

    def generate_prop_bet(self, image_path, game_type, streamer_name, gamer_tag, audio_context=""):
        prompt = f"""
        Act as a Vegas oddsmaker watching {game_type}. Coach is '{streamer_name}' ({gamer_tag}).
        Generate a prop bet for the outcome of the CURRENT DRIVE or NEXT MAJOR EVENT.
        Output JSON: {{"question": "Drive Result?", "options": {{"a": {{"text": "Touchdown", "odds": 3.5}}, "b": {{"text": "Punt", "odds": 1.5}}}} }}
        """
        return self._safe_generate(prompt, image_path, temp=0.7)

    def generate_game_props(self, image_path, game_type, streamer_name, gamer_tag):
        prompt = f"""
        Act as a Vegas oddsmaker. Generate a Pre-Game Parlay prop bet with 3 Over/Under options.
        Output JSON: {{"question": "Pre-Game Prop?", "options": {{"a": {{"text": "Over 2.5 Pass TDs", "odds": 1.9}}}} }}
        """
        return self._safe_generate(prompt, image_path, temp=0.7)

    def generate_auto_prop(self, image_path, game_type, streamer_name, gamer_tag, audio_context=""):
        prompt = f"""
        Act as a Vegas oddsmaker watching {game_type}. Generate a fast-paced micro-bet for the NEXT PLAY.
        ALWAYS output a "lock_seconds" value of 15.
        Output JSON: {{"question": "Next Play Type?", "lock_seconds": 15, "options": {{"a": {{"text": "Pass", "odds": 1.8}}, "b": {{"text": "Run", "odds": 2.1}}}} }}
        """
        return self._safe_generate(prompt, image_path, temp=0.8)

    def check_bet_resolution(self, image_path, game_type, active_bet, ocr_text=""):
        prompt = f"""
        You are a Vegas referee watching {game_type}. Active bet: "{active_bet['question']}". Options: {active_bet['options']}
        CRITICAL UI DATA: {ocr_text}. Did the play or event just conclude? If yes, resolve it immediately.
        Output JSON: {{"status": "resolved", "winning_key": "a", "reason": "brief explanation"}} OR {{"status": "pending", "winning_key": null, "reason": "still waiting"}}
        """
        return self._safe_generate(prompt, image_path, temp=0.2) # Low temp for strict referee logic

    def analyze(self, image_path, game_type, streamer_name, gamer_tag, current_opponent=None, user_question=None, scout_notes=None, ocr_text=None, recent_chat=None, audio_context=""):
        opponent_memory = f"STICKY MEMORY: Playing against '{current_opponent}'. " if current_opponent and current_opponent != "CPU" else ""
        prompt = f"""
        You are a hype Color Commentator for '{streamer_name}' ({gamer_tag}).
        TASK 1: AUTO-DETECT THE GAME. (e.g., 'Madden', 'ARPG', 'Menu/Lobby'). Return in "game_type".
        
        TASK 2: IDENTIFY OPPONENT (OCR MATCH). {opponent_memory}
        - Sports game: Read the CRITICAL UI DATA to find exact opponent Gamertag.
        - Solo/PvE game: Set "opponent_tag" to the Boss, Zone, or Objective.
        - Menu/Lobby: set opponent to 'None'.
        
        TASK 3: Generate hype "commentary" (MAX 400 CHARS) and 1 highly tactical "scouting_note" for dealing with the CURRENT opponent/boss.
        
        CRITICAL UI DATA: {ocr_text}
        AUDIO: {audio_context} | CHAT: {recent_chat} | PAST NOTES: {scout_notes}
        {"Viewer Asked: " + user_question if user_question else ""}
        
        Output JSON: {{"game_type": "Game", "commentary": "text", "opponent_tag": "tag/Boss", "scouting_note": "note", "highlight_play": false}}
        """
        return self._safe_generate(prompt, image_path, temp=0.8)

