import urllib.request
import json
import os

token = "9070559372:AAEsCUsDnb-xlgDzq3JakX4_9icIgMhPCAA"
# Find latest user from Supabase or recent chats
from services.supabase_service import SupabaseService
supa = SupabaseService()
users = supa.get_all_users()
print("Registered users on Supabase:", users)
