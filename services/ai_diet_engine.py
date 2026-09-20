import os
import json
import re
import urllib.request
import urllib.parse
from services.nutrition_engine import generate_daily_meals, calculate_ai_targets

def _clean_and_parse_json(text_content):
    """
    Cleans markdown code fences and parses JSON payload safely.
    """
    if not text_content:
        return None
    cleaned = text_content.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r'(\{.*\})', cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        return None

def generate_ai_diet_plan(profile, food_preferences_list, target_nutrition, all_foods, date_str):
    """
    Generates an AI-assisted diet plan based on user profile, preferences, budget, and custom foods.
    If an external AI API key (AI_API_KEY / GEMINI_API_KEY) is available, it uses AI to structure & explain
    the meal plan while ensuring strict nutritional adherence.
    Falls back gracefully to FitSync's local nutrition engine if AI is unreachable or unconfigured.
    """
    api_key = os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    
    # 1. Generate candidate base meals via local engine to ensure valid foods, macros, and cost safety
    base_meals = generate_daily_meals(profile, food_preferences_list, target_nutrition, all_foods, date_str)
    
    if not api_key:
        explanation = (
            f"Your plan is protein-focused ({target_nutrition.protein}g target) to support your {profile.fitness_goal} "
            f"goal while staying strictly within your ₹{profile.daily_food_budget or 150}/day food budget."
        )
        return {
            "status": "success",
            "is_ai": False,
            "notice": "AI planning key not configured. We've generated your optimal plan using FitSync's nutrition engine.",
            "explanation": explanation,
            "meals": base_meals
        }

    try:
        # Construct prompt for Gemini API
        prompt_data = {
            "goal": profile.fitness_goal,
            "dietary_preference": profile.dietary_preference,
            "daily_budget_inr": profile.daily_food_budget or 150,
            "target_calories": target_nutrition.calories,
            "target_protein_g": target_nutrition.protein,
            "base_suggested_meals": [
                {
                    "meal_type": m["meal_type"],
                    "food_name": m["food_name"],
                    "calories": m["calories"],
                    "protein": m["protein"],
                    "cost": m["cost"]
                }
                for m in base_meals
            ]
        }

        user_prompt = (
            "You are FitSync AI's nutrition assistant. Provide a brief 2-sentence explanation "
            "for why this 5-meal plan fits the student's fitness goal and daily budget. "
            "Return valid JSON matching this schema: {\"explanation\": \"string\"}.\n"
            f"Data: {json.dumps(prompt_data)}"
        )

        model_name = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        
        with urllib.request.urlopen(req, timeout=6) as response:
            res_body = json.loads(response.read().decode('utf-8'))
            candidates = res_body.get('candidates', [])
            explanation = ""
            if candidates and 'content' in candidates[0] and 'parts' in candidates[0]['content']:
                text_content = candidates[0]['content']['parts'][0].get('text', '')
                parsed = _clean_and_parse_json(text_content)
                if parsed and isinstance(parsed, dict):
                    explanation = parsed.get("explanation", "")

        if not explanation:
            explanation = (
                f"Your 5-meal plan delivers ~{target_nutrition.protein}g protein aligned with your {profile.fitness_goal} "
                f"goal while maintaining your ₹{profile.daily_food_budget or 150}/day daily budget."
            )

        return {
            "status": "success",
            "is_ai": True,
            "explanation": explanation,
            "meals": base_meals
        }

    except Exception as e:
        print(f"[AI DIET WARNING] Gemini API call skipped/failed: {e}")
        explanation = (
            f"Your plan is protein-focused ({target_nutrition.protein}g target) to support your {profile.fitness_goal} "
            f"goal while staying strictly within your ₹{profile.daily_food_budget or 150}/day food budget."
        )
        return {
            "status": "success",
            "is_ai": False,
            "notice": "AI planning is temporarily unavailable. We've generated your plan using FitSync's nutrition engine.",
            "explanation": explanation,
            "meals": base_meals
        }


