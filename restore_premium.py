
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

# Config from .env
MONGO_URI = "mongodb+srv://Komo:NaMo2580@komo.bfzous4.mongodb.net/?retryWrites=true&w=majority"
DB_NAME = "Komo"

async def restore_user():
    print("="*40)
    print("   CYORI PREMIUM RESTORE TOOL")
    print("="*40)
    
    user_id = input("Enter User ID to give Premium: ").strip()
    if not user_id.isdigit():
        print("Invalid User ID!")
        return

    print(f"Connecting to MongoDB...")
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db["music_data"]
    
    print(f"Restoring Premium for User: {user_id}...")
    
    # Update operation
    result = await collection.update_one(
        {"users": {"$exists": True}}, # Try to update existing doc with users
        {"$set": {
            f"users.{user_id}.premium": True,
            f"users.{user_id}.premium_plan": "Lifetime Restored",
            f"users.{user_id}.premium_expire": "Lifetime"
        }},
        upsert=False # Don't upsert if finding failed yet
    )
    
    if result.matched_count == 0:
        # Fallback: Find ANY document (likely the main config doc) and update it
        print("No document with 'users' key found. Adding to main document...")
        result = await collection.update_one(
            {}, # Match anything
            {"$set": {
                f"users.{user_id}.premium": True,
                f"users.{user_id}.premium_plan": "Lifetime Restored",
                f"users.{user_id}.premium_expire": "Lifetime"
            }},
            upsert=True
        )
    
    if result.modified_count > 0 or result.upserted_id:
        print(f"\n✅ SUCCESS! Premium (Lifetime) added for {user_id}.")
        print("Please restart the bot or wait for cache refresh.")
    else:
        print("\n⚠️ No changes made. User might already be premium?")

if __name__ == "__main__":
    try:
        asyncio.run(restore_user())
    except Exception as e:
        print(f"Error: {e}")
    input("\nPress Enter to exit...")
