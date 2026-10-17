# 🥗 FitSync AI — "Your Lifestyle. Your Fitness Plan."

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Framework-Flask-black?logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Database](https://img.shields.io/badge/Database-SQLite%20/%20SQLAlchemy-003B57?logo=sqlite&logoColor=white)](https://www.sqlalchemy.org)
[![Computer Vision](https://img.shields.io/badge/AI-OpenCV%20/%20Pose%20Estimation-5C3EE8?logo=opencv&logoColor=white)](https://opencv.org)
[![Tailwind CSS](https://img.shields.io/badge/UI-Tailwind%20CSS-06B6D4?logo=tailwind-css&logoColor=white)](https://tailwindcss.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**FitSync AI** is an intelligent, adaptive fitness and nutritional planning platform designed specifically around the daily realities, budget constraints, and dining halls of collegiate students. 

Unlike conventional fitness apps that deliver static templates, FitSync AI continuously mutates each student's weekly exercise schedule and meal plan based on hostel grocery budgets, dining hall food availability, exam schedules, and equipment accessibility.

---

## 💡 The Core Innovation

> *"Unlike generic fitness applications that mandate expensive gym memberships and rigid diets, FitSync AI personalizes routines based on hostel constraints: swap expensive proteins for local Indian staples, shift missed workouts around exams without guilt, and verify exercise biomechanics directly via your browser webcam."*

---

## 🌟 Key Adaptive Features

### 🏋️ Context & Equipment-Aware Workout Engine
* **Dynamic Constraint Scaling**: Switch instantly between "Full Gym", "Dumbbells Only", and "Hostel Room / Bodyweight Only". The engine immediately regenerates workouts using available resistance.
* **Smart Exam & Missed Day Shifting**: Missed a workout due to exams or labs? The **Rebuild Remaining Week** algorithm automatically rolls pending sets into upcoming rest days without causing muscular overload.
* **Biomechanics Guides**: Step-by-step kinetic movement breakdowns and rep tempos for 24+ foundational exercises.

### 🍱 Hostel & Indian Budget-Friendly Nutrition
* **Affordable Protein Swaps**: Designed around real Indian college food staples. If eggs or paneer are unavailable or over budget, tap **Swap** to replace them with macro-equivalent alternatives (e.g. roasted chana, sattu, curd, or lentils).
* **Macro & Micronutrient Split**: Automatic calorie and macronutrient breakdown calculated from your basal metabolic rate (BMR) and activity level.
* **Portion Estimator**: Practical measurement guides (katori, spoons, glasses) suited for hostel messes.

### 👁️ AI Computer Vision Pose Checker
* **Zero-Latency In-Browser Vision**: Real-time joint angle calculation for squats, push-ups, and bicep curls via webcam.
* **100% Privacy-Preserving**: Video stream frames are processed purely client-side; zero video or photo data is ever transmitted or stored on servers.
* **Virtual Simulator Fallback**: Built-in test simulator mode for development or environments without camera access.

---

## 🏛️ System Architecture

```
┌────────────────────────────────────────────────────────┐
│             Responsive Web Frontend                    │
│   Jinja2 Templates • Tailwind CSS • Chart.js • Lucide  │
└───────────────┬────────────────────────┬───────────────┘
                │                        │
         HTTP Form Submissions    Webcam Video Feed
                │                        │
                ▼                        ▼
┌────────────────────────────────────────────────────────┐
│                   Flask Core Engine                    │
│   • Auth & Session Manager (Flask-Login)               │
│   • Adaptive Meal Engine (Macro Swapper)               │
│   • Schedule Rebuild & Rest-Day Shifting Algorithm     │
│   • Computer Vision Pose Estimation (OpenCV / MediaPipe)
└───────────────┬────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────┐
│              SQLite & SQLAlchemy Models                │
│    Users • Workouts • Completed Logs • Nutrition Plan  │
└────────────────────────────────────────────────────────┘
```

---

## 📂 Project Structure

```
FITSYNC/
├── app.py                     # Flask application entry point, routing & DB setup
├── test_app.py                # Automated integration and unit test suite
├── requirements.txt           # Python dependencies
├── run.bat                    # One-click Windows setup & launcher script
├── data/                      # Global seed assets
│   ├── exercises.json         # 24 core resistance movements
│   └── foods.json             # 22 budget-friendly student food staples
├── templates/                 # Jinja2 HTML views
│   ├── base.html              # Shell layout with Tailwind & CDN scripts
│   ├── index.html             # High-impact landing page
│   ├── onboarding.html        # 9-step assessment wizard
│   ├── dashboard.html         # Main overview & quick actions
│   ├── today_workout.html     # Interactive checklist with timer
│   ├── workout_plan.html      # 7-day adaptive split
│   ├── form_check.html        # Real-time computer vision pose analyzer
│   ├── nutrition.html         # Daily meal plan & macro tracker
│   └── progress.html          # Weight trends & visual analytics
├── static/                    # CSS animations & client scripts
│   ├── css/style.css
│   └── js/
└── instance/                  # Local SQLite database (`fitsync.db`)
```

---

## 🚀 Getting Started

### Prerequisites
* **Python**: Version `3.10` or higher ([python.org](https://python.org))
* **Git**: Installed on your system

### One-Click Windows Launch
Simply double-click `run.bat` or run:
```cmd
run.bat
```
*This automatically sets up a Python virtual environment, installs dependencies, initializes the database, and opens your browser.*

### Manual Installation

1. **Clone the Repository**
   ```bash
   git clone https://github.com/hasitha0604-2006/FITSYNC.git
   cd FITSYNC
   ```

2. **Create and Activate Virtual Environment**
   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch Application**
   ```bash
   python app.py
   ```
   Open **`http://localhost:5000`** in your browser.

---

## 🧪 Testing

FitSync AI includes an automated test suite verifying auth flows, nutrition swaps, and workout shifting:
```bash
python -m pytest test_app.py
# or
python test_app.py
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
