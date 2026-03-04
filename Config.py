# config_template.py
# IMPORTANT: Rename this file to config.py on your local machine before running.
# NEVER upload your real config.py with your actual API keys to GitHub!

# --- API KEYS ---
TWITCH_TOKEN = "oauth:your_twitch_oauth_token_here" 
GEMINI_API_KEY = "your_google_gemini_api_key_here"  

# --- SUPABASE CLOUD VAULT ---
SUPABASE_URL = "https://your-project-url.supabase.co"
SUPABASE_KEY = "your_anon_public_key_here"
 

# --- STREAM IDENTITY ---
CHANNEL_NAME = "your_twitch_channel_here"      # Your Twitch channel name (lowercase)
STREAMER_NAME = "Your Spoken Name Here"        # Your spoken name for the AI coach
GAMERTAG = "Your_In_Game_Gamertag_Here"        # Exactly how it appears on the game scoreboard

# --- HARDWARE ---
# 0 is usually your laptop webcam. 1, 2, or 3 will be your Capture Card or OBS Virtual Camera.
CAMERA_INDEX = 0 

# --- BOT BEHAVIOR ---
ANALYSIS_INTERVAL = 45 # How often the bot scans the screen (in seconds)
STREAM_DELAY = 2       # Delay chat messages to match stream latency
CHAT_COOLDOWN = 60     # Prevent the AI from spamming chat too frequently

# --- SUPPORTED GAMES ---
# The dropdown list for the Command Center GUI
GAMES_ROSTER = ["Madden", "NBA 2K", "College Football 25"]
