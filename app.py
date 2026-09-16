import os
import sys
import json
import time
import threading
import webbrowser

# Reconfigure Windows console output to UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, create_engine
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables from .env
load_dotenv()

# Alias __main__ to 'app' in sys.modules to prevent dual SQLAlchemy instances on 'from app import db'
if __name__ == "__main__":
    sys.modules['app'] = sys.modules[__name__]

# Path Safety
BASE_DIR = Path(__file__).resolve().parent
if os.getenv("VERCEL"):
    INSTANCE_DIR = Path("/tmp/instance")
else:
    INSTANCE_DIR = BASE_DIR / "instance"

try:
    INSTANCE_DIR.mkdir(exist_ok=True)
except Exception:
    INSTANCE_DIR = Path("/tmp/instance")
    INSTANCE_DIR.mkdir(exist_ok=True)

DB_PATH = (INSTANCE_DIR / "fitsync.db").resolve()

app = Flask(__name__, instance_path=str(INSTANCE_DIR))
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fitsync_super_secret_production_key_2026')

def get_effective_database_uri():
    raw_url = os.getenv('DATABASE_URL')
    if not raw_url or not raw_url.strip():
        return f"sqlite:///{DB_PATH.as_posix()}"
    
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+pg8000://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+pg8000://", 1)

    # Automatically transform direct Supabase IPv6 host (db.<ref>.supabase.co:5432) to IPv4 pooler
    if ".supabase.co" in url and "db." in url:
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            parts = hostname.split(".")
            if len(parts) >= 3 and parts[0] == "db" and parts[2] == "supabase":
                project_ref = parts[1]
                pooler_host = "aws-0-ap-south-1.pooler.supabase.com"
                pooler_port = 6543
                user = parsed.username or "postgres"
                if not user.endswith(f".{project_ref}"):
                    user = f"postgres.{project_ref}"
                pwd = f":{parsed.password}" if parsed.password else ""
                new_netloc = f"{user}{pwd}@{pooler_host}:{pooler_port}"
                url = urlunparse((parsed.scheme, new_netloc, parsed.path or "/postgres", parsed.params, parsed.query, parsed.fragment))
                print(f"[DB] Auto-converted Supabase URL to IPv4 pooler: {pooler_host}:{pooler_port}")
        except Exception as e:
            print(f"[DB WARNING] Failed to auto-route Supabase pooler: {e}")

    return url

app.config['SQLALCHEMY_DATABASE_URI'] = get_effective_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

db = SQLAlchemy(app)

def print_db_debug_info():
    try:
        inspector = db.inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        users_exists = "users" in existing_tables
        total_tables = len(existing_tables)
    except Exception:
        users_exists = False
        total_tables = 0

    print("[DB DEBUG]")
    print(f"Application directory: {BASE_DIR}")
    print(f"Working directory: {Path.cwd().resolve()}")
    print(f"Configured database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"Resolved database file: {DB_PATH}")
    print(f"Database exists: {'YES' if DB_PATH.exists() else 'NO'}")
    print(f"Database file size: {DB_PATH.stat().st_size if DB_PATH.exists() else 0}")
    print(f"Users table exists: {'YES' if users_exists else 'NO'}")
    print(f"Total tables: {total_tables}")

def normalize_email(email_str):
    if not email_str:
        return ""
    return str(email_str).strip().lower()

# -----------------------------------------------------------------------------
# DATABASE MODELS
# -----------------------------------------------------------------------------

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    profile = db.relationship("UserProfile", backref="user", uselist=False, cascade="all, delete-orphan")
    equipments = db.relationship("UserEquipment", backref="user", cascade="all, delete-orphan")
    food_preferences = db.relationship("UserFoodPreference", backref="user", cascade="all, delete-orphan")
    nutrition_targets = db.relationship("NutritionTarget", backref="user", cascade="all, delete-orphan")
    workout_plans = db.relationship("WorkoutPlan", backref="user", cascade="all, delete-orphan")
    meal_plans = db.relationship("MealPlan", backref="user", cascade="all, delete-orphan")
    progress_records = db.relationship("ProgressRecord", backref="user", cascade="all, delete-orphan")
    completed_workouts = db.relationship("CompletedWorkout", backref="user", cascade="all, delete-orphan")
    custom_foods = db.relationship("CustomFood", backref="user", cascade="all, delete-orphan")
    conversations = db.relationship("ChatConversation", backref="user", cascade="all, delete-orphan")

class CustomFood(db.Model):
    __tablename__ = "custom_foods"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False, default="Homemade")
    serving_size_g = db.Column(db.Integer, nullable=False)
    calories = db.Column(db.Integer, nullable=False)
    protein = db.Column(db.Float, nullable=False)
    carbs = db.Column(db.Float, nullable=False)
    fat = db.Column(db.Float, nullable=False)
    fiber = db.Column(db.Float, default=0.0)
    cost = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class ChatConversation(db.Model):
    __tablename__ = "chat_conversations"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(120), nullable=True, default="Fitness Coaching")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    messages = db.relationship("ChatMessage", backref="conversation", cascade="all, delete-orphan", order_by="ChatMessage.id")

class ChatMessage(db.Model):
    __tablename__ = "chat_messages"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    intent = db.Column(db.String(50), nullable=True)
    extra_data_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        extra = None
        if self.extra_data_json:
            try:
                extra = json.loads(self.extra_data_json)
            except Exception:
                extra = None
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "message": self.message,
            "intent": self.intent or "GENERAL_FITNESS",
            "extra_data": extra,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else ""
        }

class Exercise(db.Model):
    __tablename__ = "exercises"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    aliases = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=False)
    primary_muscles = db.Column(db.Text, nullable=True)
    secondary_muscles = db.Column(db.Text, nullable=True)
    equipment = db.Column(db.String(100), nullable=True)
    difficulty = db.Column(db.String(50), nullable=True, default="Beginner")
    environment = db.Column(db.String(50), nullable=True, default="Gym")
    goal = db.Column(db.String(50), nullable=True, default="General Fitness")
    instructions = db.Column(db.Text, nullable=True)
    common_mistakes = db.Column(db.Text, nullable=True)
    safety_notes = db.Column(db.Text, nullable=True)
    default_sets = db.Column(db.Integer, default=3)
    default_reps_min = db.Column(db.Integer, default=8)
    default_reps_max = db.Column(db.Integer, default=12)
    default_rest_seconds = db.Column(db.Integer, default=60)
    demonstration_available = db.Column(db.Boolean, default=True)
    demonstration_asset = db.Column(db.String(255), nullable=True)
    thumbnail = db.Column(db.String(255), nullable=True)
    demo_video = db.Column(db.String(255), nullable=True)
    animation_type = db.Column(db.String(50), nullable=True, default="video")
    media_status = db.Column(db.String(50), nullable=True, default="missing")

    def to_dict(self):
        slug = self.name.lower().replace(' ', '_').replace('-', '_')
        
        # Canonical exercise-specific video paths
        video_rel = f"/static/exercise_media/{slug}.mp4"
        video_disk = BASE_DIR / "static" / "exercise_media" / f"{slug}.mp4"
        video_exists = video_disk.exists()
        
        # SVG animation paths (fallback if video not yet rendered/present)
        svg_rel = f"/static/exercises/{slug}/demo.svg"
        svg_disk = BASE_DIR / "static" / "exercises" / slug / "demo.svg"
        svg_exists = svg_disk.exists()
        
        # Determine actual media status & paths
        if video_exists:
            actual_video = video_rel
            media_type = "mp4"
            status = "available"
            media_available = True
            primary_asset = video_rel
        elif self.demo_video and os.path.exists(str(self.demo_video).lstrip('/')):
            actual_video = self.demo_video
            media_type = "mp4"
            status = "available"
            media_available = True
            primary_asset = self.demo_video
        else:
            actual_video = None
            media_type = "svg" if svg_exists else "none"
            status = "missing"
            media_available = False
            primary_asset = svg_rel if svg_exists else "/static/exercises/fallback_demo.svg"

        p_muscles = json.loads(self.primary_muscles) if self.primary_muscles and self.primary_muscles.startswith("[") else ([m.strip() for m in self.primary_muscles.split(",")] if self.primary_muscles else [self.category])
        s_muscles = json.loads(self.secondary_muscles) if self.secondary_muscles and self.secondary_muscles.startswith("[") else ([m.strip() for m in self.secondary_muscles.split(",")] if self.secondary_muscles else [])
        
        # Parse instructions list
        if self.instructions and self.instructions.startswith("["):
            try:
                inst_list = json.loads(self.instructions)
            except Exception:
                inst_list = [i.strip() for i in self.instructions.split("\n") if i.strip()]
        elif self.instructions:
            inst_list = [i.strip() for i in self.instructions.split("\n") if i.strip()]
        else:
            inst_list = []

        # Parse mistakes list
        if self.common_mistakes and self.common_mistakes.startswith("["):
            try:
                mist_list = json.loads(self.common_mistakes)
            except Exception:
                mist_list = [m.strip() for m in self.common_mistakes.split("\n") if m.strip()]
        elif self.common_mistakes:
            mist_list = [m.strip() for m in self.common_mistakes.split("\n") if m.strip()]
        else:
            mist_list = []

        thumb_path = self.thumbnail or (f"/static/exercise_media/thumbnails/{slug}.webp" if (BASE_DIR / "static" / "exercise_media" / "thumbnails" / f"{slug}.webp").exists() else primary_asset)

        return {
            "id": self.id,
            "exercise_id": self.id,
            "name": self.name,
            "aliases": json.loads(self.aliases) if self.aliases and self.aliases.startswith("[") else ([a.strip() for a in self.aliases.split(",")] if self.aliases else []),
            "category": self.category,
            "primary_muscles": p_muscles,
            "secondary_muscles": s_muscles,
            "primary_muscle": p_muscles[0] if p_muscles else self.category,
            "equipment": self.equipment or "No Equipment",
            "difficulty": self.difficulty or "Beginner",
            "environment": self.environment or "Gym",
            "goal": self.goal or "General Fitness",
            "instructions": inst_list,
            "common_mistakes": mist_list,
            "safety_notes": self.safety_notes or "Maintain controlled form throughout movement.",
            "sets": self.default_sets or 3,
            "reps": f"{self.default_reps_min or 8}-{self.default_reps_max or 12}",
            "reps_min": self.default_reps_min or 8,
            "reps_max": self.default_reps_max or 12,
            "rest_seconds": self.default_rest_seconds or 60,
            "default_sets": self.default_sets or 3,
            "default_reps": f"{self.default_reps_min or 8}-{self.default_reps_max or 12}",
            "default_rest": self.default_rest_seconds or 60,
            "demonstration_available": self.demonstration_available,
            "demonstration_asset": primary_asset,
            "demo_video": actual_video,
            "media_path": primary_asset,
            "media_type": media_type,
            "media_status": status,
            "media_available": media_available,
            "supported_demo": True,
            "thumbnail": thumb_path,
            "slug": slug,
            "start_pos": getattr(self, "start_pos", None) or "Establish solid starting posture.",
            "movement": getattr(self, "movement", None) or "Execute movement under control.",
            "end_pos": getattr(self, "end_pos", None) or "Hold contraction and return safely.",
            "working_location": getattr(self, "working_location", None) or (p_muscles[0] if p_muscles else self.category),
            "joint_action": getattr(self, "joint_action", None) or "Joint Flexion & Extension"
        }

class Food(db.Model):
    __tablename__ = "foods"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    category = db.Column(db.String(50), nullable=False)
    serving_size_g = db.Column(db.Integer, nullable=False, default=100)
    calories = db.Column(db.Integer, nullable=False)
    protein = db.Column(db.Float, nullable=False)
    carbs = db.Column(db.Float, nullable=False)
    fat = db.Column(db.Float, nullable=False)
    fiber = db.Column(db.Float, nullable=True, default=0.0)
    cost_approx = db.Column(db.Integer, nullable=True, default=0)
    common_unit = db.Column(db.String(100), nullable=True)
    is_vegetarian = db.Column(db.Boolean, default=True)
    is_vegan = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "serving_size_g": self.serving_size_g,
            "calories": self.calories,
            "protein": self.protein,
            "carbs": self.carbs,
            "fat": self.fat,
            "fiber": self.fiber or 0.0,
            "cost_approx": self.cost_approx or 0,
            "common_unit": self.common_unit or f"1 serving ({self.serving_size_g}g)",
            "is_vegetarian": self.is_vegetarian,
            "is_vegan": self.is_vegan
        }

class UserProfile(db.Model):
    __tablename__ = "user_profiles"
    id = db.Model.metadata.tables.get("user_profiles") is not None and db.Column(db.Integer, primary_key=True) or db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(20), nullable=False)
    height = db.Column(db.Float, nullable=False)  # cm
    weight = db.Column(db.Float, nullable=False)  # kg
    fitness_goal = db.Column(db.String(50), nullable=False)
    fitness_level = db.Column(db.String(50), nullable=False)
    workout_days_per_week = db.Column(db.Integer, nullable=False, default=4)
    workout_duration_mins = db.Column(db.Integer, nullable=False, default=45)
    workout_environment = db.Column(db.String(50), nullable=True, default="Gym")
    dietary_preference = db.Column(db.String(50), nullable=False)
    budget_preference = db.Column(db.String(50), nullable=True)
    daily_food_budget = db.Column(db.Integer, nullable=True, default=150)
    onboarding_completed = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class UserEquipment(db.Model):
    __tablename__ = "user_equipments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    equipment_name = db.Column(db.String(50), nullable=False)

class UserFoodPreference(db.Model):
    __tablename__ = "user_food_preferences"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    food_name = db.Column(db.String(100), nullable=False)
    is_preferred = db.Column(db.Boolean, default=True)
    is_available = db.Column(db.Boolean, default=True)
    is_avoided = db.Column(db.Boolean, default=False)

class NutritionTarget(db.Model):
    __tablename__ = "nutrition_targets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    calories = db.Column(db.Integer, nullable=False)
    protein = db.Column(db.Float, nullable=False)
    carbs = db.Column(db.Float, nullable=False)
    fat = db.Column(db.Float, nullable=False)
    is_custom = db.Column(db.Boolean, default=False)

class WorkoutPlan(db.Model):
    __tablename__ = "workout_plans"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)
    days = db.relationship("WorkoutDay", backref="plan", cascade="all, delete-orphan")

class WorkoutDay(db.Model):
    __tablename__ = "workout_days"
    id = db.Column(db.Integer, primary_key=True)
    workout_plan_id = db.Column(db.Integer, db.ForeignKey("workout_plans.id", ondelete="CASCADE"))
    day_name = db.Column(db.String(20), nullable=False)
    day_number = db.Column(db.Integer, nullable=True)
    focus = db.Column(db.String(100), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    is_rest_day = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), nullable=True, default="upcoming")  # upcoming/completed/missed/skipped/rest
    duration_minutes = db.Column(db.Integer, nullable=True, default=0)
    exercises = db.relationship("WorkoutExercise", backref="workout_day", cascade="all, delete-orphan", order_by="WorkoutExercise.order_idx")

