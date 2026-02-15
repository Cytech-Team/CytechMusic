
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

# Hardcoded from .env for absolute certainty
MONGO_URI = "mongodb+srv://Komo:NaMo2580@komo.bfzous4.mongodb.net/?retryWrites=true&w=majority"
DB_NAME = "Cyori"

async def inspect_db():
    print(f"Connecting to MongoDB: {MONGO_URI.split('@')[1]}") # Hide password in log
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db["music_data"]
    
    # 1. Count Documents
    count = await collection.count_documents({})
    print(f"Total Documents in '{db.name}.music_data': {count}")
    
    # 2. Inspect Content
    cursor = collection.find({})
    doc_idx = 1
    total_users_found = 0
    
    async for doc in cursor:
        print(f"\n--- Document #{doc_idx} (ID: {doc.get('_id')}) ---")
        keys = list(doc.keys())
        print(f"Top-level keys: {keys}")
        
        # Check users
        if "users" in doc:
            users = doc["users"]
            print(f"Found 'users' key with {len(users)} entries.")
            total_users_found += len(users)
            
            # Print first 3 users keys
            sample_users = list(users.keys())[:3]
            print(f"Sample User IDs: {sample_users}")
            
            # Check for specific fields in users
            premium_count = 0
            for uid, udata in users.items():
                if udata.get("premium") or udata.get("premium_expire"):
                    premium_count += 1
            print(f"Users with Premium flags: {premium_count}")
        else:
            print("No 'users' key in this document.")
            
        doc_idx += 1

    if total_users_found == 0:
        print("\n[!] WARNING: No users found in ANY document. Data might be lost or in another DB.")

if __name__ == "__main__":
    try:
        asyncio.run(inspect_db())
    except Exception as e:
        print(f"Error: {e}")
