import os
import json
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL or SUPABASE_KEY is missing from your .env file.")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Load existing JSON settings
if not os.path.exists("user_settings.json"):
    print("user_settings.json not found!")
    exit(1)

with open("user_settings.json", "r") as f:
    settings = json.load(f)

print(f"Migrating {len(settings)} user profiles to Supabase...")

for user_id, conf in settings.items():
    payload = {
        "user_id": str(user_id),
        "src": conf.get("src", []),
        "dst": conf.get("dst", []),
        "lang": conf.get("lang", "en"),
        "username": conf.get("username", ""),
        "active": conf.get("active", True),
        "allow_forwarded": conf.get("allow_forwarded", True),
        "use_seo_hashtags": conf.get("use_seo_hashtags", False),
    }
    try:
        supabase.table("user_settings").upsert(payload).execute()
        print(f"✅ Migrated settings for user: {user_id}")
    except Exception as e:
        print(f"❌ Failed for user {user_id}: {e}")

print("Migration complete! You can now run your main bot script.")