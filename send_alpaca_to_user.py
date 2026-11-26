import urllib.request
import json
import os
from pathlib import Path as _Path

from dotenv import load_dotenv as _load_dotenv

_load_dotenv(_Path(__file__).parent / ".env")

token = os.environ["TELEGRAM_BOT_TOKEN"]  # mai scrivere il token nel codice: usare .env
# Find latest user from Supabase or recent chats
from services.supabase_service import SupabaseService
supa = SupabaseService()
users = supa.get_all_users()
print("Registered users on Supabase:", users)
