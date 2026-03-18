import config  
import json  
import cv2  
from PIL import Image  
from google import genai  
import logging
import queue
# import numpy as np # Used in image processing

log = logging.getLogger(__name__)

class AIEngine:  
    def __init__(self, api_key=None, db_queue: queue.Queue = None):  
        self.api_key = api_key or config.GEMINI_API_KEY  
        self.ai_client = genai.Client(api_key=self.api_key)  
        self.db_queue = db_queue # Store the queue for asynchronous DB updates
  
    def _prepare_image(self, frame):  
        """
        Converts a raw OpenCV frame into a Gemini-ready PIL Image in memory.
        Refinement: Removed redundant frame.copy() if the input 'frame' 
        is already a copy or is immediately disposable.
        """
        # Ensure we are working with a clean array if the input came from a live buffer
        # In this specific case, the original code looked sound, maintaining BGR to RGB conversion
        
        # Resize to 720p for fast API uploads but high enough resolution to read text  
        # If the input frame is already close to 720p, this step can be optimized/skipped
        resized = cv2.resize(frame, (1280, 720))  
        # OpenCV uses BGR, PIL uses RGB. We must convert it so the colors aren't inverted!  
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)  
        return Image.fromarray(rgb)  
  
    def analyze(self, frame, game_type, streamer_name, gamer_tag, opponent_tag, user_question, scout_notes,  
                ocr_text, recent_chat, audio_context, encounter_count=0, death_count=0, persona_x=0.0, persona_y=0.0):  
        try:  
            # Process the image entirely in RAM - uses a clean, efficient preparation
            pil_img = self._prepare_image(frame)  
            
            # ... (rest of the prompt generation logic remains the same) ...
            prompt = f"""... Your current analysis prompt ...""" 

            response = self.ai_client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[prompt, pil_img],
            )
            
            # Assume the response is valid JSON
            ai_output = json.loads(response.text)

            # --- Delegation to DB Worker Thread (Crucial Improvement) ---
            # EXAMPLE: If the AI output contains a trigger for a fund update 
            # (e.g., a "bounty_paid" flag), it should use the queue.
            
            # This is an example of an asynchronous DB task after an AI trigger
            if self.db_queue and ai_output.get('trigger_db_update'):
                user_to_update = ai_output.get('user_id')
                new_balance = ai_output.get('new_bankroll')
                if user_to_update and new_balance is not None:
                    # Non-blocking: Puts the task on the queue and returns immediately
                    self.db_queue.put(('update_bankroll', (user_to_update, new_balance), {}))
                    log.info(f"AI triggered bankroll update for {user_to_update}. Task queued.")
            
            return ai_output # Return the immediate, non-blocking AI response

        except Exception as e:
            log.error(f"AI Analysis Error: {e}")
            return None # Handle error gracefully
