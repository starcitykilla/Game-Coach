import os
from supabase import create_client, Client

# --- CONFIGURATION ---
# PASTE YOUR SUPABASE KEYS HERE
url: str = "YOUR_SUPABASE_URL_GOES_HERE"
key: str = "YOUR_SUPABASE_ANON_KEY_GOES_HERE"

def test_connection():
    try:
        supabase: Client = create_client(url, key)
        
        print("1. Connecting to the Cloud Vault...")
        
        # Test Write: Create a fake user
        data, count = supabase.table('viewers').upsert({"username": "test_user_bmg", "bankroll": 5000}).execute()
        print("✅ Write Successful! Uploaded test user.")
        
        # Test Read: Fetch the user back
        response = supabase.table('viewers').select("*").eq("username", "test_user_bmg").execute()
        user_data = response.data[0]
        print(f"✅ Read Successful! Found User: {user_data['username']} | Bankroll: ${user_data['bankroll']}")
        
        print("\n🚀 SYSTEM STATUS: READY FOR TAKEOFF")
        
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        print("Double check your URL and KEY in the script!")

if __name__ == "__main__":
    test_connection()
