# 🎰 BMG's Virtual Vegas (Game-Coach AI)
**An interactive, AI-driven broadcast booth and automated sportsbook for Twitch.**

Welcome to the official repository for **Virtual Vegas**, developed by BlindMan Gaming LLC. 

Streaming sports games like Madden or NBA 2K shouldn't just be about watching someone play a video game. It should feel like a prime-time television broadcast. Our vision is to bridge the gap between the streamer and the audience, turning passive viewers into heavily invested participants using cutting-edge, real-time AI.



## 👁️ The Vision
We are building a future where solo content creators can have the production value of a 10-person studio network. Virtual Vegas acts as an entirely automated production crew that watches your gameplay in real-time and dynamically reacts to it, creating a thriving, high-stakes stream economy where the chat is invested in every single play.

We believe that **Text is Cheap, but Vision is Expensive.** By leveraging local Computer Vision to read the game state directly from a capture card, we allow powerful cloud LLMs to process game strategy instantly and affordably.

## ✨ The Core Experience

### 🎙️ The Tandem Broadcast Booth
Why stream alone when you can have a broadcast team? This software uses Google's Gemini AI to split its brain into two distinct personalities:
1. **The Tactical Coach:** An analytical, cutthroat coach talking directly to the streamer's earpiece via Text-to-Speech, offering high-level strategy and opponent profiling based on the live scoreboard.
2. **The Color Commentator:** A hype-man living in the Twitch chat, describing the on-screen action, reacting emotionally to big plays, and directly welcoming viewers into the stream.

### 🎲 The AI Sportsbook (Virtual Vegas)
We turned the Twitch chat into a live casino. The AI acts as a Vegas Oddsmaker, reading the game clock, the score, and the field position to generate highly specific, context-aware prop bets. 
* *"Krzy Budz is down by 4 in the 4th quarter. Will he score a passing TD, rushing TD, or turn it over?"* * Viewers use a virtual bankroll to place bets in chat (`!bet a 500`), creating massive FOMO and engagement.

### 🧠 Local Computer Vision & Memory
Instead of relying entirely on heavy API calls, the bot uses local OpenCV and Tesseract OCR to slice the video feed and read the game's UI (scores, time, gamertags) at lightning speed. It also utilizes a local SQLite database to "remember" opponents across different streams, allowing the Coach to pull up past scouting notes on rival players.

---

## 🗺️ The Roadmap (What's Next)
This is just the foundation. Our development roadmap includes:
* **The Post-Game Press Conference:** AI-generated interview questions asked live to the streamer after a tough loss or big win.
* **Automated Stream Markers:** Triggering Twitch API stream markers automatically when the local OCR reads massive plays (like a Pick-Six), completely automating the highlight-reel process.
* **Audio-Scouting:** Implementing local Speech-to-Text to transcribe in-game announcers, feeding the AI a continuous play-by-play without burning a single image token.
* **Multi-Game Expansion:** Seamlessly shifting OCR zones from Madden to NBA 2K to College Football 25.

---

*A full technical user manual and installation guide will be added in a future update.*