class WorkoutExercise(db.Model):
    __tablename__ = "workout_exercises"
    id = db.Column(db.Integer, primary_key=True)
    workout_day_id = db.Column(db.Integer, db.ForeignKey("workout_days.id", ondelete="CASCADE"))
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercises.id", ondelete="SET NULL"), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    sets = db.Column(db.Integer, nullable=False)
    reps = db.Column(db.String(20), nullable=False)
    reps_min = db.Column(db.Integer, nullable=True, default=8)
    reps_max = db.Column(db.Integer, nullable=True, default=12)
    rest_seconds = db.Column(db.Integer, nullable=False)
    instructions = db.Column(db.Text, nullable=True)
    start_pos = db.Column(db.String(200), nullable=True)
    movement = db.Column(db.String(200), nullable=True)
    end_pos = db.Column(db.String(200), nullable=True)
    common_mistakes = db.Column(db.Text, nullable=True)
    is_completed = db.Column(db.Boolean, default=False)
    order_idx = db.Column(db.Integer, default=0)

    def to_dict(self):
        slug = self.name.lower().replace(' ', '_').replace('-', '_')
        master = db.session.get(Exercise, self.exercise_id) if self.exercise_id else None
        
        p_muscles = []
        s_muscles = []
        inst_data = self.instructions or ""
        mistakes_data = self.common_mistakes or ""
        
        # Canonical video paths
        video_rel = f"/static/exercise_media/{slug}.mp4"
        video_disk = BASE_DIR / "static" / "exercise_media" / f"{slug}.mp4"
        video_exists = video_disk.exists()

        svg_rel = f"/static/exercises/{slug}/demo.svg"
        svg_disk = BASE_DIR / "static" / "exercises" / slug / "demo.svg"
        svg_exists = svg_disk.exists()

        demo_video = None
        if video_exists:
            demo_video = video_rel
            primary_asset = video_rel
            media_type = "mp4"
            media_status = "available"
            media_available = True
        elif master and master.demo_video and os.path.exists(str(master.demo_video).lstrip('/')):
            demo_video = master.demo_video
            primary_asset = master.demo_video
            media_type = "mp4"
            media_status = "available"
            media_available = True
        elif svg_exists:
            primary_asset = svg_rel
            media_type = "svg"
            media_status = "missing"
            media_available = False
        else:
            primary_asset = "/static/exercises/fallback_demo.svg"
            media_type = "none"
            media_status = "missing"
            media_available = False

        equipment = "Gym"
        difficulty = "Intermediate"
        working_loc = self.category
        joint_act = "Joint Flexion & Extension"

        if master:
            master_dict = master.to_dict()
            p_muscles = master_dict.get("primary_muscles") or [self.category]
            s_muscles = master_dict.get("secondary_muscles") or []
            if not inst_data:
                inst_data = master_dict.get("instructions") or master.instructions or ""
            if not mistakes_data:
                mistakes_data = master_dict.get("common_mistakes") or master.common_mistakes or ""
            equipment = master.equipment or equipment
            difficulty = master.difficulty or difficulty
            working_loc = master_dict.get("working_location") or (p_muscles[0] if p_muscles else self.category)
            joint_act = master_dict.get("joint_action") or joint_act

        if not p_muscles:
            p_muscles = [self.category]

        # Ensure instructions is formatted cleanly as a list
        if isinstance(inst_data, list):
            inst_list = inst_data
        elif isinstance(inst_data, str) and inst_data.startswith("["):
            try:
                inst_list = json.loads(inst_data)
            except Exception:
                inst_list = [i.strip() for i in inst_data.split("\n") if i.strip()]
        elif isinstance(inst_data, str) and inst_data:
            inst_list = [i.strip() for i in inst_data.split("\n") if i.strip()]
        else:
            inst_list = []

        # Ensure mistakes is formatted cleanly as a list
        if isinstance(mistakes_data, list):
            mist_list = mistakes_data
        elif isinstance(mistakes_data, str) and mistakes_data.startswith("["):
            try:
                mist_list = json.loads(mistakes_data)
            except Exception:
                mist_list = [m.strip() for m in mistakes_data.split("\n") if m.strip()]
        elif isinstance(mistakes_data, str) and mistakes_data:
            mist_list = [m.strip() for m in mistakes_data.split("\n") if m.strip()]
        else:
            mist_list = []

        return {
            "id": self.id,
            "exercise_id": self.exercise_id,
            "name": self.name,
            "category": self.category,
            "sets": self.sets,
            "reps": self.reps,
            "reps_min": self.reps_min or 8,
            "reps_max": self.reps_max or 12,
            "rest_seconds": self.rest_seconds,
            "instructions": inst_list,
            "start_pos": self.start_pos or "Position figure in starting alignment.",
            "movement": self.movement or "Execute movement under control.",
            "end_pos": self.end_pos or "Contract target muscle group at peak.",
            "common_mistakes": mist_list,
            "is_completed": self.is_completed,
            "slug": slug,
            "equipment": equipment,
            "difficulty": difficulty,
            "demo_video": demo_video,
            "media_path": primary_asset,
            "demonstration_asset": primary_asset,
            "media_type": media_type,
            "media_status": media_status,
            "media_available": media_available,
            "primary_muscles": p_muscles,
            "secondary_muscles": s_muscles,
            "primary_muscle": p_muscles[0] if p_muscles else self.category,
            "working_location": working_loc,
            "joint_action": joint_act,
            "supported_demo": True
        }

class MealPlan(db.Model):
    __tablename__ = "meal_plans"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    date = db.Column(db.String(20), nullable=False)  # YYYY-MM-DD
    total_calories = db.Column(db.Integer, default=0)
    total_protein = db.Column(db.Float, default=0.0)
    total_carbs = db.Column(db.Float, default=0.0)
    total_fat = db.Column(db.Float, default=0.0)
    total_cost = db.Column(db.Integer, default=0)
    meals = db.relationship("Meal", backref="meal_plan", cascade="all, delete-orphan")

class Meal(db.Model):
    __tablename__ = "meals"
    id = db.Column(db.Integer, primary_key=True)
    meal_plan_id = db.Column(db.Integer, db.ForeignKey("meal_plans.id", ondelete="CASCADE"))
    meal_type = db.Column(db.String(55), nullable=False)
    food_id = db.Column(db.Integer, nullable=False)
    food_name = db.Column(db.String(100), nullable=False)
    serving_size_g = db.Column(db.Integer, nullable=False)
    calories = db.Column(db.Integer, nullable=False)
    protein = db.Column(db.Float, nullable=False)
    carbs = db.Column(db.Float, nullable=False)
    fat = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Integer, default=0)
    common_unit = db.Column(db.String(100), nullable=True)

class ProgressRecord(db.Model):
    __tablename__ = "progress_records"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    date = db.Column(db.String(20), nullable=False)
    weight = db.Column(db.Float, nullable=True)
    workouts_completed = db.Column(db.Integer, default=0)
    calories_consumed = db.Column(db.Integer, default=0)
    protein_consumed = db.Column(db.Float, default=0.0)
    carbs_consumed = db.Column(db.Float, default=0.0)
    fat_consumed = db.Column(db.Float, default=0.0)

class CompletedWorkout(db.Model):
    __tablename__ = "completed_workouts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    date = db.Column(db.String(20), nullable=False)
    workout_name = db.Column(db.String(100), nullable=False)

# -----------------------------------------------------------------------------
# ENGINE IMPORTS (services)
# -----------------------------------------------------------------------------
from services.fitness_engine import (
    generate_weekly_workout, find_alternative_exercise, switch_today_focus,
    scale_workout_duration, scale_workout_difficulty, generate_custom_today_workout,
    filter_exercises_for_focus
)
from services.nutrition_engine import (
    calculate_ai_targets, generate_daily_meals, get_food_alternative,
    swap_meal_with_chosen_food
)
from services.adaptation_engine import rebuild_remaining_week_logic, move_workout_logic, skip_workout_logic
from services.form_analysis import check_exercise_form
from services.ai_diet_engine import generate_ai_diet_plan
from services.ai_search_engine import process_ai_gym_query
from services.ai_coach_engine import process_coach_command

# Data loaders helper with in-memory caching for instantaneous response
_CACHED_EXERCISES_DATA = None
_CACHED_FOODS_DATA = None

def get_exercises_data():
    global _CACHED_EXERCISES_DATA
    if _CACHED_EXERCISES_DATA is not None:
        return _CACHED_EXERCISES_DATA
    p = BASE_DIR / "data" / "exercises.json"
    if not p.exists():
        p = Path.cwd() / "data" / "exercises.json"
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                _CACHED_EXERCISES_DATA = json.load(f)
                return _CACHED_EXERCISES_DATA
        except Exception:
            pass
    # Database fallback if file is not bundled or accessible in serverless environment
    try:
        db_exercises = Exercise.query.order_by(Exercise.id).all()
        if db_exercises:
            _CACHED_EXERCISES_DATA = [ex.to_dict() for ex in db_exercises]
            return _CACHED_EXERCISES_DATA
    except Exception:
        pass
    return []

def get_foods_data():
    global _CACHED_FOODS_DATA
    if _CACHED_FOODS_DATA is not None:
        return _CACHED_FOODS_DATA
    p = BASE_DIR / "data" / "foods.json"
    if not p.exists():
        p = Path.cwd() / "data" / "foods.json"
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                _CACHED_FOODS_DATA = json.load(f)
                return _CACHED_FOODS_DATA
        except Exception:
            pass
    # Database fallback if file is not bundled or accessible in serverless environment
    try:
        db_foods = Food.query.order_by(Food.id).all()
        if db_foods:
            _CACHED_FOODS_DATA = [fd.to_dict() for fd in db_foods]
            return _CACHED_FOODS_DATA
    except Exception:
        pass
    return []

def get_all_user_foods(user=None):
    base_foods = get_foods_data()
    if not user:
        return base_foods

    c_foods = CustomFood.query.filter_by(user_id=user.id).all()
    if not c_foods:
        return base_foods

    merged = list(base_foods)
    for cf in c_foods:
        merged.append({
            "id": 10000 + cf.id,
            "custom_food_id": cf.id,
            "name": cf.name,
            "category": cf.category or "Homemade",
            "serving_size_g": cf.serving_size_g,
            "calories": cf.calories,
            "protein": cf.protein,
            "carbs": cf.carbs,
            "fat": cf.fat,
            "fiber": cf.fiber or 0.0,
            "is_vegetarian": True,
            "is_vegan": False,
            "cost_approx": cf.cost,
            "common_unit": f"1 serving ({cf.serving_size_g}g)",
            "is_custom": True,
            "notes": cf.notes
        })
    return merged

