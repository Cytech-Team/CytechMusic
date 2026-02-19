
import asyncio
import time
from bot import collection_myasync

QUESTS_DB = {
    "daily_login": {
        "id": "daily_login",
        "title_en": "Daily Check-in",
        "title_th": "เช็คอินรายวัน",
        "desc_en": "Login to the dashboard today",
        "desc_th": "เข้าสู่ระบบแดชบอร์ดวันนี้",
        "target": 1,
        "reward": 100,
        "type": "daily"
    }
}

class QuestManager:
    @staticmethod
    async def get_user_quests(user_id: str):
        user_id = str(user_id)
        user_doc = await collection_myasync.find_one({"user_id": user_id}) or {}
        user_quests = user_doc.get("quests", {})
        points = user_doc.get("points", 0)
        level = user_doc.get("level", 1)
        
        # Reset dailies if needed
        last_reset = user_doc.get("last_quest_reset", 0)
        now = int(time.time())
        # Check if it's a new day (UTC or Local? Let's use 24h for simplicity or calendar day)
        if now - last_reset > 86400: # 24 hours
             user_quests = {} 
             await collection_myasync.update_one(
                 {"user_id": user_id}, 
                 {"$set": {"quests": {}, "last_quest_reset": now}}, 
                 upsert=True
             )

        quest_list = []
        for qid, qdata in QUESTS_DB.items():
            status = user_quests.get(qid, {"progress": 0, "claimed": False})
            quest_list.append({
                **qdata,
                "progress": status.get("progress", 0),
                "claimed": status.get("claimed", False)
            })
            
        return {
            "quests": quest_list,
            "points": points,
            "level": level,
            "xp_next": level * 1000 # Example XP logic
        }

    @staticmethod
    async def update_quest_progress(user_id: str, quest_id: str, amount: int = 1):
        if quest_id not in QUESTS_DB: return
        user_id = str(user_id)
        
        # Ensure daily reset check happens here too or assume handled
        
        path = f"quests.{quest_id}.progress"
        await collection_myasync.update_one(
            {"user_id": user_id},
            {"$inc": {path: amount}},
            upsert=True
        )

    @staticmethod
    async def claim_reward(user_id: str, quest_id: str):
        if quest_id not in QUESTS_DB: return {"error": "invalid_quest"}
        user_id = str(user_id)
        
        user_doc = await collection_myasync.find_one({"user_id": user_id}) or {}
        user_quests = user_doc.get("quests", {})
        q_status = user_quests.get(quest_id, {"progress": 0, "claimed": False})
        
        q_def = QUESTS_DB[quest_id]
        
        if q_status.get("claimed"): return {"error": "already_claimed"}
        if q_status.get("progress", 0) < q_def["target"]: return {"error": "not_finished"}
        
        # Claim it
        reward = q_def["reward"]
        await collection_myasync.update_one(
            {"user_id": user_id},
            {
                "$set": {f"quests.{quest_id}.claimed": True},
                "$inc": {"points": reward, "xp": reward} # Reward matches XP for now
            }
        )
        
        # Level up logic check? 
        # For now keep it simple.
        return {"status": "ok", "reward": reward}
