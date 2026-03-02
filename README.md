# 🎰 BMG's Virtual Vegas (Game-Coach AI)
**An interactive, Edge-to-Cloud AI broadcast booth and automated sportsbook for Twitch.**

Welcome to the official repository for **Virtual Vegas**, developed by BlindMan Gaming LLC. 

Streaming sports games like Madden or NBA 2K shouldn't just be about watching someone play a video game. It should feel like a prime-time television broadcast. Virtual Vegas acts as an entirely automated production crew that watches your gameplay in real-time, dynamically reacts to it, and creates a thriving, high-stakes stream economy where the chat is invested in every single play.



## 👁️ The Architecture: Edge-to-Cloud "Dashcam" Tripwires
We believe that **Text is Cheap, but Vision is Expensive.** Cloud LLMs are powerful, but pinging them constantly during a live stream will burn through API tokens and get you rate-limited instantly. 

To solve this, Virtual Vegas utilizes a **Local Dashcam Buffer**.
1. **The Edge:** The bot uses local OpenCV and Tesseract OCR to slice the video feed, and a local Vosk audio model to listen to the game's announcers for free. It holds the last 3 seconds of gameplay in a local RAM buffer (like a dashcam).
2. **The Tripwires:** When the local system sees or hears a trigger word (e.g., *"Intercepted!"*, *"Touchdown"*, or a flashing penalty flag), it hits the alarm.
3. **The Cloud Strike:** The bot reaches into its memory buffer, pulls the exact frame from 1.5 seconds ago, and fires it to Google's Gemini 2.5 Flash API for advanced analysis, payout resolutions, and commentary.

## ✨ The Core Features

* 🎙️ **The Tandem Broadcast Booth:** The AI splits its brain into two roles. It acts as a cutthroat tactical coach tracking opponent tendencies, and a hype-man Color Commentator dropping live reactions directly into your Twitch chat.
* 🎲 **The AI Sportsbook:** Turns the Twitch chat into a live casino. The AI Oddsmaker generates context-aware prop bets based on the current game clock and score. The *AI Referee* automatically pays out the winners when it detects the play has resolved.
* 💸 **Automated Stream Economy:** Viewers automatically earn a "Virtual Vegas Payout" every 15 minutes just for actively watching and chatting. 
* 🎬 **Auto-Highlight Reel:** When the AI detects a massive momentum shift, it automatically triggers the Twitch API to drop a Stream Marker and create a public clip, completely automating the streamer's video editing pipeline.
* 🕹️ **Modular OBS Overlays:** A built-in local web server hosts a dynamic 3-piece HTML widget system (Left Film Room, Right Sportsbook, Bottom Ticker) that updates live in OBS.
* 🔴 **Auto-Pokémon Catcher:** Automatically detects wild Pokémon in the Twitch Chat Community Game, throws Pokéballs, and buys more when you run out.

*(A full technical installation and configuration guide will be added in a future update).*

