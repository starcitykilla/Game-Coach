# 🎰 BMG's Virtual Vegas Software (Game-Coach)

An AI-powered stream companion built for Twitch. This software watches your live gameplay using computer vision, acts as a Tandem Broadcast Booth (offering tactical coaching to you and color commentary to your chat), and runs a fully automated virtual Vegas sportsbook for your viewers.

## ✨ Features
* **The Tandem Booth:** Uses Google's Gemini AI to simultaneously act as a cutthroat tactical coach in your ear, and a hype-man color commentator in your Twitch chat.
* **Computer Vision (Local OCR):** Slices your game feed and reads the UI locally using Tesseract OCR to save API tokens and reduce latency.
* **Live Virtual Sportsbook:** Automatically reads the game state to generate highly specific prop bets. Viewers use virtual bankrolls to bet for or against you in real-time.
* **Dynamic OBS Overlay:** A sleek, auto-updating HTML widget that displays the Coach's scouting notes, the active betting market, and a live "High Roller" leaderboard.
* **SQLite Memory:** Remembers opponents across sessions and securely tracks viewer bankrolls.

---

## 🛠️ Prerequisites & Installation

### 1. System Requirements (Tesseract OCR)
Because this bot reads your screen natively, you **must** install the Tesseract OCR engine on your computer before running the Python code.

* **Linux (Ubuntu/Debian):**
  ```bash
  sudo apt update
  sudo apt install tesseract-ocr -y
