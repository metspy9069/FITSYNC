import unittest
import json
import uuid
from datetime import datetime
from werkzeug.security import generate_password_hash
from app import app, db, User, UserProfile, NutritionTarget, MealPlan, Meal

class NationalCompetitionFeaturesTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        with app.app_context():
            self.test_email = f'competitor_{uuid.uuid4().hex[:10]}@fitsync.ai'
            user = User(email=self.test_email, password_hash=generate_password_hash('SecurePass123!'))
            db.session.add(user)
            db.session.commit()

            profile = UserProfile(
                user_id=user.id,
                name='Competitor Student',
                age=20,
                gender='Male',
                height=175.0,
                weight=68.0,
                fitness_goal='Muscle Gain',
                fitness_level='Intermediate',
                workout_days_per_week=4,
                workout_duration_mins=45,
                workout_environment='Gym',
                dietary_preference='Vegetarian',
                daily_food_budget=160,
                onboarding_completed=True
            )
            db.session.add(profile)
            db.session.commit()
            self.user_id = user.id

    def login_test_user(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id

    def test_hostel_mess_presets_endpoint(self):
        res = self.client.get('/api/nutrition/hostel-presets')
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertEqual(data.get('status'), 'success')
        self.assertGreaterEqual(len(data.get('presets', [])), 4)

        preset_keys = [p['key'] for p in data['presets']]
        self.assertIn('north_indian_mess', preset_keys)
        self.assertIn('south_indian_mess', preset_keys)
        self.assertIn('high_protein_student', preset_keys)
        self.assertIn('budget_student_snack', preset_keys)

    def test_scan_food_plate_endpoint(self):
        self.login_test_user()
        payload = {
            'image': 'data:image/jpeg;base64,dGVzdGZvb2RpbWFnZQ==',
            'meal_type': 'Lunch'
        }
        res = self.client.post('/api/ai/scan-food-plate', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('dish_name', data)
        self.assertIn('total_calories', data)
        self.assertIn('total_protein', data)
        self.assertGreater(data.get('total_calories', 0), 200)
        self.assertGreater(len(data.get('items', [])), 0)

    def test_log_scanned_plate_to_daily_meals(self):
        self.login_test_user()
        payload = {
            'meal_type': 'Lunch',
            'dish_name': 'Hostel Mess Thali',
            'total_calories': 636,
            'total_protein': 22.7,
            'total_carbs': 105.5,
            'total_fat': 12.6,
            'estimated_cost_inr': 52
        }
        res = self.client.post('/api/nutrition/log-scanned-plate', json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json.get('status'), 'success')

        today_str = datetime.now().strftime('%Y-%m-%d')
        with app.app_context():
            meal_plan = MealPlan.query.filter_by(user_id=self.user_id, date=today_str).first()
            self.assertIsNotNone(meal_plan)
            lunch = Meal.query.filter_by(meal_plan_id=meal_plan.id, meal_type='Lunch').first()
            self.assertIsNotNone(lunch)
            self.assertEqual(lunch.calories, 636)
            self.assertAlmostEqual(lunch.protein, 22.7, places=1)
            self.assertGreaterEqual(meal_plan.total_calories, 636)

    def test_apply_hostel_preset(self):
        self.login_test_user()
        payload = {
            'preset_key': 'high_protein_student',
            'meal_type': 'Dinner'
        }
        res = self.client.post('/api/nutrition/apply-hostel-preset', json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json.get('status'), 'success')

        today_str = datetime.now().strftime('%Y-%m-%d')
        with app.app_context():
            meal_plan = MealPlan.query.filter_by(user_id=self.user_id, date=today_str).first()
            self.assertIsNotNone(meal_plan)
            dinner = Meal.query.filter_by(meal_plan_id=meal_plan.id, meal_type='Dinner').first()
            self.assertIsNotNone(dinner)
            self.assertIn('High-Protein', dinner.food_name)
            self.assertGreaterEqual(dinner.protein, 50.0)

    def test_dashboard_heatmap_and_leaderboard_rendering(self):
        self.login_test_user()
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn('30-Day Consistency Heatmap', html)
        self.assertIn('Day Streak', html)
        self.assertIn('Campus Arena Leaderboard', html)
        self.assertIn('IIT Bombay', html)

    def test_service_worker_offline_caching(self):
        res = self.client.get('/static/sw.js')
        self.assertEqual(res.status_code, 200)
        sw_content = res.data.decode('utf-8')
        self.assertIn('fitsync-v2-offline-gym', sw_content)
        self.assertIn('/today-workout', sw_content)
        self.assertIn('/form-check', sw_content)
        self.assertIn('/nutrition', sw_content)

if __name__ == '__main__':
    unittest.main()