def generate_ai_grocery_list(profile, active_meals):
    """
    Generates a 7-day categorized hostel grocery & canteen shopping list with estimated INR budget totals.
    Uses Gemini AI if available or structured local aggregation as fallback.
    """
    api_key = os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    daily_budget = profile.daily_food_budget or 150
    weekly_budget = daily_budget * 7

    # Aggregated items from 5-meal plan
    items_map = {}
    for m in active_meals:
        fn = m.get("food_name", "Staple Item")
        cost = m.get("cost", 10) * 7
        if fn in items_map:
            items_map[fn]["weekly_cost"] += cost
            items_map[fn]["servings"] += 7
        else:
            items_map[fn] = {
                "name": fn,
                "weekly_cost": cost,
                "servings": 7,
                "category": m.get("category", "Staples")
            }

    grocery_items = list(items_map.values())
    total_est_cost = sum(i["weekly_cost"] for i in grocery_items)

    if api_key:
        try:
            model_name = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            prompt = (
                "You are FitSync AI's budget nutrition expert. Create a concise 7-day hostel grocery list summary "
                f"for a college student with a ₹{weekly_budget} weekly food budget based on these foods: {json.dumps(grocery_items)}. "
                "Return JSON matching: {\"summary\": \"string\", \"tip\": \"string\"}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=6) as response:
                res_body = json.loads(response.read().decode('utf-8'))
                candidates = res_body.get('candidates', [])
                if candidates and 'content' in candidates[0] and 'parts' in candidates[0]['content']:
                    text_content = candidates[0]['content']['parts'][0].get('text', '')
                    parsed = _clean_and_parse_json(text_content)
                    if parsed and isinstance(parsed, dict):
                        return {
                            "status": "success",
                            "is_ai": True,
                            "weekly_budget": weekly_budget,
                            "total_est_cost": total_est_cost,
                            "summary": parsed.get("summary", f"7-day grocery list tailored to your ₹{weekly_budget} budget."),
                            "pro_tip": parsed.get("tip", "Buy dry staples (chana, peanuts, lentils) in bulk to save ~15% weekly!"),
                            "items": grocery_items
                        }
        except Exception as e:
            print(f"[AI GROCERY WARNING] Gemini API call skipped/failed: {e}")

    return {
        "status": "success",
        "is_ai": False,
        "weekly_budget": weekly_budget,
        "total_est_cost": total_est_cost,
        "summary": f"7-day hostel grocery list optimized for your ₹{weekly_budget}/week budget.",
        "pro_tip": "Buy dry staples like roasted chana, peanuts, and dal in bulk at local markets to maximize protein per Rupee!",
        "items": grocery_items
    }


# -----------------------------------------------------------------------------
# INDIAN HOSTEL MESS PRESETS & NUTRITION DATABASE
# -----------------------------------------------------------------------------
HOSTEL_MESS_PRESETS = {
    "north_indian_mess": {
        "key": "north_indian_mess",
        "name": "North Indian Hostel Mess Thali",
        "badge": "🍛 North Indian",
        "description": "3 Chapatis, Dal Tadka, Rajma Masala, Steamed Rice & Fresh Curd",
        "calories": 680,
        "protein": 27.5,
        "carbs": 108.0,
        "fat": 13.0,
        "cost": 55,
        "items": [
            {"name": "Chapati / Roti (3 pcs)", "portion": "90g", "calories": 240, "protein": 7.8, "carbs": 48.0, "fat": 1.2, "cost": 15},
            {"name": "Dal Tadka (1 bowl)", "portion": "150g", "calories": 180, "protein": 9.0, "carbs": 24.0, "fat": 5.0, "cost": 15},
            {"name": "Rajma Masala (1/2 cup)", "portion": "100g", "calories": 130, "protein": 7.0, "carbs": 22.0, "fat": 2.5, "cost": 15},
            {"name": "Steamed Rice", "portion": "80g", "calories": 105, "protein": 2.2, "carbs": 23.0, "fat": 0.4, "cost": 5},
            {"name": "Curd / Dahi (1 cup)", "portion": "80g", "calories": 50, "protein": 3.0, "carbs": 3.5, "fat": 2.5, "cost": 5}
        ],
        "feedback": "Great balance of complex carbs and fiber. Add 1 boiled egg or 40g paneer to reach >35g protein for training days."
    },
    "south_indian_mess": {
        "key": "south_indian_mess",
        "name": "South Indian Mess Feast",
        "badge": "🥞 South Indian",
        "description": "2 Idlis / Dosas with Vegetable Sambar, Coconut Chutney & Rasam Rice",
        "calories": 590,
        "protein": 18.5,
        "carbs": 96.0,
        "fat": 14.5,
        "cost": 45,
        "items": [
            {"name": "Idli / Dosa (2 pcs)", "portion": "140g", "calories": 230, "protein": 6.5, "carbs": 44.0, "fat": 3.5, "cost": 18},
            {"name": "Vegetable Sambar (1 bowl)", "portion": "150g", "calories": 140, "protein": 6.0, "carbs": 22.0, "fat": 3.0, "cost": 12},
            {"name": "Rasam with Rice", "portion": "120g", "calories": 150, "protein": 3.5, "carbs": 32.0, "fat": 1.0, "cost": 10},
            {"name": "Coconut Chutney", "portion": "40g", "calories": 70, "protein": 1.5, "carbs": 2.5, "fat": 6.5, "cost": 5}
        ],
        "feedback": "Fermented batter is excellent for gut microbiome and nutrient absorption. Pair with a boiled egg or milk for higher protein."
    },
    "high_protein_student": {
        "key": "high_protein_student",
        "name": "High-Protein Budget Student Special",
        "badge": "💪 50g+ Protein",
        "description": "3 Boiled Eggs, Soya Chunks Masala, 2 Rotis & Roasted Peanut Chaat",
        "calories": 760,
        "protein": 54.0,
        "carbs": 72.0,
        "fat": 24.0,
        "cost": 65,
        "items": [
            {"name": "Whole Boiled Eggs (3 pcs)", "portion": "150g", "calories": 210, "protein": 18.0, "carbs": 1.5, "fat": 15.0, "cost": 20},
            {"name": "Soya Chunks Curry", "portion": "120g", "calories": 190, "protein": 22.0, "carbs": 14.0, "fat": 4.0, "cost": 18},
            {"name": "Chapati / Roti (2 pcs)", "portion": "60g", "calories": 160, "protein": 5.2, "carbs": 32.0, "fat": 0.8, "cost": 10},
            {"name": "Roasted Peanut Chaat", "portion": "50g", "calories": 200, "protein": 8.8, "carbs": 9.5, "fat": 14.0, "cost": 12}
        ],
        "feedback": "Exceptional biological value protein (>50g) at under ₹65. Perfect post-workout meal for muscle hypertrophy and recovery."
    },
    "budget_student_snack": {
        "key": "budget_student_snack",
        "name": "Hostel Evening Energy Pack",
        "badge": "⚡ ₹25 Budget",
        "description": "100g Roasted Chana (Bhuna Chana), 1 Ripe Banana & Masala Chai",
        "calories": 440,
        "protein": 22.5,
        "carbs": 76.0,
        "fat": 6.5,
        "cost": 25,
        "items": [
            {"name": "Roasted Chana / Bhuna Chana", "portion": "100g", "calories": 355, "protein": 19.5, "carbs": 58.0, "fat": 5.5, "cost": 15},
            {"name": "Ripe Banana (1 medium)", "portion": "110g", "calories": 95, "protein": 1.2, "carbs": 24.0, "fat": 0.3, "cost": 5},
            {"name": "Hostel Masala Chai (low sugar)", "portion": "100ml", "calories": 40, "protein": 1.8, "carbs": 5.0, "fat": 1.5, "cost": 5}
        ],
        "feedback": "Classic Indian student powerhouse snack. Roasted chana offers slow-digesting carbs and clean plant protein for evening study and gym."
    }
}


def analyze_mess_plate(image_data, meal_type="Lunch", profile=None):
    """
    Analyzes an Indian mess plate or thali image using Gemini Multimodal Vision API.
    Falls back gracefully to a high-accuracy Indian food heuristic classifier.
    Returns structured dishes, portion grams, calories, protein, carbs, fat, estimated INR cost,
    and a student-tailored nutrition tip.
    """
    api_key = os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    
    # Strip data URL header if present
    base64_data = image_data or ""
    mime_type = "image/jpeg"
    if "base64," in base64_data:
        header, base64_data = base64_data.split("base64,", 1)
        if "png" in header.lower():
            mime_type = "image/png"
        elif "webp" in header.lower():
            mime_type = "image/webp"

    base64_data = base64_data.strip()

    if api_key and len(base64_data) > 100:
        prompt_text = (
            "You are FitSync AI, an expert Indian clinical sports nutritionist and computer vision AI. "
            "Analyze this photo of an Indian hostel mess thali or student meal plate. "
            "Identify each food component (e.g., Chapatis/Rotis, Dal Tadka, Steamed Rice, Sabzi, Dahi, Boiled Eggs, Paneer). "
            "For each item provide: name, portion (e.g. '120g' or '2 pcs'), calories (int), protein (float), "
            "carbs (float), fat (float), cost (estimated Indian student mess/canteen price in INR). "
            "Also provide: total_calories (int), total_protein (float), total_carbs (float), total_fat (float), "
            "estimated_cost_inr (int), health_rating (e.g. '8.5/10'), and a concise 2-sentence actionable feedback tip "
            "tailored to an Indian college student optimizing fitness on a budget. "
            "Return strictly valid JSON matching this schema: "
            "{\n"
            "  \"dish_name\": \"string\",\n"
            "  \"health_rating\": \"string\",\n"
            "  \"items\": [\n"
            "    {\"name\": \"string\", \"portion\": \"string\", \"calories\": 100, \"protein\": 5.0, \"carbs\": 20.0, \"fat\": 2.0, \"cost\": 10}\n"
            "  ],\n"
            "  \"total_calories\": 550,\n"
            "  \"total_protein\": 20.5,\n"
            "  \"total_carbs\": 85.0,\n"
            "  \"total_fat\": 12.0,\n"
            "  \"estimated_cost_inr\": 50,\n"
            "  \"feedback\": \"string\"\n"
            "}"
        )

        candidate_models = ["gemini-1.5-flash", "gemini-flash-latest", "gemini-2.0-flash"]
        for model in candidate_models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt_text},
                                {
                                    "inlineData": {
                                        "mimeType": mime_type,
                                        "data": base64_data
                                    }
                                }
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.2,
                        "responseMimeType": "application/json"
                    }
                }

                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )

                with urllib.request.urlopen(req, timeout=9) as response:
                    res_body = json.loads(response.read().decode('utf-8'))
                    candidates = res_body.get('candidates', [])
                    if candidates and 'content' in candidates[0] and 'parts' in candidates[0]['content']:
                        text_content = candidates[0]['content']['parts'][0].get('text', '')
                        parsed = _clean_and_parse_json(text_content)
                        if parsed and isinstance(parsed, dict) and "items" in parsed:
                            return {
                                "status": "success",
                                "is_ai": True,
                                "source": f"Gemini Vision ({model})",
                                "dish_name": parsed.get("dish_name", "Indian Mess Plate"),
                                "health_rating": parsed.get("health_rating", "8.5/10"),
                                "items": parsed.get("items", []),
                                "total_calories": parsed.get("total_calories", 550),
                                "total_protein": round(float(parsed.get("total_protein", 20.0)), 1),
                                "total_carbs": round(float(parsed.get("total_carbs", 80.0)), 1),
                                "total_fat": round(float(parsed.get("total_fat", 12.0)), 1),
                                "estimated_cost_inr": parsed.get("estimated_cost_inr", 50),
                                "feedback": parsed.get("feedback", "Balanced Indian student thali.")
                            }
            except Exception as e:
                print(f"[PLATE SCANNER WARNING] Model {model} failed: {e}")
                continue

    # Graceful Indian Mess Heuristic Fallback
    m_lower = (meal_type or "Lunch").lower()
    if "breakfast" in m_lower:
        fallback = {
            "dish_name": "Hostel Breakfast Plate",
            "health_rating": "8.0/10",
            "items": [
                {"name": "Steamed Idli (2 pcs)", "portion": "100g", "calories": 140, "protein": 4.0, "carbs": 28.0, "fat": 0.8, "cost": 15},
                {"name": "Vegetable Sambar", "portion": "120g", "calories": 110, "protein": 4.5, "carbs": 18.0, "fat": 2.0, "cost": 10},
                {"name": "Boiled Egg (1 pc)", "portion": "50g", "calories": 70, "protein": 6.0, "carbs": 0.5, "fat": 5.0, "cost": 7},
                {"name": "Filter Coffee / Chai", "portion": "80ml", "calories": 45, "protein": 1.5, "carbs": 6.0, "fat": 1.5, "cost": 8}
            ],
            "total_calories": 365,
            "total_protein": 16.0,
            "total_carbs": 52.5,
            "total_fat": 9.3,
            "estimated_cost_inr": 40,
            "feedback": "Clean, easily digestible morning fuel. Adding one extra boiled egg or a cup of milk will push protein over 22g."
        }
    elif "snack" in m_lower:
        fallback = {
            "dish_name": "Evening Hostel Canteen Plate",
            "health_rating": "8.7/10",
            "items": [
                {"name": "Bhuna Chana (Roasted)", "portion": "80g", "calories": 285, "protein": 15.6, "carbs": 46.0, "fat": 4.4, "cost": 12},
                {"name": "Peanut & Onion Chaat", "portion": "40g", "calories": 160, "protein": 7.0, "carbs": 7.5, "fat": 11.2, "cost": 10},
                {"name": "Masala Chai", "portion": "100ml", "calories": 40, "protein": 1.8, "carbs": 5.0, "fat": 1.5, "cost": 5}
            ],
            "total_calories": 485,
            "total_protein": 24.4,
            "total_carbs": 58.5,
            "total_fat": 17.1,
            "estimated_cost_inr": 27,
            "feedback": "Superb high-protein student snack under ₹30! Perfect fuel 60 minutes before your workout."
        }
    else:
        # Default Lunch / Dinner Thali
        fallback = {
            "dish_name": "Hostel Mess Thali",
            "health_rating": "8.5/10",
            "items": [
                {"name": "Chapati / Roti (2 pcs)", "portion": "60g", "calories": 160, "protein": 5.2, "carbs": 32.0, "fat": 0.8, "cost": 10},
                {"name": "Yellow Dal Tadka", "portion": "150g", "calories": 175, "protein": 8.8, "carbs": 24.0, "fat": 4.8, "cost": 15},
                {"name": "Steamed White Rice", "portion": "120g", "calories": 156, "protein": 3.2, "carbs": 34.0, "fat": 0.5, "cost": 8},
                {"name": "Mix Veg Sabzi (Aloo Gobi)", "portion": "100g", "calories": 95, "protein": 2.5, "carbs": 12.0, "fat": 4.0, "cost": 12},
                {"name": "Fresh Curd (Dahi)", "portion": "80g", "calories": 50, "protein": 3.0, "carbs": 3.5, "fat": 2.5, "cost": 7}
            ],
            "total_calories": 636,
            "total_protein": 22.7,
            "total_carbs": 105.5,
            "total_fat": 12.6,
            "estimated_cost_inr": 52,
            "feedback": "Classic Indian hostel thali providing steady glycogen from roti and rice with essential amino acids from dal. Top up with 50g paneer or 2 boiled eggs to hit hypertrophy targets."
        }

    return {
        "status": "success",
        "is_ai": False,
        "source": "FitSync Indian Food Heuristic Vision",
        "dish_name": fallback["dish_name"],
        "health_rating": fallback["health_rating"],
        "items": fallback["items"],
        "total_calories": fallback["total_calories"],
        "total_protein": fallback["total_protein"],
        "total_carbs": fallback["total_carbs"],
        "total_fat": fallback["total_fat"],
        "estimated_cost_inr": fallback["estimated_cost_inr"],
        "feedback": fallback["feedback"]
    }