def run_migrations():
    try:
        db.create_all()
    except Exception as create_err:
        db.session.rollback()
        print(f"[MIGRATION WARNING] db.create_all error: {create_err}")

    is_postgres = "postgres" in app.config.get('SQLALCHEMY_DATABASE_URI', '')
    bool_val = "FALSE" if is_postgres else "0"
    datetime_type = "TIMESTAMP" if is_postgres else "DATETIME"

    # 1. Add daily_food_budget to user_profiles
    try:
        db.session.execute(db.text("SELECT daily_food_budget FROM user_profiles LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding daily_food_budget to user_profiles...")
            db.session.execute(db.text("ALTER TABLE user_profiles ADD COLUMN daily_food_budget INTEGER DEFAULT 150"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 2. Add total_cost to meal_plans
    try:
        db.session.execute(db.text("SELECT total_cost FROM meal_plans LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding total_cost to meal_plans table...")
            db.session.execute(db.text("ALTER TABLE meal_plans ADD COLUMN total_cost INTEGER DEFAULT 0"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 3. Add cost to meals
    try:
        db.session.execute(db.text("SELECT cost FROM meals LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding cost to meals table...")
            db.session.execute(db.text("ALTER TABLE meals ADD COLUMN cost INTEGER DEFAULT 0"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 4. Migrate user_food_preferences table columns (is_preferred, is_available, is_avoided)
    try:
        db.session.execute(db.text("SELECT is_preferred FROM user_food_preferences LIMIT 1"))
    except Exception:
        db.session.rollback()
        print("[MIGRATION] Adding boolean preference columns to user_food_preferences...")
        try:
            db.session.execute(db.text(f"ALTER TABLE user_food_preferences ADD COLUMN is_preferred BOOLEAN DEFAULT {bool_val}"))
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text(f"ALTER TABLE user_food_preferences ADD COLUMN is_available BOOLEAN DEFAULT {bool_val}"))
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text(f"ALTER TABLE user_food_preferences ADD COLUMN is_avoided BOOLEAN DEFAULT {bool_val}"))
        except Exception:
            db.session.rollback()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 5. Add workout_environment to user_profiles
    try:
        db.session.execute(db.text("SELECT workout_environment FROM user_profiles LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding workout_environment to user_profiles...")
            db.session.execute(db.text("ALTER TABLE user_profiles ADD COLUMN workout_environment VARCHAR(50) DEFAULT 'Gym'"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 6. Add day_number to workout_days
    try:
        db.session.execute(db.text("SELECT day_number FROM workout_days LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding day_number to workout_days...")
            db.session.execute(db.text("ALTER TABLE workout_days ADD COLUMN day_number INTEGER DEFAULT 1"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 7. Add reps_min to workout_exercises
    try:
        db.session.execute(db.text("SELECT reps_min FROM workout_exercises LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding reps_min to workout_exercises...")
            db.session.execute(db.text("ALTER TABLE workout_exercises ADD COLUMN reps_min INTEGER DEFAULT 8"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 8. Add reps_max to workout_exercises
    try:
        db.session.execute(db.text("SELECT reps_max FROM workout_exercises LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding reps_max to workout_exercises...")
            db.session.execute(db.text("ALTER TABLE workout_exercises ADD COLUMN reps_max INTEGER DEFAULT 12"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 9. Add name to users
    try:
        db.session.execute(db.text("SELECT name FROM users LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding name to users...")
            db.session.execute(db.text("ALTER TABLE users ADD COLUMN name VARCHAR(100)"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 10. Add updated_at to users
    try:
        db.session.execute(db.text("SELECT updated_at FROM users LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding updated_at to users...")
            db.session.execute(db.text(f"ALTER TABLE users ADD COLUMN updated_at {datetime_type}"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 11. Add status to workout_days
    try:
        db.session.execute(db.text("SELECT status FROM workout_days LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding status to workout_days...")
            db.session.execute(db.text("ALTER TABLE workout_days ADD COLUMN status VARCHAR(20) DEFAULT 'upcoming'"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 12. Add duration_minutes to workout_days
    try:
        db.session.execute(db.text("SELECT duration_minutes FROM workout_days LIMIT 1"))
    except Exception:
        db.session.rollback()
        try:
            print("[MIGRATION] Adding duration_minutes to workout_days...")
            db.session.execute(db.text("ALTER TABLE workout_days ADD COLUMN duration_minutes INTEGER DEFAULT 0"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 13. Purge orphan records
    try:
        db.session.execute(db.text("DELETE FROM user_profiles WHERE user_id NOT IN (SELECT id FROM users)"))
        db.session.execute(db.text("DELETE FROM user_equipments WHERE user_id NOT IN (SELECT id FROM users)"))
        db.session.execute(db.text("DELETE FROM user_food_preferences WHERE user_id NOT IN (SELECT id FROM users)"))
        db.session.execute(db.text("DELETE FROM nutrition_targets WHERE user_id NOT IN (SELECT id FROM users)"))
        db.session.execute(db.text("DELETE FROM workout_plans WHERE user_id NOT IN (SELECT id FROM users)"))
        db.session.execute(db.text("DELETE FROM meal_plans WHERE user_id NOT IN (SELECT id FROM users)"))
        db.session.execute(db.text("DELETE FROM progress_records WHERE user_id NOT IN (SELECT id FROM users)"))
        db.session.execute(db.text("DELETE FROM custom_foods WHERE user_id NOT IN (SELECT id FROM users)"))
        db.session.execute(db.text("DELETE FROM chat_conversations WHERE user_id NOT IN (SELECT id FROM users)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # 14. Add demo_video, animation_type, media_status to exercises table
    try:
        db.session.execute(db.text("SELECT demo_video FROM exercises LIMIT 1"))
    except Exception:
        db.session.rollback()
        print("[MIGRATION] Adding demo_video, animation_type, media_status to exercises...")
        try:
            db.session.execute(db.text("ALTER TABLE exercises ADD COLUMN demo_video VARCHAR(255)"))
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE exercises ADD COLUMN animation_type VARCHAR(50) DEFAULT 'video'"))
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE exercises ADD COLUMN media_status VARCHAR(50) DEFAULT 'missing'"))
        except Exception:
            db.session.rollback()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def validate_media_path(path_str):
    """
    Security check: Ensures media paths are strictly confined to authorized static media directories,
    blocking directory traversal attacks (e.g. '../', '..\\', absolute system files).
    """
    if not path_str or not isinstance(path_str, str):
        return False
    cleaned = path_str.replace('\\', '/').strip()
    if '..' in cleaned or cleaned.startswith('/etc') or cleaned.startswith('C:') or cleaned.startswith('/root'):
        return False
    allowed_prefixes = (
        '/static/exercise_media/', 'static/exercise_media/',
        '/static/exercises/', 'static/exercises/'
    )
    if not any(cleaned.startswith(p) for p in allowed_prefixes):
        return False
    try:
        abs_path = (BASE_DIR / cleaned.lstrip('/')).resolve()
        static_dir = (BASE_DIR / 'static').resolve()
        return static_dir in abs_path.parents or abs_path == static_dir
    except Exception:
        return False

def seed_exercises_table():
    try:
        p = BASE_DIR / "data" / "exercises.json"
        if not p.exists():
            return
        with open(p, 'r', encoding='utf-8') as f:
            ex_list = json.load(f)

        existing_ex = {e.id: e for e in Exercise.query.all()}
        existing_names = {e.name.lower(): e for e in existing_ex.values()}

        added_count = 0
        for item in ex_list:
            ex_id = item.get("id")
            name_val = item.get("name", "").strip()
            if not name_val:
                continue

            inst_val = item.get("instructions", "")
            if isinstance(inst_val, list):
                inst_val = "\n".join(inst_val)

            cm_val = item.get("common_mistakes", "")
            if isinstance(cm_val, list):
                cm_val = "\n".join(cm_val)

            sn_val = item.get("safety_notes", "")
            if isinstance(sn_val, list):
                sn_val = "\n".join(sn_val)

            slug_name = name_val.lower().replace(' ', '_').replace('-', '_')
            video_disk = BASE_DIR / "static" / "exercise_media" / f"{slug_name}.mp4"
            status_val = "available" if video_disk.exists() else "missing"

            existing_record = existing_ex.get(ex_id) or existing_names.get(name_val.lower())
            if existing_record:
                # Update existing exercise metadata safely
                existing_record.category = item.get("category", existing_record.category or "General")
                existing_record.primary_muscles = json.dumps(item.get("primary_muscles", [])) if isinstance(item.get("primary_muscles"), list) else (item.get("primary_muscles") or existing_record.primary_muscles)
                existing_record.secondary_muscles = json.dumps(item.get("secondary_muscles", [])) if isinstance(item.get("secondary_muscles"), list) else (item.get("secondary_muscles") or existing_record.secondary_muscles)
                existing_record.equipment = item.get("equipment", existing_record.equipment)
                existing_record.difficulty = item.get("difficulty", existing_record.difficulty)
                existing_record.environment = item.get("environment", existing_record.environment)
                existing_record.goal = item.get("goal", existing_record.goal)
                existing_record.instructions = inst_val or existing_record.instructions
                existing_record.common_mistakes = cm_val or existing_record.common_mistakes
                existing_record.safety_notes = sn_val or existing_record.safety_notes
                existing_record.demo_video = f"/static/exercise_media/{slug_name}.mp4" if video_disk.exists() else existing_record.demo_video
                existing_record.media_status = status_val
            else:
                e = Exercise(
                    id=ex_id,
                    name=name_val,
                    aliases=json.dumps(item.get("aliases", [name_val.lower()])),
                    category=item.get("category", "General"),
                    primary_muscles=json.dumps(item.get("primary_muscles", [item.get("category", "General")])),
                    secondary_muscles=json.dumps(item.get("secondary_muscles", [])),
                    equipment=item.get("equipment", "No Equipment"),
                    difficulty=item.get("difficulty", "Beginner"),
                    environment=item.get("environment", "Gym"),
                    goal=item.get("goal", "General Fitness"),
                    instructions=inst_val,
                    common_mistakes=cm_val,
                    safety_notes=sn_val,
                    default_sets=item.get("default_sets", item.get("sets", 3)),
                    default_reps_min=item.get("reps_min", 8),
                    default_reps_max=item.get("reps_max", 12),
                    default_rest_seconds=item.get("default_rest", item.get("rest_seconds", 60)),
                    demonstration_available=item.get("demonstration_available", True),
                    demonstration_asset=item.get("demonstration_asset", f"/static/exercises/{slug_name}/demo.svg"),
                    thumbnail=item.get("thumbnail", f"/static/exercises/{slug_name}/thumbnail.png"),
                    demo_video=f"/static/exercise_media/{slug_name}.mp4" if video_disk.exists() else None,
                    animation_type="video",
                    media_status=status_val
                )
                db.session.add(e)
                added_count += 1
        db.session.commit()
        if added_count > 0:
            print(f"[SEED] Added {added_count} new exercises to SQLite database.")
    except Exception as err:
        db.session.rollback()
        print(f"[SEED WARNING] Exercise table seed error: {err}")

def seed_foods_table():
    try:
        p = BASE_DIR / "data" / "foods.json"
        if not p.exists():
            return
        with open(p, 'r', encoding='utf-8') as f:
            food_list = json.load(f)

        existing_foods = {f.id: f for f in Food.query.all()}
        existing_names = {f.name.lower(): f for f in existing_foods.values()}

        added_count = 0
        for item in food_list:
            fd_id = item.get("id")
            name_val = item.get("name", "").strip()
            if not name_val:
                continue

            existing_record = existing_foods.get(fd_id) or existing_names.get(name_val.lower())
            if existing_record:
                # Keep food macros updated
                existing_record.category = item.get("category", existing_record.category)
                existing_record.serving_size_g = item.get("serving_size_g", existing_record.serving_size_g)
                existing_record.calories = item.get("calories", existing_record.calories)
                existing_record.protein = item.get("protein", existing_record.protein)
                existing_record.carbs = item.get("carbs", existing_record.carbs)
                existing_record.fat = item.get("fat", existing_record.fat)
                existing_record.fiber = item.get("fiber", existing_record.fiber)
                existing_record.cost_approx = item.get("cost_approx", existing_record.cost_approx)
                existing_record.common_unit = item.get("common_unit", existing_record.common_unit)
                existing_record.is_vegetarian = item.get("is_vegetarian", existing_record.is_vegetarian)
                existing_record.is_vegan = item.get("is_vegan", existing_record.is_vegan)
            else:
                fd = Food(
                    id=fd_id,
                    name=name_val,
                    category=item.get("category", "General"),
                    serving_size_g=item.get("serving_size_g", 100),
                    calories=item.get("calories", 0),
                    protein=item.get("protein", 0.0),
                    carbs=item.get("carbs", 0.0),
                    fat=item.get("fat", 0.0),
                    fiber=item.get("fiber", 0.0),
                    cost_approx=item.get("cost_approx", 0),
                    common_unit=item.get("common_unit", ""),
                    is_vegetarian=item.get("is_vegetarian", True),
                    is_vegan=item.get("is_vegan", False)
                )
                db.session.add(fd)
                added_count += 1
        db.session.commit()
        if added_count > 0:
            print(f"[SEED] Added {added_count} new foods to SQLite database.")
    except Exception as err:
        db.session.rollback()
        print(f"[SEED WARNING] Food table seed error: {err}")

# -----------------------------------------------------------------------------
# DATABASE SEEDER
# -----------------------------------------------------------------------------
def seed_database():
    # Verify if tables exist and are empty
    run_migrations()
    seed_exercises_table()
    seed_foods_table()

    demo_email = "demo@fitsync.ai"
    user = User.query.filter_by(email=demo_email).first()
    if user:
        return

    print("[SEED] Seeding Demo User...")
    try:
        # 1. User
        hashed_pwd = generate_password_hash("Demo@123")
        user = User(email=demo_email, password_hash=hashed_pwd)
        db.session.add(user)
        db.session.commit()

        # 2. Profile
        profile = UserProfile(
            user_id=user.id,
            name="Rahul Sharma",
            age=20,
            gender="Male",
            height=175.0,
            weight=72.0,
            fitness_goal="Muscle Gain",
            fitness_level="Beginner",
            workout_days_per_week=4,
            workout_duration_mins=45,
            workout_environment="Gym",
            dietary_preference="Eggetarian",
            budget_preference="₹150",
            daily_food_budget=150,
            onboarding_completed=True
        )
        db.session.add(profile)

        # 3. Equipments
        eqs = ["Dumbbells", "No Equipment"]
        for eq in eqs:
            db.session.add(UserEquipment(user_id=user.id, equipment_name=eq))

        # 4. Food Preferences
        food_prefs = [
            ("Boiled Eggs", True, True, False),
            ("Paneer (Cottage Cheese)", True, True, False),
            ("Yellow Dal (Tadka)", False, True, False),
            ("White Rice", False, True, False),
            ("Chapati (Whole Wheat Roti)", True, True, False),
            ("Peanuts", False, True, False),
            ("Roasted Chana", False, True, False),
            ("Banana", True, True, False)
        ]
        for name, pref, avail, avoid in food_prefs:
            db.session.add(UserFoodPreference(
                user_id=user.id,
                food_name=name,
                is_preferred=pref,
                is_available=avail,
                is_avoided=avoid
            ))

        # 5. AI Targets
        macros = calculate_ai_targets(profile)
        targets = NutritionTarget(
            user_id=user.id,
            calories=macros["calories"],
            protein=macros["protein"],
            carbs=macros["carbs"],
            fat=macros["fat"],
            is_custom=False
        )
        db.session.add(targets)
        db.session.commit()

        # 6. Plans
        all_exercises = get_exercises_data()
        weekly_workout = generate_weekly_workout(profile, eqs, all_exercises)
        w_plan = WorkoutPlan(user_id=user.id, is_active=True)
        db.session.add(w_plan)
        db.session.commit()

        for day in weekly_workout:
            w_day = WorkoutDay(
                workout_plan_id=w_plan.id,
                day_name=day["day_name"],
                day_number=day.get("day_number", 1),
                focus=day["focus"],
                is_completed=False,
                is_rest_day=day["is_rest_day"],
                status="rest" if day["is_rest_day"] else "upcoming",
                duration_minutes=day.get("duration_minutes", 0)
            )
            db.session.add(w_day)
            db.session.commit()

            for idx, ex in enumerate(day["exercises"]):
                w_ex = WorkoutExercise(
                    workout_day_id=w_day.id,
                    exercise_id=ex["exercise_id"],
                    name=ex["name"],
                    category=ex["category"],
                    sets=ex["sets"],
                    reps=ex["reps"],
                    reps_min=ex.get("reps_min", 8),
                    reps_max=ex.get("reps_max", 12),
                    rest_seconds=ex["rest_seconds"],
                    instructions=ex["instructions"],
                    start_pos=ex.get("start_pos"),
                    movement=ex.get("movement"),
                    end_pos=ex.get("end_pos"),
                    common_mistakes=ex.get("common_mistakes"),
                    is_completed=False,
                    order_idx=idx
                )
                db.session.add(w_ex)
        
        # 7. Meal plan for today
        all_foods = get_foods_data()
        today_str = datetime.now().strftime("%Y-%m-%d")
        daily_meals = generate_daily_meals(profile, user.food_preferences, targets, all_foods, today_str)
        m_plan = MealPlan(
            user_id=user.id,
            date=today_str,
            total_calories=0,
            total_protein=0.0,
            total_carbs=0.0,
            total_fat=0.0
        )
        db.session.add(m_plan)
        db.session.commit()

        cals, prot, carbs, fat, cost = 0, 0.0, 0.0, 0.0, 0
        for m in daily_meals:
            meal = Meal(
                meal_plan_id=m_plan.id,
                meal_type=m["meal_type"],
                food_id=m["food_id"],
                food_name=m["food_name"],
                serving_size_g=m["serving_size_g"],
                calories=m["calories"],
                protein=m["protein"],
                carbs=m["carbs"],
                fat=m["fat"],
                cost=m.get("cost", 0),
                common_unit=m["common_unit"]
            )
            db.session.add(meal)
            cals += m["calories"]
            prot += m["protein"]
            carbs += m["carbs"]
            fat += m["fat"]
            cost += m.get("cost", 0)

        m_plan.total_calories = cals
        m_plan.total_protein = round(prot, 1)
        m_plan.total_carbs = round(carbs, 1)
        m_plan.total_fat = round(fat, 1)
        m_plan.total_cost = cost

        # 8. Seed some progress history for Chart.js
        for i in range(6, -1, -1):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            p_weight = round(72.0 - (i * 0.15) + (0.1 * (i % 3 - 1)), 1)
            factor = 1.0 + (0.05 * (i % 4 - 2))
            
            rec = ProgressRecord(
                user_id=user.id,
                date=date_str,
                weight=p_weight,
                workouts_completed=max(0, 3 - (i // 2)),
                calories_consumed=int(targets.calories * factor),
                protein_consumed=round(targets.protein * factor, 1),
                carbs_consumed=round(targets.carbs * factor, 1),
                fat_consumed=round(targets.fat * factor, 1)
            )
            db.session.add(rec)

        db.session.commit()
        print("[SEED] Seed finished successfully.")
    except Exception as e:
        db.session.rollback()
        print(f"[SEED ERROR] Seeder failed: {e}")

def init_app_database(app_instance):
    with app_instance.app_context():
        try:
            db.create_all()
            run_migrations()
            seed_database()
        except Exception as e:
            db.session.rollback()
            print(f"[DB INIT WARNING] {e}")
        print_db_debug_info()




@app.errorhandler(500)
def server_error(e):
    original_err = getattr(e, 'original_exception', e)
    app.logger.error(f"[SERVER ERROR 500] {original_err}", exc_info=True)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"status": "error", "message": str(original_err)}), 500
    return f"""
    <div style="font-family: system-ui, sans-serif; padding: 40px; background: #0b0f19; color: #f8fafc; min-height: 100vh;">
      <h2 style="color: #f43f5e;">FITSYNC Server Error Details</h2>
      <p style="font-size: 15px; color: #94a3b8;">The backend encountered a runtime exception:</p>
      <pre style="background: #1e293b; padding: 16px; border-radius: 8px; color: #e2e8f0; overflow-x: auto; white-space: pre-wrap;">{str(original_err)}</pre>
      <p><a href="/" style="color: #38bdf8; text-decoration: none;">&larr; Back to Home</a></p>
    </div>
    """, 500

# -----------------------------------------------------------------------------
# FLASK ROUTE AND SESSION CONTROLLER
# -----------------------------------------------------------------------------
def get_current_user():
    if 'user_id' not in session:
        return None
    try:
        user = db.session.get(User, session['user_id'])
        if not user:
            session.pop('user_id', None)
            return None
        return user
    except Exception:
        db.session.rollback()
        session.pop('user_id', None)
        return None

def is_user_onboarded(user):
    if not user:
        return False
    if session.get('is_onboarded') is True:
        return True
    profile = UserProfile.query.filter_by(user_id=user.id).first()
    if not profile:
        return False
    onboarded = bool(profile.onboarding_completed)
    if onboarded:
        session['is_onboarded'] = True
    return onboarded

def require_onboarded_user():
    user = get_current_user()
    if not user:
        return None, redirect(url_for("login"))
    if not is_user_onboarded(user):
        return None, redirect(url_for("onboarding"))
    return user, None

@app.route("/")
def index():
    user = get_current_user()
    if user:
        if is_user_onboarded(user):
            return redirect(url_for("dashboard"))
        return redirect(url_for("onboarding"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    user = get_current_user()
    if user and request.method == "GET":
        if is_user_onboarded(user):
            return redirect(url_for("dashboard"))
        return redirect(url_for("onboarding"))

    if request.method == "POST":
        raw_email = request.form.get("email")
        password = request.form.get("password")
        
        if not raw_email or not password:
            flash("Please enter both email and password.", "error")
            return redirect(url_for("register"))

        clean_email = normalize_email(raw_email)
        existing = User.query.filter(func.lower(User.email) == clean_email).first()
        if existing:
            flash("An account with this email already exists. Please log in below.", "warning")
            return redirect(url_for("login"))

        hashed = generate_password_hash(password)
        new_user = User(email=clean_email, password_hash=hashed)
        db.session.add(new_user)
        db.session.commit()

        session.permanent = True
        session['user_id'] = new_user.id
        return redirect(url_for("onboarding"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    user = get_current_user()
    if user and request.method == "GET":
        if is_user_onboarded(user):
            return redirect(url_for("dashboard"))
        return redirect(url_for("onboarding"))

    if request.method == "POST":
        raw_email = request.form.get("email")
        password = request.form.get("password")
        
        if not raw_email or not password:
            flash("Please enter both email and password.", "error")
            return redirect(url_for("login"))

        clean_email = normalize_email(raw_email)
        user = User.query.filter(func.lower(User.email) == clean_email).first()

        if not user:
            flash("No account found with this email address. Please check your email or create an account.", "error")
            return redirect(url_for("login", email=clean_email))

        if not check_password_hash(user.password_hash, password):
            flash("Incorrect password. Please try again.", "error")
            return redirect(url_for("login", email=clean_email))

        session.permanent = True
        session['user_id'] = user.id

        if is_user_onboarded(user):
            return redirect(url_for("dashboard"))
        return redirect(url_for("onboarding"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Successfully logged out.", "success")
    return redirect(url_for("login"))

@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    user = get_current_user()
    if not user:
        if request.method == "POST":
            demo = User.query.filter_by(email="demo@fitsync.ai").first()
            if demo:
                session['user_id'] = demo.id
                user = demo
            else:
                return jsonify({"status": "error", "message": "Session expired. Please log in again."}), 401
        else:
            return redirect(url_for("login"))

    # If already completed onboarding and viewing page, go directly to dashboard
    if request.method == "GET" and is_user_onboarded(user):
        return redirect(url_for("dashboard"))

    all_foods = get_all_user_foods(user) if user else []

    if request.method == "POST":
        try:
            data = request.json
            profile = UserProfile.query.filter_by(user_id=user.id).first()
            if not profile:
                profile = UserProfile(user_id=user.id)
                db.session.add(profile)

            user.name = data["name"]
            profile.name = data["name"]
            profile.age = int(data["age"])
            profile.gender = data["gender"]
            profile.height = float(data["height"])
            profile.weight = float(data["weight"])
            profile.fitness_goal = data["fitness_goal"]
            profile.fitness_level = data["fitness_level"]
            profile.workout_days_per_week = int(data["workout_days_per_week"])
            profile.workout_duration_mins = int(data["workout_duration_mins"])
            profile.workout_environment = data.get("workout_environment", "Gym")
            profile.dietary_preference = data["dietary_preference"]
            
            # Budget preference and daily food budget parsing
            budget_str = data.get("budget_preference", "₹150")
            profile.budget_preference = budget_str
            try:
                if "daily_food_budget" in data and data["daily_food_budget"]:
                    val = int(str(data["daily_food_budget"]).strip())
                    if val <= 0:
                        return jsonify({"status": "error", "message": "Please enter a valid daily food budget (must be greater than 0)."}), 400
                    profile.daily_food_budget = val
                    profile.budget_preference = f"₹{val}"
                else:
                    digits = "".join([c for c in str(budget_str) if c.isdigit()])
                    if digits:
                        profile.daily_food_budget = int(digits)
                    else:
                        profile.daily_food_budget = 150
            except Exception:
                return jsonify({"status": "error", "message": "Please enter a valid daily food budget."}), 400

            # Clear old preferences
            UserEquipment.query.filter_by(user_id=user.id).delete()
            UserFoodPreference.query.filter_by(user_id=user.id).delete()

            for eq in data["equipments"]:
                db.session.add(UserEquipment(user_id=user.id, equipment_name=eq))

            for pref in data.get("food_preferences", []):
                db.session.add(UserFoodPreference(
                    user_id=user.id,
                    food_name=pref["food_name"],
                    is_preferred=pref.get("is_preferred", False),
                    is_available=pref.get("is_available", False),
                    is_avoided=pref.get("is_avoided", False)
                ))

            # AI targets
            db.session.commit() # Save profile first
            macros = calculate_ai_targets(profile)
            
            NutritionTarget.query.filter_by(user_id=user.id).delete()
            targets = NutritionTarget(
                user_id=user.id,
                calories=macros["calories"],
                protein=macros["protein"],
                carbs=macros["carbs"],
                fat=macros["fat"],
                is_custom=False
            )
            db.session.add(targets)
            db.session.commit()

            # Generate workout and nutrition
            try:
                WorkoutPlan.query.filter_by(user_id=user.id).delete()
                all_exercises = get_exercises_data()
                weekly_workout = generate_weekly_workout(profile, data.get("equipments", []), all_exercises)
                if not weekly_workout:
                    raise ValueError("Failed to generate weekly workout plan.")
                w_plan = WorkoutPlan(user_id=user.id, is_active=True)
                db.session.add(w_plan)
                db.session.commit()

                valid_ex_ids = {e[0] for e in db.session.query(Exercise.id).all()}
                for day in weekly_workout:
                    w_day = WorkoutDay(
                        workout_plan_id=w_plan.id,
                        day_name=day["day_name"],
                        day_number=day.get("day_number", 1),
                        focus=day["focus"],
                        is_completed=False,
                        is_rest_day=day["is_rest_day"],
                        status="rest" if day["is_rest_day"] else "upcoming",
                        duration_minutes=day.get("duration_minutes", 0)
                    )
                    db.session.add(w_day)
                    db.session.commit()

                    for idx, ex in enumerate(day["exercises"]):
                        target_ex_id = ex.get("exercise_id")
                        if target_ex_id is not None:
                            try:
                                target_ex_id = int(target_ex_id)
                                if target_ex_id not in valid_ex_ids:
                                    target_ex_id = None
                            except (ValueError, TypeError):
                                target_ex_id = None

                        w_ex = WorkoutExercise(
                            workout_day_id=w_day.id,
                            exercise_id=target_ex_id,
                            name=ex["name"],
                            category=ex["category"],
                            sets=ex["sets"],
                            reps=ex["reps"],
                            reps_min=ex.get("reps_min", 8),
                            reps_max=ex.get("reps_max", 12),
                            rest_seconds=ex["rest_seconds"],
                            instructions=ex["instructions"],
                            start_pos=ex.get("start_pos"),
                            movement=ex.get("movement"),
                            end_pos=ex.get("end_pos"),
                            common_mistakes=ex.get("common_mistakes"),
                            is_completed=False,
                            order_idx=idx
                        )
                        db.session.add(w_ex)
                db.session.commit()
            except Exception as w_err:
                app.logger.error(f"Workout generation error: {w_err}", exc_info=True)
                db.session.rollback()
                try:
                    WorkoutPlan.query.filter_by(user_id=user.id).delete()
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                return jsonify({"status": "error", "message": "We couldn't generate your workout plan. Please try again."}), 400

            # Generate food
            MealPlan.query.filter_by(user_id=user.id).delete()
            today_str = datetime.now().strftime("%Y-%m-%d")
            daily_meals = generate_daily_meals(profile, user.food_preferences, targets, all_foods, today_str)
            m_plan = MealPlan(
                user_id=user.id,
                date=today_str,
                total_calories=0,
                total_protein=0.0,
                total_carbs=0.0,
                total_fat=0.0,
                total_cost=0
            )
            db.session.add(m_plan)
            db.session.commit()

            cals, prot, carbs, fat, cost = 0, 0.0, 0.0, 0.0, 0
            for m in daily_meals:
                meal = Meal(
                    meal_plan_id=m_plan.id,
                    meal_type=m["meal_type"],
                    food_id=m["food_id"],
                    food_name=m["food_name"],
                    serving_size_g=m["serving_size_g"],
                    calories=m["calories"],
                    protein=m["protein"],
                    carbs=m["carbs"],
                    fat=m["fat"],
                    cost=m.get("cost", 0),
                    common_unit=m["common_unit"]
                )
                db.session.add(meal)
                cals += m["calories"]
                prot += m["protein"]
                carbs += m["carbs"]
                fat += m["fat"]
                cost += m.get("cost", 0)

            m_plan.total_calories = cals
            m_plan.total_protein = round(prot, 1)
            m_plan.total_carbs = round(carbs, 1)
            m_plan.total_fat = round(fat, 1)
            m_plan.total_cost = cost

            # Initial progress log
            ProgressRecord.query.filter_by(user_id=user.id, date=today_str).delete()
            rec = ProgressRecord(
                user_id=user.id,
                date=today_str,
                weight=profile.weight,
                workouts_completed=0,
                calories_consumed=cals,
                protein_consumed=round(prot, 1),
                carbs_consumed=round(carbs, 1),
                fat_consumed=round(fat, 1)
            )
            db.session.add(rec)
            
            # Mark onboarding completed now that all generation succeeded
            profile.onboarding_completed = True
            db.session.commit()
            session['is_onboarded'] = True

            return jsonify({"status": "success"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"status": "error", "message": str(e)}), 400

    return render_template("onboarding.html", foods=all_foods)

@app.route("/dashboard")
def dashboard():
    user, redir = require_onboarded_user()
    if redir:
        return redir

    # Determine weekday focus
    today_name = datetime.now().strftime("%A")
    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()
    today_workout = None
    if plan:
        today_workout = WorkoutDay.query.filter_by(workout_plan_id=plan.id, day_name=today_name).first()

    today_str = datetime.now().strftime("%Y-%m-%d")
    meal_plan = MealPlan.query.filter_by(user_id=user.id, date=today_str).first()
    targets = NutritionTarget.query.filter_by(user_id=user.id).first()

    return render_template("dashboard.html", 
                           profile=user.profile, 
                           workout_day=today_workout, 
                           meal_plan=meal_plan, 
                           targets=targets)

@app.route("/workout-plan")
def workout_plan():
    user, redir = require_onboarded_user()
    if redir:
        return redir
    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()

    today_name = datetime.now().strftime("%A")
    today_day_number = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4,
                        "Friday": 5, "Saturday": 6, "Sunday": 7}.get(today_name, 1)

    # Weekly stats
    total_workout_days = 0
    completed_days = 0
    if plan:
        for d in plan.days:
            if not d.is_rest_day:
                total_workout_days += 1
                if d.is_completed:
                    completed_days += 1

    # Streak: count consecutive completed days (from completed_workouts or workout_days)
    streak = 0
    if plan:
        days_sorted = sorted([d for d in plan.days if d.is_completed and not d.is_rest_day],
                             key=lambda d: d.day_number or 0, reverse=True)
        prev_num = None
        for d in days_sorted:
            dn = d.day_number or 0
            if prev_num is None or prev_num - dn == 1:
                streak += 1
                prev_num = dn
            else:
                break

    if plan and plan.days:
        for d in plan.days:
            if d.day_number is None:
                d.day_number = 0

    # Equipment list
    equipment_list = [eq.equipment_name for eq in user.equipments]

    # Completed workout history (last 10)
    history = CompletedWorkout.query.filter_by(user_id=user.id).order_by(CompletedWorkout.id.desc()).limit(10).all()

    return render_template("workout_plan.html",
                           plan=plan,
                           profile=user.profile,
                           today_name=today_name,
                           today_day_number=today_day_number,
                           streak=streak,
                           completed_days=completed_days,
                           total_workout_days=total_workout_days,
                           equipment_list=equipment_list,
                           history=history)

@app.route("/today-workout")
def today_workout():
    user, redir = require_onboarded_user()
    if redir:
        return redir

    day_name = request.args.get("day", datetime.now().strftime("%A"))
    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()

    workout_day = None
    all_plan_days = []
    if plan:
        workout_day = WorkoutDay.query.filter_by(workout_plan_id=plan.id, day_name=day_name).first()
        all_plan_days = sorted(plan.days, key=lambda d: d.day_number or 0)

    equipment_list = [eq.equipment_name for eq in user.equipments]

    return render_template("today_workout.html",
                           workout_day=workout_day,
                           day_name=day_name,
                           profile=user.profile,
                           plan=plan,
                           all_plan_days=all_plan_days,
                           equipment_list=equipment_list)

@app.route("/exercises")
def exercises():
    user, redir = require_onboarded_user()
    if redir:
        return redir
    all_ex = get_exercises_data()
    m_path = BASE_DIR / "data" / "gym_knowledge" / "muscles.json"
    muscles = []
    if m_path.exists():
        with open(m_path, "r", encoding="utf-8") as f:
            muscles = json.load(f)
    return render_template("exercise_library.html", exercises=all_ex, muscles=muscles)

@app.route("/exercise/<int:ex_id>")
def exercise_detail(ex_id):
    user, redir = require_onboarded_user()
    if redir:
        return redir
    all_ex = get_exercises_data()
    ex = next((item for item in all_ex if item["id"] == ex_id), None)
    if not ex:
        flash("Exercise not found.", "error")
        return redirect(url_for("exercises"))
    return render_template("exercise_detail.html", ex=ex)

@app.route("/meal/<int:meal_id>")
def meal_detail(meal_id):
    user, redir = require_onboarded_user()
    if redir:
        return redir
    meal = db.session.get(Meal, meal_id)
    if not meal or meal.meal_plan.user_id != user.id:
        flash("Meal not found.", "error")
        return redirect(url_for("nutrition"))
    return render_template("meal_detail.html", meal=meal)

@app.route("/form-check")
def form_check():
    user, redir = require_onboarded_user()
    if redir:
        return redir
    
    all_exercises = sorted(get_exercises_data(), key=lambda x: x.get('name', ''))
    exercise_id = request.args.get("exercise_id", type=int)
    ex_slug = request.args.get("exercise", type=str)
    
    selected_ex = None
    if exercise_id:
        selected_ex = next((ex for ex in all_exercises if ex.get("id") == exercise_id), None)
    elif ex_slug:
        normalized = ex_slug.lower().replace('-', '_')
        for ex in all_exercises:
            name_norm = ex.get('name', '').lower().replace(' ', '_').replace('-', '_')
            if name_norm == normalized or normalized in name_norm:
                selected_ex = ex
                break

    if not selected_ex and all_exercises:
        selected_ex = all_exercises[0]

    return render_template("form_check.html", exercises=all_exercises, selected_ex=selected_ex)

@app.route("/nutrition", methods=["GET"])
def nutrition():
    user, redir = require_onboarded_user()
    if redir:
        return redir
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    meal_plan = MealPlan.query.filter_by(user_id=user.id, date=today_str).first()
    targets = NutritionTarget.query.filter_by(user_id=user.id).first()
    
    avail_count = len([p for p in user.food_preferences if p.is_available])
    all_foods = get_all_user_foods(user)
    custom_foods = CustomFood.query.filter_by(user_id=user.id).order_by(CustomFood.created_at.desc()).all()
    
    return render_template(
        "nutrition.html", 
        meal_plan=meal_plan, 
        targets=targets,
        daily_budget=user.profile.daily_food_budget or 150,
        total_estimated_cost=meal_plan.total_cost if meal_plan else 0,
        available_foods_count=avail_count,
        foods=all_foods,
        custom_foods=custom_foods
    )

@app.route("/progress")
def progress():
    user, redir = require_onboarded_user()
    if redir:
        return redir
    return render_template("progress.html", profile=user.profile)

@app.route("/profile")
def profile():
    user, redir = require_onboarded_user()
    if redir:
        return redir
        
    preferred_foods = [p.food_name for p in user.food_preferences if p.is_preferred]
    available_foods = [p.food_name for p in user.food_preferences if p.is_available]
    avoided_foods = [p.food_name for p in user.food_preferences if p.is_avoided]
    
    return render_template(
        "profile.html", 
        profile=user.profile,
        preferred_foods=preferred_foods,
        available_foods=available_foods,
        avoided_foods=avoided_foods
    )

@app.route("/settings", methods=["GET", "POST"])
def settings():
    user, redir = require_onboarded_user()
    if redir:
        return redir
    all_foods = get_all_user_foods(user)
    user_prefs = {}
    for p in user.food_preferences:
        user_prefs[p.food_name.lower()] = {
            "is_preferred": p.is_preferred,
            "is_available": p.is_available,
            "is_avoided": p.is_avoided
        }
    return render_template("settings.html", profile=user.profile, foods=all_foods, user_prefs=user_prefs)

@app.route("/ai-coach", endpoint="ai_coach_page")
@app.route("/ai-coach", endpoint="ai_coach")
def ai_coach_page():
    user, redir = require_onboarded_user()
    if redir:
        return redir
    return render_template("ai_coach.html", profile=user.profile)

# -----------------------------------------------------------------------------
# CUSTOM FOODS & EXERCISE SEARCH & AI DIET API ROUTES
# -----------------------------------------------------------------------------

@app.route("/api/custom-foods", methods=["GET", "POST"])
def api_custom_foods():
    user = get_current_user()
    if not user:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    if request.method == "GET":
        foods = CustomFood.query.filter_by(user_id=user.id).order_by(CustomFood.created_at.desc()).all()
        result = []
        for f in foods:
            result.append({
                "id": f.id,
                "name": f.name,
                "category": f.category,
                "serving_size_g": f.serving_size_g,
                "calories": f.calories,
                "protein": f.protein,
                "carbs": f.carbs,
                "fat": f.fat,
                "fiber": f.fiber or 0.0,
                "cost": f.cost,
                "notes": f.notes or ""
            })
        return jsonify({"status": "success", "custom_foods": result})

    # POST - Create custom food
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"status": "error", "message": "Food name is required."}), 400

    try:
        serving_size_g = int(data.get("serving_size_g", 0))
        calories = int(data.get("calories", 0))
        protein = float(data.get("protein", 0.0))
        carbs = float(data.get("carbs", 0.0))
        fat = float(data.get("fat", 0.0))
        fiber = float(data.get("fiber", 0.0))
        cost = int(data.get("cost", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Nutrition and cost values must be valid non-negative numbers."}), 400

    if serving_size_g < 0 or calories < 0 or protein < 0 or carbs < 0 or fat < 0 or fiber < 0 or cost < 0:
        return jsonify({"status": "error", "message": "Nutrition values cannot be negative."}), 400

    c_food = CustomFood(
        user_id=user.id,
        name=name,
        category=data.get("category", "Homemade") or "Homemade",
        serving_size_g=serving_size_g,
        calories=calories,
        protein=protein,
        carbs=carbs,
        fat=fat,
        fiber=fiber,
        cost=cost,
        notes=data.get("notes", "")
    )
    db.session.add(c_food)
    db.session.commit()

    pref = UserFoodPreference.query.filter_by(user_id=user.id, food_name=name).first()
    if not pref:
        pref = UserFoodPreference(
            user_id=user.id,
            food_name=name,
            is_preferred=True,
            is_available=True,
            is_avoided=False
        )
        db.session.add(pref)
        db.session.commit()

    return jsonify({"status": "success", "message": f"Added '{name}' to your custom foods.", "id": c_food.id})


@app.route("/api/custom-foods/<int:food_id>", methods=["PUT", "DELETE"])
def api_manage_custom_food(food_id):
    user = get_current_user()
    if not user:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    c_food = db.session.get(CustomFood, food_id)
    if not c_food or c_food.user_id != user.id:
        return jsonify({"status": "error", "message": "Custom food item not found."}), 404

    if request.method == "DELETE":
        db.session.delete(c_food)
        db.session.commit()
        return jsonify({"status": "success", "message": "Custom food deleted."})

    # PUT - Edit custom food
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"status": "error", "message": "Food name cannot be empty."}), 400

    try:
        c_food.name = name
        c_food.category = data.get("category", c_food.category)
        c_food.serving_size_g = int(data.get("serving_size_g", c_food.serving_size_g))
        c_food.calories = int(data.get("calories", c_food.calories))
        c_food.protein = float(data.get("protein", c_food.protein))
        c_food.carbs = float(data.get("carbs", c_food.carbs))
        c_food.fat = float(data.get("fat", c_food.fat))
        c_food.fiber = float(data.get("fiber", c_food.fiber))
        c_food.cost = int(data.get("cost", c_food.cost))
        c_food.notes = data.get("notes", c_food.notes)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid numeric input."}), 400

    db.session.commit()
    return jsonify({"status": "success", "message": "Custom food updated."})


@app.route("/api/exercises/<int:exercise_id>", methods=["GET"])
def api_get_exercise(exercise_id):
    all_ex = get_exercises_data()
    ex = next((item for item in all_ex if item["id"] == exercise_id), None)
    if not ex:
        db_ex = db.session.get(Exercise, exercise_id)
        if db_ex:
            ex = db_ex.to_dict()
    if not ex:
        return jsonify({"status": "error", "message": "Exercise not found"}), 404

    # Security validation of media reference
    demo_video = ex.get("demo_video")
    if demo_video and not validate_media_path(demo_video):
        demo_video = None

    return jsonify({
        "status": "success",
        "id": ex.get("id"),
        "exercise_id": ex.get("id"),
        "name": ex.get("name"),
        "slug": ex.get("slug"),
        "category": ex.get("category"),
        "primary_muscles": ex.get("primary_muscles", []),
        "secondary_muscles": ex.get("secondary_muscles", []),
        "primary_muscle": ex.get("primary_muscle") or (ex.get("primary_muscles", [ex.get("category")])[0] if ex.get("primary_muscles") else ex.get("category")),
        "equipment": ex.get("equipment", "No Equipment"),
        "difficulty": ex.get("difficulty", "Beginner"),
        "environment": ex.get("environment", "Gym"),
        "instructions": ex.get("instructions", []),
        "common_mistakes": ex.get("common_mistakes", []),
        "safety_notes": ex.get("safety_notes", ""),
        "sets": ex.get("sets", 3),
        "reps": ex.get("reps", "8-12"),
        "rest_seconds": ex.get("rest_seconds", 60),
        "demo_video": demo_video,
        "media_path": ex.get("media_path"),
        "demonstration_asset": ex.get("demonstration_asset"),
        "thumbnail": ex.get("thumbnail"),
        "media_type": ex.get("media_type", "mp4"),
        "media_status": ex.get("media_status", "missing"),
        "media_available": bool(ex.get("media_available", False)),
        "supported_demo": bool(ex.get("supported_demo", True)),
        "start_pos": ex.get("start_pos", "Establish solid starting alignment."),
        "movement": ex.get("movement", "Execute movement under control."),
        "end_pos": ex.get("end_pos", "Contract target muscle group at peak and return."),
        "working_location": ex.get("working_location", ex.get("category")),
        "joint_action": ex.get("joint_action", "Joint Flexion & Extension"),
        "muscle_engagement": ex.get("muscle_engagement", {"primary_pct": 80, "secondary_pct": 20}),
        "coaching_cues": ex.get("coaching_cues", []),
        "has_3d_demo": True,
        "demo_type": "3d",
        "model_path": f"/static/3d/models/{ex.get('slug')}.glb",
        "animation_clip": ex.get("slug"),
        "camera_config": {
            "preset": "front_3_4" if ex.get("category") in ["Arms", "Chest", "Shoulders"] else "side_3_4",
            "distance": 4.5,
            "fov": 45
        }
    })


@app.route("/api/exercises/search")
def api_search_exercises():
    query = request.args.get("q", "").strip().lower()
    category = request.args.get("category", "").strip().lower()
    equipment = request.args.get("equipment", "").strip().lower()
    difficulty = request.args.get("difficulty", "").strip().lower()
    only_demo = request.args.get("demo", "").strip().lower() == "true"

    all_ex = get_exercises_data()
    filtered = []

    for ex in all_ex:
        if query:
            name_match = query in ex["name"].lower()
            cat_match = query in ex["category"].lower()
            sec_match = any(query in sec.lower() for sec in ex.get("secondary_muscles", []))
            equip_match = query in ex.get("equipment", "").lower()
            if not (name_match or cat_match or sec_match or equip_match):
                continue

        if category and category != "all":
            if ex["category"].lower() != category:
                continue

        if equipment and equipment != "all":
            if equipment == "home":
                if ex["equipment"] not in ["No Equipment", "Dumbbells", "Resistance Bands"]:
                    continue
            elif equipment == "gym":
                if ex["equipment"] != "Full Gym":
                    continue
            elif ex["equipment"].lower() != equipment:
                continue

        if difficulty and difficulty != "all":
            if ex["difficulty"].lower() != difficulty:
                continue

        if only_demo and not ex.get("supported_demo", True):
            continue

        filtered.append(ex)

    return jsonify({
        "status": "success",
        "query": query,
        "total_supported": len(all_ex),
        "count": len(filtered),
        "results": filtered
    })


def get_exercise_animation_data(exercise_id_or_name):
    anim_path = BASE_DIR / "data" / "exercise_animations.json"
    animations_data = {}
    if anim_path.exists():
        try:
            with open(anim_path, "r", encoding="utf-8") as f:
                animations_data = json.load(f)
        except Exception:
            pass

    ex_obj = None
    if str(exercise_id_or_name).isdigit():
        ex_obj = db.session.get(Exercise, int(exercise_id_or_name))
    if not ex_obj:
        ex_obj = Exercise.query.filter(func.lower(Exercise.name) == str(exercise_id_or_name).lower()).first()

    slug = ""
    if ex_obj:
        slug = ex_obj.name.lower().replace(' ', '_').replace('-', '_')
    else:
        slug = str(exercise_id_or_name).lower().replace(' ', '_').replace('-', '_')

    if slug in animations_data:
        return animations_data[slug], ex_obj

    for key, data in animations_data.items():
        if key in slug or slug in key:
            return data, ex_obj

    category = ex_obj.category if ex_obj else "General"
    primaries = [ex_obj.primary_muscles] if ex_obj and isinstance(ex_obj.primary_muscles, str) else (ex_obj.primary_muscles if ex_obj and ex_obj.primary_muscles else ["Full Body"])
    secondaries = [ex_obj.secondary_muscles] if ex_obj and isinstance(ex_obj.secondary_muscles, str) else (ex_obj.secondary_muscles if ex_obj and ex_obj.secondary_muscles else ["Core"])

    fallback_config = {
        "exercise_id": slug,
        "name": ex_obj.name if ex_obj else slug.replace('_', ' ').title(),
        "category": category,
        "movement_type": "dynamic",
        "equipment": ex_obj.equipment if ex_obj else "bodyweight",
        "primary_muscles": primaries,
        "secondary_muscles": secondaries,
        "phases": [
            {"name": "Starting Setup", "duration": 0.5},
            {"name": "Active Movement", "duration": 1.2},
            {"name": "Peak Contraction", "duration": 0.4},
            {"name": "Controlled Return", "duration": 1.0}
        ],
        "keyframes": [
            {
                "timestamp": 0.0,
                "phase": "Starting Setup",
                "equipment": {"type": (ex_obj.equipment or "none").lower() if ex_obj else "none", "x": 200, "y": 150},
                "joints": {
                    "head": {"x": 200, "y": 40}, "neck": {"x": 200, "y": 60}, "chest": {"x": 200, "y": 90},
                    "spine": {"x": 200, "y": 120}, "pelvis": {"x": 200, "y": 150},
                    "left_shoulder": {"x": 180, "y": 90}, "left_elbow": {"x": 180, "y": 125}, "left_wrist": {"x": 180, "y": 155},
                    "right_shoulder": {"x": 220, "y": 90}, "right_elbow": {"x": 220, "y": 125}, "right_wrist": {"x": 220, "y": 155},
                    "left_hip": {"x": 185, "y": 150}, "left_knee": {"x": 185, "y": 200}, "left_ankle": {"x": 185, "y": 250},
                    "right_hip": {"x": 215, "y": 150}, "right_knee": {"x": 215, "y": 200}, "right_ankle": {"x": 215, "y": 250}
                },
                "muscle_activations": {p: 0.5 for p in primaries}
            },
            {
                "timestamp": 0.5,
                "phase": "Peak Contraction",
                "equipment": {"type": (ex_obj.equipment or "none").lower() if ex_obj else "none", "x": 200, "y": 120},
                "joints": {
                    "head": {"x": 200, "y": 40}, "neck": {"x": 200, "y": 60}, "chest": {"x": 200, "y": 90},
                    "spine": {"x": 200, "y": 120}, "pelvis": {"x": 200, "y": 150},
                    "left_shoulder": {"x": 180, "y": 90}, "left_elbow": {"x": 170, "y": 110}, "left_wrist": {"x": 180, "y": 120},
                    "right_shoulder": {"x": 220, "y": 90}, "right_elbow": {"x": 230, "y": 110}, "right_wrist": {"x": 220, "y": 120},
                    "left_hip": {"x": 185, "y": 150}, "left_knee": {"x": 185, "y": 200}, "left_ankle": {"x": 185, "y": 250},
                    "right_hip": {"x": 215, "y": 150}, "right_knee": {"x": 215, "y": 200}, "right_ankle": {"x": 215, "y": 250}
                },
                "muscle_activations": {p: 1.0 for p in primaries}
            },
            {
                "timestamp": 1.0,
                "phase": "Starting Setup",
                "equipment": {"type": (ex_obj.equipment or "none").lower() if ex_obj else "none", "x": 200, "y": 150},
                "joints": {
                    "head": {"x": 200, "y": 40}, "neck": {"x": 200, "y": 60}, "chest": {"x": 200, "y": 90},
                    "spine": {"x": 200, "y": 120}, "pelvis": {"x": 200, "y": 150},
                    "left_shoulder": {"x": 180, "y": 90}, "left_elbow": {"x": 180, "y": 125}, "left_wrist": {"x": 180, "y": 155},
                    "right_shoulder": {"x": 220, "y": 90}, "right_elbow": {"x": 220, "y": 125}, "right_wrist": {"x": 220, "y": 155},
                    "left_hip": {"x": 185, "y": 150}, "left_knee": {"x": 185, "y": 200}, "left_ankle": {"x": 185, "y": 250},
                    "right_hip": {"x": 215, "y": 150}, "right_knee": {"x": 215, "y": 200}, "right_ankle": {"x": 215, "y": 250}
                },
                "muscle_activations": {p: 0.5 for p in primaries}
            }
        ]
    }
    return fallback_config, ex_obj


@app.route("/api/exercises/<exercise_id>/animation")
def api_exercise_animation(exercise_id):
    anim_data, ex_obj = get_exercise_animation_data(exercise_id)
    return jsonify({
        "status": "success",
        "exercise_id": exercise_id,
        "name": anim_data.get("name"),
        "animation": anim_data
    })


@app.route("/api/exercises/<exercise_id>/muscles")
def api_exercise_muscles(exercise_id):
    anim_data, ex_obj = get_exercise_animation_data(exercise_id)
    return jsonify({
        "status": "success",
        "exercise_id": exercise_id,
        "primary_muscles": anim_data.get("primary_muscles", []),
        "secondary_muscles": anim_data.get("secondary_muscles", []),
        "engagement_split": {"primary_pct": 80, "secondary_pct": 20}
    })


@app.route("/api/exercises/<exercise_id>/movement")
def api_exercise_movement(exercise_id):
    anim_data, ex_obj = get_exercise_animation_data(exercise_id)
    return jsonify({
        "status": "success",
        "exercise_id": exercise_id,
        "movement_type": anim_data.get("movement_type", "dynamic"),
        "equipment": anim_data.get("equipment", "bodyweight"),
        "phases": anim_data.get("phases", [])
    })


@app.route("/api/exercises/<exercise_id>/animation-config")
def api_exercise_animation_config(exercise_id):
    anim_data, ex_obj = get_exercise_animation_data(exercise_id)
    return jsonify({
        "status": "success",
        "exercise_id": exercise_id,
        "config": {
            "engine": "FitSync_CPlusPlus_WASM_V2",
            "wasm_url": "/static/wasm/animation_engine.wasm",
            "js_fallback": "/static/js/exercise_motion_player.js",
            "animation_data": anim_data
        }
    })


@app.route("/api/ai/search", methods=["POST", "GET"])
def api_ai_search():
    user = get_current_user()
    if request.method == "POST":
        data = request.get_json() or {}
        query = data.get("query", "").strip()
    else:
        query = request.args.get("q", "").strip()

    profile = user.profile if user else None
    result = process_ai_gym_query(query, user_profile=profile)
    return jsonify(result)


@app.route("/api/ai/chat", methods=["POST"])
def api_ai_chat():
    user = get_current_user()
    if not user:
        return jsonify({"status": "error", "message": "Please log in again to use your AI Coach."}), 401

    data = request.get_json() or {}
    message_text = (data.get("message") or data.get("prompt") or "").strip()
    if not message_text:
        return jsonify({"status": "error", "message": "Please enter a message."}), 400

    try:
        conv_id = data.get("conversation_id")
        conv = None
        if conv_id:
            conv = ChatConversation.query.filter_by(id=conv_id, user_id=user.id).first()

        if not conv:
            conv = ChatConversation.query.filter_by(user_id=user.id).order_by(ChatConversation.updated_at.desc()).first()
            if not conv:
                conv = ChatConversation(user_id=user.id, title="FitSync AI Coaching")
                db.session.add(conv)
                db.session.commit()

        # Build recent conversation history
        history_records = ChatMessage.query.filter_by(conversation_id=conv.id).order_by(ChatMessage.id.desc()).limit(10).all()
        history_list = [{"role": m.role, "message": m.message} for m in reversed(history_records)] if history_records else []

        user_msg = ChatMessage(
            conversation_id=conv.id,
            role="user",
            message=message_text
        )
        db.session.add(user_msg)
        db.session.commit()

        result = process_coach_command(user, message_text, app_context=app, history=history_list, db_session=db.session)

        reply_text = result.get("coach_reply") or result.get("message") or "I'm your FitSync Coach. How can I help today?"
        intent = result.get("intent") or result.get("action") or "GENERAL_FITNESS"
        proposed_act = result.get("proposed_action")
        
        def _serialize_item(item):
            if hasattr(item, "to_dict"):
                return item.to_dict()
            if isinstance(item, dict):
                return item
            return str(item)

        raw_exercises = result.get("exercises") or result.get("results") or []
        raw_foods = result.get("foods") or result.get("food_results") or []

        extra_data = {
            "exercises": [_serialize_item(e) for e in raw_exercises],
            "foods": [_serialize_item(f) for f in raw_foods],
            "actions": result.get("actions") or [],
            "action": result.get("action"),
            "proposed_action": proposed_act,
            "explanation": result.get("explanation"),
            "redirect_url": result.get("redirect_url"),
            "suggested_quick_replies": result.get("suggested_quick_replies") or []
        }

        if reply_text:
            assistant_msg = ChatMessage(
                conversation_id=conv.id,
                role="assistant",
                message=reply_text,
                intent=intent,
                extra_data_json=json.dumps(extra_data)
            )
            db.session.add(assistant_msg)
            conv.updated_at = datetime.now(timezone.utc)
            db.session.commit()

        return jsonify({
            "status": "success",
            "success": True,
            "conversation_id": conv.id,
            "message": reply_text,
            "coach_reply": reply_text,
            "intent": intent,
            "action": result.get("action"),
            "proposed_action": proposed_act,
            "explanation": result.get("explanation"),
            "results": extra_data["exercises"],
            "food_results": extra_data["foods"],
            "actions": extra_data["actions"],
            "suggested_quick_replies": extra_data["suggested_quick_replies"],
            "redirect_url": result.get("redirect_url")
        })
    except Exception as e:
        import traceback
        print(f"[API AI CHAT ERROR] {e}")
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"status": "error", "message": "Coach encountered a temporary server problem."}), 500


@app.route("/api/ai/coach", methods=["POST"])
def api_ai_coach():
    return api_ai_chat()


@app.route("/api/ai/conversations", methods=["GET"])
def api_ai_conversations():
    user = get_current_user()
    if not user:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    convs = ChatConversation.query.filter_by(user_id=user.id).order_by(ChatConversation.updated_at.desc()).all()
    res = []
    for c in convs:
        msgs = [m.to_dict() for m in c.messages]
        res.append({
            "id": c.id,
            "title": c.title,
            "updated_at": c.updated_at.strftime("%Y-%m-%d %H:%M:%S") if c.updated_at else "",
            "messages": msgs
        })
    return jsonify({"status": "success", "conversations": res})


@app.route("/api/ai/conversations/clear", methods=["POST"])
def api_ai_clear_conversation():
    user = get_current_user()
    if not user:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    conv_id = data.get("conversation_id")
    if conv_id:
        conv = ChatConversation.query.filter_by(id=conv_id, user_id=user.id).first()
        if conv:
            ChatMessage.query.filter_by(conversation_id=conv.id).delete()
            db.session.commit()
    else:
        convs = ChatConversation.query.filter_by(user_id=user.id).all()
        for c in convs:
            ChatMessage.query.filter_by(conversation_id=c.id).delete()
        db.session.commit()

    return jsonify({"status": "success", "message": "Conversation history cleared"})


@app.route("/api/workout/change-focus", methods=["POST"])
def api_change_focus():
    user = get_current_user()
    if not user or not user.profile:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    new_focus = data.get("focus", "").strip()
    if not new_focus:
        return jsonify({"status": "error", "message": "New focus is required"}), 400

    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()
    if not plan:
        return jsonify({"status": "error", "message": "No active workout plan found"}), 404

    today_name = datetime.now().strftime("%A")
    all_ex = get_exercises_data()
    success, msg, orig_focus = switch_today_focus(plan, today_name, new_focus, user.profile, user.equipments, all_ex, db.session, WorkoutDay, WorkoutExercise)

    if not success:
        return jsonify({"status": "error", "message": msg}), 400

    explanation = f"Switched today's focus to {new_focus} and rebalanced remaining week split."
    return jsonify({"status": "success", "message": msg, "focus": new_focus, "explanation": explanation})


@app.route("/api/workout/day/change-focus", methods=["POST"])
def api_change_day_focus():
    user = get_current_user()
    if not user or not user.profile:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    day_id = data.get("day_id")
    day_name = (data.get("day_name") or "").strip()
    new_focus = (data.get("focus") or "").strip()

    if not new_focus:
        return jsonify({"status": "error", "message": "New workout focus is required (e.g. Chest, Biceps, Back, Shoulders, Legs, Core)."}), 400

    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).order_by(WorkoutPlan.id.desc()).first()
    if not plan:
        return jsonify({"status": "error", "message": "No active workout plan found"}), 404

    target_day = None
    if day_id:
        target_day = WorkoutDay.query.filter_by(id=day_id, workout_plan_id=plan.id).first()
    elif day_name:
        for d in plan.days:
            if d.day_name.lower() == day_name.lower():
                target_day = d
                break
    else:
        today_name = datetime.now().strftime("%A")
        for d in plan.days:
            if d.day_name.lower() == today_name.lower():
                target_day = d
                break

    if not target_day:
        return jsonify({"status": "error", "message": "Specified workout day was not found in plan."}), 404

    all_ex = get_exercises_data()
    allowed_eq = [eq.equipment_name for eq in user.equipments] if user.equipments else None
    matching = filter_exercises_for_focus(all_ex, new_focus, allowed_equipment=allowed_eq)
    if not matching:
        matching = filter_exercises_for_focus(all_ex, new_focus, allowed_equipment=None)
    if not matching:
        matching = all_ex[:5]

    target_day.focus = f"{new_focus.title()} Focus" if not new_focus.lower().endswith("focus") else new_focus.title()
    target_day.is_rest_day = False
    target_day.status = "upcoming"
    target_day.exercises.clear()
    db.session.commit()

    reps_default = "8-10" if user.profile.fitness_goal == "Strength" else ("12-15" if user.profile.fitness_goal == "Fat Loss" else "10-12")
    sets_default = 4 if user.profile.fitness_level == "Advanced" else 3

    for idx, ex in enumerate(matching[:6]):
        inst_str = ex["instructions"] if isinstance(ex["instructions"], str) else "\n".join(ex.get("instructions", []))
        reps_val = ex.get("default_reps") or reps_default
        w_ex = WorkoutExercise(
            workout_day_id=target_day.id,
            exercise_id=int(ex["id"]),
            name=ex["name"],
            category=ex["category"],
            sets=int(ex.get("default_sets") or sets_default),
            reps=str(reps_val),
            reps_min=8,
            reps_max=12,
            rest_seconds=int(ex.get("default_rest") or 60),
            instructions=inst_str,
            start_pos=ex.get("start_pos"),
            movement=ex.get("movement"),
            end_pos=ex.get("end_pos"),
            common_mistakes="\n".join(ex.get("common_mistakes", [])) if isinstance(ex.get("common_mistakes"), list) else ex.get("common_mistakes", ""),
            is_completed=False,
            order_idx=idx
        )
        db.session.add(w_ex)

    db.session.commit()

    return jsonify({
        "status": "success",
        "message": f"Successfully updated {target_day.day_name} to {target_day.focus}!",
        "day_id": target_day.id,
        "day_name": target_day.day_name,
        "focus": target_day.focus,
        "exercises": [e.to_dict() for e in target_day.exercises]
    })


@app.route("/api/workout/generate-custom-today", methods=["POST"])
def api_generate_custom_today():
    user = get_current_user()
    if not user or not user.profile:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    focus = data.get("focus", "").strip()
    if not focus:
        return jsonify({"status": "error", "message": "Workout focus is required (e.g. Biceps, Chest, Back, Legs)."}), 400

    duration_mins = int(data.get("duration_mins") or data.get("duration_minutes") or data.get("duration") or 45)
    env_override = data.get("environment") or user.profile.workout_environment or "Gym"

    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).order_by(WorkoutPlan.id.desc()).first()
    if not plan:
        # Create a new workout plan if not present
        plan = WorkoutPlan(user_id=user.id, is_active=True)
        db.session.add(plan)
        db.session.commit()

    today_name = datetime.now().strftime("%A")
    today_w = WorkoutDay.query.filter_by(workout_plan_id=plan.id, day_name=today_name).order_by(WorkoutDay.id.desc()).first()
    if not today_w:
        today_w = WorkoutDay(workout_plan_id=plan.id, day_name=today_name, day_number=1, focus=focus, is_rest_day=False, status="upcoming")
        db.session.add(today_w)
        db.session.commit()

    all_ex = get_exercises_data()
    success, msg, exercises = generate_custom_today_workout(
        plan, today_name, focus, duration_mins, env_override,
        user.profile, user.equipments, all_ex, db.session,
        WorkoutDay, WorkoutExercise
    )

    if not success:
        return jsonify({"status": "error", "message": msg}), 400

    return jsonify({
        "status": "success",
        "message": msg,
        "focus": focus,
        "duration_minutes": duration_mins,
        "exercises": exercises
    })


@app.route("/api/workout/adjust-duration", methods=["POST"])
def api_adjust_duration():
    user = get_current_user()
    if not user or not user.profile:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    duration_mins = int(data.get("duration_minutes") or data.get("duration_mins") or data.get("duration") or 30)

    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()
    if not plan:
        return jsonify({"status": "error", "message": "No active plan found"}), 404

    today_name = datetime.now().strftime("%A")
    today_w = WorkoutDay.query.filter_by(workout_plan_id=plan.id, day_name=today_name).first()
    if not today_w or today_w.is_rest_day:
        today_w = next((d for d in plan.days if not d.is_rest_day), plan.days[0] if plan.days else None)

    if not today_w:
        return jsonify({"status": "error", "message": "No active workout day found."}), 400

    scale_workout_duration(today_w, duration_mins, db.session, WorkoutExercise)
    user.profile.workout_duration_mins = duration_mins
    db.session.commit()

    return jsonify({"status": "success", "message": f"Adjusted today's workout to {duration_mins} minutes.", "duration_minutes": duration_mins})


@app.route("/api/workout/adjust-difficulty", methods=["POST"])
def api_adjust_difficulty():
    user = get_current_user()
    if not user or not user.profile:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    direction = data.get("direction", "easier")

    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()
    if not plan:
        return jsonify({"status": "error", "message": "No active plan found"}), 404

    today_name = datetime.now().strftime("%A")
    today_w = WorkoutDay.query.filter_by(workout_plan_id=plan.id, day_name=today_name).first()
    if not today_w or today_w.is_rest_day:
        today_w = next((d for d in plan.days if not d.is_rest_day), plan.days[0] if plan.days else None)

    if not today_w:
        return jsonify({"status": "error", "message": "No active workout day found."}), 400

    scale_workout_difficulty(today_w, direction, db.session)
    return jsonify({"status": "success", "message": f"Scaled today's workout intensity ({direction}).", "direction": direction})


@app.route("/api/diet/generate", methods=["POST"])
@app.route("/api/diet/regenerate", methods=["POST"])
def api_generate_ai_diet():
    user = get_current_user()
    if not user or not user.profile:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    targets = NutritionTarget.query.filter_by(user_id=user.id).first()
    if not targets:
        macros = calculate_ai_targets(user.profile)
        targets = NutritionTarget(
            user_id=user.id,
            calories=macros["calories"],
            protein=macros["protein"],
            carbs=macros["carbs"],
            fat=macros["fat"]
        )
        db.session.add(targets)
        db.session.commit()

    all_foods = get_all_user_foods(user)
    today_str = datetime.now().strftime("%Y-%m-%d")

    ai_result = generate_ai_diet_plan(user.profile, user.food_preferences, targets, all_foods, today_str)

    MealPlan.query.filter_by(user_id=user.id, date=today_str).delete()
    m_plan = MealPlan(
        user_id=user.id,
        date=today_str,
        total_calories=0,
        total_protein=0.0,
        total_carbs=0.0,
        total_fat=0.0,
        total_cost=0
    )
    db.session.add(m_plan)
    db.session.commit()

    cals, prot, carbs, fat, cost = 0, 0.0, 0.0, 0.0, 0
    for m in ai_result["meals"]:
        meal = Meal(
            meal_plan_id=m_plan.id,
            meal_type=m["meal_type"],
            food_id=m["food_id"],
            food_name=m["food_name"],
            serving_size_g=m["serving_size_g"],
            calories=m["calories"],
            protein=m["protein"],
            carbs=m["carbs"],
            fat=m["fat"],
            cost=m.get("cost", 0),
            common_unit=m["common_unit"]
        )
        db.session.add(meal)
        cals += m["calories"]
        prot += m["protein"]
        carbs += m["carbs"]
        fat += m["fat"]
        cost += m.get("cost", 0)

    m_plan.total_calories = cals
    m_plan.total_protein = round(prot, 1)
    m_plan.total_carbs = round(carbs, 1)
    m_plan.total_fat = round(fat, 1)
    m_plan.total_cost = cost
    db.session.commit()

    progress = ProgressRecord.query.filter_by(user_id=user.id, date=today_str).first()
    if progress:
        progress.calories_consumed = cals
        progress.protein_consumed = round(prot, 1)
        progress.carbs_consumed = round(carbs, 1)
        progress.fat_consumed = round(fat, 1)
        db.session.commit()

    ai_result["total_calories"] = cals
    ai_result["total_protein"] = round(prot, 1)
    ai_result["total_cost"] = cost
    return jsonify(ai_result)

# -----------------------------------------------------------------------------
# POST / ACTION ROUTES (AJAX CONTROLLERS)
# -----------------------------------------------------------------------------

@app.route("/api/workout/exercise/toggle-complete", methods=["POST"])
def api_toggle_exercise():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.json
    ex_id = data.get("id")
    ex = db.session.get(WorkoutExercise, ex_id)
    if not ex or ex.workout_day.plan.user_id != user.id:
        return jsonify({"status": "error", "message": "Exercise not found"}), 404
        
    ex.is_completed = not ex.is_completed
    db.session.commit()
    
    # Recalculate day completion
    day = ex.workout_day
    all_done = all([e.is_completed for e in day.exercises])
    day.is_completed = all_done
    db.session.commit()
    
    # Sync progress record
    today_str = datetime.now().strftime("%Y-%m-%d")
    progress = ProgressRecord.query.filter_by(user_id=user.id, date=today_str).first()
    if not progress:
        progress = ProgressRecord(user_id=user.id, date=today_str)
        db.session.add(progress)
    
    completed_days_count = WorkoutDay.query.join(WorkoutPlan).filter(
        WorkoutPlan.user_id == user.id,
        WorkoutDay.is_completed == True
    ).count()
    progress.workouts_completed = completed_days_count
    db.session.commit()
    
    return jsonify({"status": "success", "is_completed": ex.is_completed, "day_completed": day.is_completed})


@app.route("/api/workout/exercise/substitute", methods=["POST"])
def api_substitute_exercise():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.json or {}
    ex_id = data.get("id") or data.get("exercise_id")
    new_ex_id = data.get("new_exercise_id")
    reason = data.get("reason", "")

    orig_ex = db.session.get(WorkoutExercise, ex_id)
    if not orig_ex or orig_ex.workout_day.plan.user_id != user.id:
        return jsonify({"status": "error", "message": "Exercise not found"}), 404

    if new_ex_id:
        new_master = db.session.get(Exercise, new_ex_id)
        if new_master:
            orig_ex.exercise_id = new_master.id
            orig_ex.name = new_master.name
            orig_ex.category = new_master.category
            orig_ex.instructions = new_master.instructions
            db.session.commit()
            return jsonify({"status": "success", "message": f"Substituted with {new_master.name}", "exercise": orig_ex.to_dict()})

    equipments = [eq.equipment_name for eq in user.equipments]
    all_ex = get_exercises_data()

    goal = user.profile.fitness_goal if user.profile else None
    level = user.profile.fitness_level if user.profile else None
    env = user.profile.workout_environment if user.profile else None

    alt = find_alternative_exercise(orig_ex.category, orig_ex.exercise_id, equipments, all_ex,
                                     goal=goal, fitness_level=level, workout_environment=env)
    if not alt:
        return jsonify({"status": "error", "message": "No suitable alternative found."}), 404

    inst_str = alt["instructions"] if isinstance(alt["instructions"], str) else "\n".join(alt.get("instructions", []))
    mistakes_str = alt.get("common_mistakes", "")
    if isinstance(mistakes_str, list):
        mistakes_str = "\n".join(mistakes_str)

    orig_ex.exercise_id = int(alt["id"])
    orig_ex.name = alt["name"]
    orig_ex.category = alt["category"]
    orig_ex.instructions = inst_str
    orig_ex.start_pos = alt.get("start_pos")
    orig_ex.movement = alt.get("movement")
    orig_ex.end_pos = alt.get("end_pos")
    orig_ex.common_mistakes = mistakes_str
    orig_ex.is_completed = False
    db.session.commit()

    return jsonify({"status": "success", "replacement": alt["name"], "replacement_id": alt["id"]})


@app.route("/api/workout/rebuild", methods=["POST"])
def api_rebuild_week():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401

    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()
    if not plan:
        return jsonify({"status": "error", "message": "No active plan."}), 404

    missed_day = None
    for day in sorted(plan.days, key=lambda d: d.day_number or 0):
        if not day.is_completed and not day.is_rest_day:
            missed_day = day
            break

    if not missed_day:
        return jsonify({"status": "no_change", "detail": "All workouts are already completed."})

    success = rebuild_remaining_week_logic(plan, missed_day.id, WorkoutExercise)
    if success:
        db.session.commit()
        return jsonify({"status": "success", "detail": f"Shifted missed workout from {missed_day.day_name} to a later rest day."})

    return jsonify({"status": "error", "message": "Could not reschedule week. Ensure you have available rest days."}), 400


@app.route("/api/workout/skip", methods=["POST"])
def api_skip_workout():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.json or {}
    day_id = data.get("day_id")
    if not day_id:
        return jsonify({"status": "error", "message": "day_id required"}), 400

    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()
    if not plan:
        return jsonify({"status": "error", "message": "No active plan."}), 404

    success, message = skip_workout_logic(plan, day_id)
    if success:
        db.session.commit()
        return jsonify({"status": "success", "message": message})
    return jsonify({"status": "error", "message": message}), 400


@app.route("/api/workout/move", methods=["POST"])
def api_move_workout():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.json or {}
    from_day_id = data.get("from_day_id")
    to_day_id = data.get("to_day_id")
    if not from_day_id or not to_day_id:
        return jsonify({"status": "error", "message": "from_day_id and to_day_id required"}), 400

    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()
    if not plan:
        return jsonify({"status": "error", "message": "No active plan."}), 404

    success, message = move_workout_logic(plan, from_day_id, to_day_id, WorkoutExercise)
    if success:
        db.session.commit()
        return jsonify({"status": "success", "message": message})
    return jsonify({"status": "error", "message": message}), 400


@app.route("/api/workout/regenerate", methods=["POST"])
def api_regenerate_plan():
    user = get_current_user()
    if not user or not user.profile:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    try:
        data = request.get_json() or {}
        new_env = data.get("environment")
        if new_env:
            user.profile.workout_environment = new_env
            db.session.commit()

        # Soft-delete old plan
        old_plans = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).all()
        for old in old_plans:
            old.is_active = False
        db.session.commit()

        # Generate new plan
        all_exercises = get_exercises_data()
        equipment_list = [eq.equipment_name for eq in user.equipments]
        weekly_workout = generate_weekly_workout(user.profile, equipment_list, all_exercises)
        if not weekly_workout:
            raise ValueError("Failed to generate weekly workout plan.")

        w_plan = WorkoutPlan(user_id=user.id, is_active=True)
        db.session.add(w_plan)
        db.session.commit()

        valid_ex_ids = {e[0] for e in db.session.query(Exercise.id).all()}
        for day in weekly_workout:
            w_day = WorkoutDay(
                workout_plan_id=w_plan.id,
                day_name=day["day_name"],
                day_number=day.get("day_number", 1),
                focus=day["focus"],
                is_completed=False,
                is_rest_day=day["is_rest_day"],
                status="rest" if day["is_rest_day"] else "upcoming",
                duration_minutes=day.get("duration_minutes", 0)
            )
            db.session.add(w_day)
            db.session.commit()

            for idx, ex in enumerate(day["exercises"]):
                target_ex_id = ex.get("exercise_id")
                if target_ex_id is not None:
                    try:
                        target_ex_id = int(target_ex_id)
                        if target_ex_id not in valid_ex_ids:
                            target_ex_id = None
                    except (ValueError, TypeError):
                        target_ex_id = None

                w_ex = WorkoutExercise(
                    workout_day_id=w_day.id,
                    exercise_id=target_ex_id,
                    name=ex["name"],
                    category=ex["category"],
                    sets=ex["sets"],
                    reps=ex["reps"],
                    reps_min=ex.get("reps_min", 8),
                    reps_max=ex.get("reps_max", 12),
                    rest_seconds=ex["rest_seconds"],
                    instructions=ex["instructions"],
                    start_pos=ex.get("start_pos"),
                    movement=ex.get("movement"),
                    end_pos=ex.get("end_pos"),
                    common_mistakes=ex.get("common_mistakes"),
                    is_completed=False,
                    order_idx=idx
                )
                db.session.add(w_ex)
        db.session.commit()
        return jsonify({"status": "success", "message": "Your workout plan has been regenerated!"})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Regenerate plan error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Could not regenerate plan: {str(e)}"}), 500


@app.route("/api/workout/history", methods=["GET"])
def api_workout_history():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401

    # Gather completed workouts from CompletedWorkout model
    cw_list = CompletedWorkout.query.filter_by(user_id=user.id).order_by(CompletedWorkout.id.desc()).limit(20).all()
    history = []
    for cw in cw_list:
        history.append({"date": cw.date, "workout_name": cw.workout_name})

    # Also gather from completed WorkoutDay in active plan
    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()
    plan_history = []
    if plan:
        for day in plan.days:
            if day.is_completed and not day.is_rest_day and "Skipped" not in (day.focus or ""):
                plan_history.append({
                    "day_name": day.day_name,
                    "focus": day.focus,
                    "exercise_count": len(day.exercises),
                    "duration_minutes": day.duration_minutes or 0,
                    "status": day.status or "completed"
                })

    return jsonify({
        "status": "success",
        "history": history,
        "plan_summary": plan_history
    })


@app.route("/api/workout/ai-query", methods=["POST"])
def api_workout_ai_query():
    user = get_current_user()
    data = request.get_json() or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"status": "error", "message": "Query is required"}), 400

    profile = user.profile if user else None

    # Inject workout context into query
    context_prefix = ""
    if profile:
        context_prefix = f"User goal: {profile.fitness_goal}, Level: {profile.fitness_level}. "
    enriched_query = context_prefix + query

    result = process_ai_gym_query(enriched_query, user_profile=profile)
    return jsonify(result)


@app.route("/api/profile/update-metrics", methods=["POST"])
def api_update_physical_metrics():
    user = get_current_user()
    if not user:
        return jsonify({"status": "error", "message": "Please log in to update physical metrics."}), 401

    data = request.get_json() or {}
    profile = user.profile
    if not profile:
        profile = UserProfile(user_id=user.id)
        db.session.add(profile)

    try:
        # Validate & update height
        if "height" in data and data["height"] is not None:
            try:
                h = float(data["height"])
                if h < 50 or h > 260:
                    return jsonify({"status": "error", "message": "Height must be between 50 cm and 260 cm."}), 400
                profile.height = h
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": "Invalid height format."}), 400

        # Validate & update weight
        weight_changed = False
        if "weight" in data and data["weight"] is not None:
            try:
                w = float(data["weight"])
                if w < 20 or w > 400:
                    return jsonify({"status": "error", "message": "Weight must be between 20 kg and 400 kg."}), 400
                if profile.weight != w:
                    weight_changed = True
                profile.weight = w
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": "Invalid weight format."}), 400

        # Validate & update age
        if "age" in data and data["age"] is not None:
            try:
                a = int(data["age"])
                if a < 10 or a > 120:
                    return jsonify({"status": "error", "message": "Age must be between 10 and 120."}), 400
                profile.age = a
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": "Invalid age format."}), 400

        # Update gender
        if "gender" in data and data["gender"]:
            g = str(data["gender"]).strip().capitalize()
            if g in ["Male", "Female", "Other"]:
                profile.gender = g

        # Update fitness goal
        if "fitness_goal" in data and data["fitness_goal"]:
            profile.fitness_goal = str(data["fitness_goal"]).strip()

        # Update fitness level
        if "fitness_level" in data and data["fitness_level"]:
            profile.fitness_level = str(data["fitness_level"]).strip()

        # Update workout environment
        if "workout_environment" in data and data["workout_environment"]:
            profile.workout_environment = str(data["workout_environment"]).strip()

        # Update workout days/duration if provided
        if "workout_days_per_week" in data and data["workout_days_per_week"]:
            try:
                profile.workout_days_per_week = max(1, min(7, int(data["workout_days_per_week"])))
            except (ValueError, TypeError):
                pass

        if "workout_duration_mins" in data and data["workout_duration_mins"]:
            try:
                profile.workout_duration_mins = max(15, min(180, int(data["workout_duration_mins"])))
            except (ValueError, TypeError):
                pass

        profile.updated_at = datetime.utcnow()

        # Recalculate nutrition targets automatically
        macros = calculate_ai_targets(profile)
        targets = NutritionTarget.query.filter_by(user_id=user.id).first()
        if not targets:
            targets = NutritionTarget(user_id=user.id)
            db.session.add(targets)
        targets.calories = macros["calories"]
        targets.protein = macros["protein"]
        targets.carbs = macros["carbs"]
        targets.fat = macros["fat"]
        targets.is_custom = False

        # Log new weight in ProgressRecord for progress tracking
        today_str = datetime.now().strftime("%Y-%m-%d")
        existing_prog = ProgressRecord.query.filter_by(user_id=user.id, date=today_str).first()
        if existing_prog:
            existing_prog.weight = profile.weight
        else:
            db.session.add(ProgressRecord(
                user_id=user.id,
                date=today_str,
                weight=profile.weight,
                calories_consumed=targets.calories
            ))

        db.session.commit()

        # Calculate updated BMI
        h_m = profile.height / 100.0 if profile.height else 1.75
        bmi_val = round(profile.weight / (h_m * h_m), 1) if h_m > 0 else 0
        if bmi_val < 18.5:
            bmi_label = "Underweight"
            bmi_color = "text-amber-400"
        elif 25.0 <= bmi_val < 30.0:
            bmi_label = "Overweight"
            bmi_color = "text-amber-400"
        elif bmi_val >= 30.0:
            bmi_label = "Obese"
            bmi_color = "text-rose-400"
        else:
            bmi_label = "Normal"
            bmi_color = "text-emerald-400"

        return jsonify({
            "status": "success",
            "message": "Physical metrics updated successfully! Daily targets and BMI have been recalibrated.",
            "profile": {
                "height": profile.height,
                "weight": profile.weight,
                "age": profile.age,
                "gender": profile.gender,
                "fitness_goal": profile.fitness_goal,
                "fitness_level": profile.fitness_level,
                "workout_environment": profile.workout_environment,
                "bmi": bmi_val,
                "bmi_label": bmi_label,
                "bmi_color": bmi_color
            },
            "nutrition_targets": macros
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Failed to update physical metrics: {str(e)}"}), 500


@app.route("/api/profile/save", methods=["POST"])
def api_save_profile():
    user = get_current_user()
    if not user:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    data = request.json or {}
    try:
        profile = UserProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            profile = UserProfile(user_id=user.id)
            db.session.add(profile)
        profile.onboarding_completed = True
        session['is_onboarded'] = True
            
        # Update core profile attributes if passed
        if "name" in data and data["name"]:
            user.name = str(data["name"]).strip()
            profile.name = str(data["name"]).strip()
        if "age" in data and data["age"]:
            profile.age = int(data["age"])
        if "gender" in data and data["gender"]:
            profile.gender = str(data["gender"])
        if "height" in data and data["height"]:
            profile.height = float(data["height"])
        if "weight" in data and data["weight"]:
            profile.weight = float(data["weight"])
        if "fitness_goal" in data and data["fitness_goal"]:
            profile.fitness_goal = str(data["fitness_goal"])
        if "fitness_level" in data and data["fitness_level"]:
            profile.fitness_level = str(data["fitness_level"])
        if "workout_days_per_week" in data and data["workout_days_per_week"]:
            profile.workout_days_per_week = int(data["workout_days_per_week"])
        if "workout_duration_mins" in data and data["workout_duration_mins"]:
            profile.workout_duration_mins = int(data["workout_duration_mins"])
        if "workout_environment" in data and data["workout_environment"]:
            profile.workout_environment = str(data["workout_environment"])
        if "dietary_preference" in data and data["dietary_preference"]:
            profile.dietary_preference = str(data["dietary_preference"])

        if "equipments" in data and isinstance(data["equipments"], list):
            UserEquipment.query.filter_by(user_id=user.id).delete()
            for eq in data["equipments"]:
                db.session.add(UserEquipment(user_id=user.id, equipment_name=eq))

        # Parse and validate daily food budget if passed
        budget_val = data.get("daily_food_budget")
        if budget_val is not None:
            try:
                val = int(str(budget_val).strip())
                if val <= 0:
                    return jsonify({"status": "error", "message": "Please enter a valid daily food budget (must be greater than 0)."}), 400
                profile.daily_food_budget = val
                profile.budget_preference = f"₹{val}"
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": "Please enter a valid daily food budget."}), 400
        elif "name" not in data:
            return jsonify({"status": "error", "message": "Daily food budget is required."}), 400

        # Save food preferences
        if "food_preferences" in data and isinstance(data["food_preferences"], list):
            UserFoodPreference.query.filter_by(user_id=user.id).delete()
            for pref in data.get("food_preferences", []):
                db.session.add(UserFoodPreference(
                    user_id=user.id,
                    food_name=pref["food_name"],
                    is_preferred=pref.get("is_preferred", False),
                    is_available=pref.get("is_available", False),
                    is_avoided=pref.get("is_avoided", False)
                ))
            
        # Update macro targets based on updated profile
        macros = calculate_ai_targets(profile)
        targets = NutritionTarget.query.filter_by(user_id=user.id).first()
        if not targets:
            targets = NutritionTarget(user_id=user.id)
            db.session.add(targets)
        targets.calories = macros["calories"]
        targets.protein = macros["protein"]
        targets.carbs = macros["carbs"]
        targets.fat = macros["fat"]

        db.session.commit()
        
        # Regenerate daily meal plan for today
        today_str = datetime.now().strftime("%Y-%m-%d")
        MealPlan.query.filter_by(user_id=user.id, date=today_str).delete()
        
        all_foods = get_all_user_foods(user)
        daily_meals = generate_daily_meals(profile, user.food_preferences, targets, all_foods, today_str)
        m_plan = MealPlan(
            user_id=user.id,
            date=today_str,
            total_calories=0,
            total_protein=0.0,
            total_carbs=0.0,
            total_fat=0.0,
            total_cost=0
        )
        db.session.add(m_plan)
        db.session.commit()

        cals, prot, carbs, fat, cost = 0, 0.0, 0.0, 0.0, 0
        for m in daily_meals:
            meal = Meal(
                meal_plan_id=m_plan.id,
                meal_type=m["meal_type"],
                food_id=m["food_id"],
                food_name=m["food_name"],
                serving_size_g=m["serving_size_g"],
                calories=m["calories"],
                protein=m["protein"],
                carbs=m["carbs"],
                fat=m["fat"],
                cost=m.get("cost", 0),
                common_unit=m["common_unit"]
            )
            db.session.add(meal)
            cals += m["calories"]
            prot += m["protein"]
            carbs += m["carbs"]
            fat += m["fat"]
            cost += m.get("cost", 0)

        m_plan.total_calories = cals
        m_plan.total_protein = round(prot, 1)
        m_plan.total_carbs = round(carbs, 1)
        m_plan.total_fat = round(fat, 1)
        m_plan.total_cost = cost
        
        db.session.commit()
        return jsonify({"status": "success", "message": "Profile updated successfully."})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Unable to update profile: {str(e)}"}), 500


@app.route("/api/nutrition/meal/substitute", methods=["POST"])
def api_substitute_meal():
    user = get_current_user()
    if not user or not user.profile: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.json or {}
    meal_id = data.get("id") or data.get("meal_id")
    new_food_id = data.get("new_food_id") or data.get("food_id")
    
    meal = db.session.get(Meal, meal_id)
    if not meal or meal.meal_plan.user_id != user.id:
        return jsonify({"status": "error", "message": "Meal item not found"}), 404

    if new_food_id:
        food = db.session.get(Food, new_food_id)
        if food:
            meal.food_id = food.id
            meal.food_name = food.name
            meal.calories = food.calories
            meal.protein = food.protein
            meal.carbs = food.carbs
            meal.fat = food.fat
            meal.cost = getattr(food, 'cost_approx', getattr(food, 'cost', 0))
            db.session.commit()
            return jsonify({
                "status": "success",
                "message": f"Swapped to {food.name}",
                "meal": {
                    "id": meal.id,
                    "meal_type": meal.meal_type,
                    "food_id": meal.food_id,
                    "food_name": meal.food_name,
                    "calories": meal.calories,
                    "protein": meal.protein,
                    "carbs": meal.carbs,
                    "fat": meal.fat,
                    "cost": meal.cost
                }
            })

    all_foods = get_all_user_foods(user)
    alt = get_food_alternative(
        meal.food_id,
        meal.calories,
        meal.protein,
        user.profile.dietary_preference,
        user.profile.daily_food_budget,
        all_foods,
        user.food_preferences
    )
    if not alt:
        return jsonify({"status": "error", "message": "No alternative food found matching dietary type."}), 404

    meal_plan = meal.meal_plan
    # Adjust targets and cost
    meal_plan.total_calories = int(meal_plan.total_calories - meal.calories + alt["calories"])
    meal_plan.total_protein = round(meal_plan.total_protein - meal.protein + alt["protein"], 1)
    meal_plan.total_carbs = round(meal_plan.total_carbs - meal.carbs + alt["carbs"], 1)
    meal_plan.total_fat = round(meal_plan.total_fat - meal.fat + alt["fat"], 1)
    
    old_cost = meal.cost or 0
    meal.cost = alt.get("cost", 0)
    meal_plan.total_cost = int((meal_plan.total_cost or 0) - old_cost + meal.cost)

    meal.food_id = alt["food_id"]
    meal.food_name = alt["name"]
    meal.serving_size_g = alt["serving_size_g"]
    meal.calories = alt["calories"]
    meal.protein = alt["protein"]
    meal.carbs = alt["carbs"]
    meal.fat = alt["fat"]
    meal.common_unit = alt["common_unit"]
    db.session.commit()

    # Sync progress record
    today_str = datetime.now().strftime("%Y-%m-%d")
    progress = ProgressRecord.query.filter_by(user_id=user.id, date=today_str).first()
    if progress:
        progress.calories_consumed = meal_plan.total_calories
        progress.protein_consumed = meal_plan.total_protein
        progress.carbs_consumed = meal_plan.total_carbs
        progress.fat_consumed = meal_plan.total_fat
        db.session.commit()

    return jsonify({"status": "success", "replacement": alt["name"]})


@app.route("/api/nutrition/available-foods", methods=["GET"])
def api_get_available_foods():
    user = get_current_user()
    if not user:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    all_foods = get_all_user_foods(user)
    user_prefs = {p.food_name.lower(): p for p in (user.food_preferences or [])}

    enriched = []
    for f in all_foods:
        f_key = f["name"].lower()
        pref_obj = user_prefs.get(f_key)
        enriched.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "category": f.get("category", "General"),
            "serving_size_g": f.get("serving_size_g", 100),
            "calories": f.get("calories", 0),
            "protein": f.get("protein", 0),
            "carbs": f.get("carbs", 0),
            "fat": f.get("fat", 0),
            "cost": f.get("cost_approx", f.get("cost", 0)),
            "common_unit": f.get("common_unit", f"{f.get('serving_size_g', 100)}g"),
            "is_preferred": bool(pref_obj.is_preferred) if pref_obj else False,
            "is_available": bool(pref_obj.is_available) if pref_obj else True,
            "is_avoided": bool(pref_obj.is_avoided) if pref_obj else False,
            "is_custom": bool(f.get("is_custom", False))
        })

    return jsonify({
        "status": "success",
        "foods": enriched,
        "total": len(enriched)
    })


@app.route("/api/nutrition/select-food-for-meal", methods=["POST"])
def api_select_food_for_meal():
    user = get_current_user()
    if not user or not user.profile:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.json or {}
    meal_id = data.get("meal_id") or data.get("id")
    food_name = data.get("food_name", "").strip()
    custom_serving = data.get("serving_size_g")

    if not meal_id or not food_name:
        return jsonify({"status": "error", "message": "Meal ID and food name are required"}), 400

    meal = Meal.query.get(meal_id)
    if not meal or meal.meal_plan.user_id != user.id:
        return jsonify({"status": "error", "message": "Meal item not found"}), 404

    all_foods = get_all_user_foods(user)
    target_food = next((f for f in all_foods if f["name"].lower() == food_name.lower()), None)
    if not target_food:
        cf = CustomFood.query.filter_by(user_id=user.id).filter(func.lower(CustomFood.name) == food_name.lower()).first()
        if cf:
            target_food = {
                "id": f"cf_{cf.id}",
                "name": cf.name,
                "category": cf.category,
                "serving_size_g": cf.serving_size_g,
                "calories": cf.calories,
                "protein": cf.protein,
                "carbs": cf.carbs,
                "fat": cf.fat,
                "cost_approx": cf.cost,
                "common_unit": f"{cf.serving_size_g}g serving",
                "is_custom": True
            }

    if not target_food:
        return jsonify({"status": "error", "message": f"Food '{food_name}' not found in database or custom catalog."}), 404

    meal_plan = meal.meal_plan
    old_cals = meal.calories
    old_prot = meal.protein
    old_carbs = meal.carbs
    old_fat = meal.fat
    old_cost = meal.cost or 0

    updated_meal_data = swap_meal_with_chosen_food(meal, target_food, custom_serving)

    # Recalculate meal plan totals
    meal_plan.total_calories = max(0, int(meal_plan.total_calories - old_cals + meal.calories))
    meal_plan.total_protein = max(0.0, round(meal_plan.total_protein - old_prot + meal.protein, 1))
    meal_plan.total_carbs = max(0.0, round(meal_plan.total_carbs - old_carbs + meal.carbs, 1))
    meal_plan.total_fat = max(0.0, round(meal_plan.total_fat - old_fat + meal.fat, 1))
    meal_plan.total_cost = max(0, int((meal_plan.total_cost or 0) - old_cost + (meal.cost or 0)))
    db.session.commit()

    today_str = datetime.now().strftime("%Y-%m-%d")
    progress = ProgressRecord.query.filter_by(user_id=user.id, date=today_str).first()
    if progress:
        progress.calories_consumed = meal_plan.total_calories
        progress.protein_consumed = meal_plan.total_protein
        progress.carbs_consumed = meal_plan.total_carbs
        progress.fat_consumed = meal_plan.total_fat
        db.session.commit()

    return jsonify({
        "status": "success",
        "message": f"Meal updated to {meal.food_name}",
        "meal": updated_meal_data,
        "meal_plan_totals": {
            "total_calories": meal_plan.total_calories,
            "total_protein": meal_plan.total_protein,
            "total_carbs": meal_plan.total_carbs,
            "total_fat": meal_plan.total_fat,
            "total_cost": meal_plan.total_cost
        }
    })


@app.route("/api/nutrition/targets", methods=["POST"])
def api_update_targets():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.json
    targets = NutritionTarget.query.filter_by(user_id=user.id).first()
    if not targets:
        targets = NutritionTarget(user_id=user.id)
        db.session.add(targets)
        
    targets.calories = int(data.get("calories"))
    targets.protein = float(data.get("protein"))
    targets.carbs = float(data.get("carbs"))
    targets.fat = float(data.get("fat"))
    targets.is_custom = True
    db.session.commit()
    
    return jsonify({"status": "success"})


@app.route("/api/progress/log", methods=["POST"])
def api_log_progress():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.json
    date_str = data.get("date")
    weight = data.get("weight")
    
    rec = ProgressRecord.query.filter_by(user_id=user.id, date=date_str).first()
    if not rec:
        rec = ProgressRecord(user_id=user.id, date=date_str)
        db.session.add(rec)
        
    if weight is not None:
        rec.weight = float(weight)
        if user.profile:
            user.profile.weight = float(weight)
            
    db.session.commit()
    return jsonify({"status": "success"})


@app.route("/api/progress/history")
def api_progress_history():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    records = ProgressRecord.query.filter_by(user_id=user.id).order_by(ProgressRecord.date.asc()).all()
    history_list = []
    for r in records:
        history_list.append({
            "date": r.date,
            "weight": r.weight,
            "calories_consumed": r.calories_consumed,
            "protein_consumed": r.protein_consumed,
            "carbs_consumed": r.carbs_consumed,
            "fat_consumed": r.fat_consumed,
            "workouts_completed": r.workouts_completed
        })
    return jsonify(history_list)


@app.route("/api/form-analysis", methods=["POST"])
def api_form_analysis():
    data = request.json
    ex_name = data.get("exercise_name")
    frame = data.get("frame_base64")
    
    result = check_exercise_form(ex_name, frame)
    return jsonify(result)

@app.route("/export/report")
@app.route("/api/export/report")
def export_report():
    user = get_current_user()
    if not user:
        flash("Please log in to export your plan report.", "warning")
        return redirect(url_for("login"))
    
    target = NutritionTarget.query.filter_by(user_id=user.id).first()
    plan = WorkoutPlan.query.filter_by(user_id=user.id, is_active=True).first()
    workout_days = plan.days if plan else []
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    meal_plan = MealPlan.query.filter_by(user_id=user.id, date=today_str).first()
    meals = meal_plan.meals if meal_plan else []
    
    return render_template(
        "export_report.html",
        user=user,
        profile=user.profile,
        target=target,
        workout_days=workout_days,
        meals=meals
    )

@app.route("/api/diet/grocery-list")
def api_grocery_list():
    user = get_current_user()
    if not user: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    from services.ai_diet_engine import generate_ai_grocery_list
    today_str = datetime.now().strftime("%Y-%m-%d")
    meal_plan = MealPlan.query.filter_by(user_id=user.id, date=today_str).first()
    meals_list = [m.to_dict() for m in meal_plan.meals] if (meal_plan and meal_plan.meals) else []
    
    result = generate_ai_grocery_list(user.profile, meals_list)
    return jsonify(result)


# -----------------------------------------------------------------------------
# AUTO OPEN DEFAULT BROWSER
# -----------------------------------------------------------------------------
def open_browser():
    time.sleep(1.5)  # Wait for Flask to boot
    webbrowser.open("http://127.0.0.1:5000")

# -----------------------------------------------------------------------------
# MAIN START
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    with app.app_context():
        seed_database()
        
    # Prevent 2 tabs from opening due to Flask Werkzeug reloader process spawning
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=open_browser, daemon=True).start()

    app.run(debug=True)
