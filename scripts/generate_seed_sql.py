import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

exercises = json.load(open(BASE_DIR / 'data' / 'exercises.json', encoding='utf-8'))
foods = json.load(open(BASE_DIR / 'data' / 'foods.json', encoding='utf-8'))

def esc(val):
    if val is None:
        return 'NULL'
    if isinstance(val, bool):
        return 'TRUE' if val else 'FALSE'
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        val = '\n'.join(str(x) for x in val)
    s = str(val).replace("'", "''")
    return f"'{s}'"

out_path = BASE_DIR / 'seed_data.sql'
with open(out_path, 'w', encoding='utf-8') as f:
    for ex in exercises:
        name = esc(ex.get('name'))
        aliases = esc(ex.get('aliases'))
        cat = esc(ex.get('category', 'General'))
        prim = esc(ex.get('primary_muscles'))
        sec = esc(ex.get('secondary_muscles'))
        eq = esc(ex.get('equipment'))
        diff = esc(ex.get('difficulty'))
        env = esc(ex.get('environment'))
        goal = esc(ex.get('goal'))
        inst = esc(ex.get('instructions'))
        cm = esc(ex.get('common_mistakes'))
        sn = esc(ex.get('safety_notes'))
        d_sets = ex.get('default_sets', 3)
        d_rmin = ex.get('default_reps_min', 8)
        d_rmax = ex.get('default_reps_max', 12)
        d_rest = ex.get('default_rest_seconds', 60)
        demo_av = 'TRUE' if ex.get('demonstration_available') else 'FALSE'
        demo_as = esc(ex.get('demonstration_asset'))
        thumb = esc(ex.get('thumbnail'))
        f.write(f"INSERT INTO exercises (name, aliases, category, primary_muscles, secondary_muscles, equipment, difficulty, environment, goal, instructions, common_mistakes, safety_notes, default_sets, default_reps_min, default_reps_max, default_rest_seconds, demonstration_available, demonstration_asset, thumbnail) VALUES ({name}, {aliases}, {cat}, {prim}, {sec}, {eq}, {diff}, {env}, {goal}, {inst}, {cm}, {sn}, {d_sets}, {d_rmin}, {d_rmax}, {d_rest}, {demo_av}, {demo_as}, {thumb}) ON CONFLICT (name) DO NOTHING;\n")

    for fd in foods:
        name = esc(fd.get('name'))
        cat = esc(fd.get('category', 'General'))
        ss = fd.get('serving_size_g', 100)
        cal = fd.get('calories', 0)
        prot = fd.get('protein', 0.0)
        carb = fd.get('carbs', 0.0)
        fat = fd.get('fat', 0.0)
        fib = fd.get('fiber', 0.0)
        cost = fd.get('cost_approx', 0)
        cu = esc(fd.get('common_unit', ''))
        is_veg = 'TRUE' if fd.get('is_vegetarian', True) else 'FALSE'
        is_vgn = 'TRUE' if fd.get('is_vegan', False) else 'FALSE'
        f.write(f"INSERT INTO foods (name, category, serving_size_g, calories, protein, carbs, fat, fiber, cost_approx, common_unit, is_vegetarian, is_vegan) VALUES ({name}, {cat}, {ss}, {cal}, {prot}, {carb}, {fat}, {fib}, {cost}, {cu}, {is_veg}, {is_vgn}) ON CONFLICT (name) DO NOTHING;\n")

print(f"Generated {out_path} successfully!")
