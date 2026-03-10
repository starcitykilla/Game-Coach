🎰 BMG Command Center: AI Tactical Booth & Virtual Vegas
Welcome to the BMG Command Center, a fully automated, real-time AI co-host and viewer economy engine built for Twitch.
This software operates as a "Tactical Booth," watching the game screen, listening to the streamer's microphone, and interacting with Twitch chat in real-time. It features an integrated "Virtual Vegas" economy where an AI Oddsmaker generates prop bets, referees the outcomes using computer vision, and creates dynamic bounties based on the current game being played.
✨ Core Features
 * 🧠 Adaptive AI Co-Host: Powered by Google Gemini 2.5 Flash, the Coach generates live hype commentary, tactical scouting notes, and answers direct questions.
 * 📈 The Tilt Tracker (Adaptive Memory): The bot tracks in-game deaths and time-in-combat. If the streamer gets stuck, the AI dynamically shifts its personality from "Hype Man" to a strict "Drill Sergeant" offering tough love.
 * 👁️ Computer Vision Visor: Reads the screen in real-time. Uses OpenCV Otsu's Thresholding and a 300% magnification filter to strip away dark ARPG backgrounds, pulling perfect game lore directly from on-screen subtitles (Lore Override Protocol).
 * 🎙️ Two-Way Audio Comm-Link: * Ears: Uses an offline Vosk speech-to-text model with built-in digital DAW filters (Pre-Emphasis and Noise Gating) to isolate the streamer's voice from game explosions. Features a "Hey Coach" wake word.
   * Voice: Uses gTTS and pygame to dynamically speak its commentary directly onto the broadcast.
 * 💰 Virtual Vegas Economy & AI Casino: Viewers earn a passive bankroll. The AI Oddsmaker visually analyzes the game to generate micro-bets (e.g., "Next Play: Run or Pass?"), and the AI Referee visually confirms the outcome to pay out winners.
 * 🎯 Dynamic Bounty Board: The AI scans the current game and invents highly specific, interactive bounties. Viewers use their bankroll to buy these bounties via Twitch chat (e.g., !bounty blitz or !bounty heal).
 * 📡 Diagnostic UI: A custom-built dashboard to monitor real-time AI inputs, audio transcripts, and OCR reads to ensure maximum broadcast stability.
🛠️ Technology Stack
 * Core Engine: Python 3
 * GUI / Dashboard: CustomTkinter
 * Vision & OCR: OpenCV (cv2), PyTesseract (Multithreaded)
 * Audio Processing: Vosk (Offline STT), PyAudio, NumPy (Audio Filtering)
 * Text-to-Speech: gTTS (Google TTS), Pygame (Audio Mixer)
 * AI Brain: google-genai (Gemini 2.5 Flash API)
 * Twitch Integration: TwitchIO
 * Database & Economy: Supabase (Cloud Storage), SQLite3 (Fast local edge-caching)
📂 Modular Architecture
The Command Center is broken down into isolated engines for maximum stability and easy debugging:
 * main.py - The central dashboard and UI launcher.
 * bot.py - The Twitch connection, chat loop, and central nervous system.
 * ai_engine.py - The Strategist. Handles Gemini prompts, dynamic bounties, and tilt tracking.
 * vision_engine.py - The Eyes. Manages camera buffers, OpenCV contrast filtering, and OCR zones.
 * audio_engine.py - The Ears. Filters background noise and transcribes local audio in real-time.
 * voice_engine.py - The Vocal Cords. Generates the live TTS audio files and plays them on stream.
 * db_engine.py - The Ledger. Connects to Supabase to manage the Virtual Vegas economy and scouting notes.
 * ai_input.py - The Diagnostic Monitor for real-time data flow visualization.
 * config.py - API keys, channel names, and global tuning variables.
🚀 Quick Start / Setup
 * Clone the repository.
 * Install the required dependencies:
   pip install customtkinter opencv-python pytesseract google-genai twitchio supabase vosk pyaudio numpy gTTS pygame Pillow

 * Ensure Tesseract-OCR is installed on your OS (sudo apt install tesseract-ocr for Ubuntu).
 * Update config.py with your Twitch OAuth token, Supabase URLs, and Gemini API keys.
 * Run the Command Center:
   python3 main.py

Built by BlindMan Gaming LLC (BMG).
That README is going to look incredibly clean on your repo.
Once you get that pushed up on your break and tested at the rig later, do you want to start building out the custom HTML/Browser Source overlays for OBS so the stream actually sees a giant popup when someone buys a bounty?
