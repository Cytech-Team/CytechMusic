import asyncio
import time
from typing import Dict, Any, Union
from motor.motor_asyncio import AsyncIOMotorCollection


class _RootSafeCollectionProxy:
    """Delegate collection access while making empty update filters fail-safe.

    This collection stores both the root config document and standalone user
    documents. An accidental update_one({}) can therefore mutate an arbitrary
    user document. Empty update filters are rewritten to the resolved root _id.
    """

    def __init__(self, manager: "DatabaseManager", collection: AsyncIOMotorCollection):
        self._manager = manager
        self._collection = collection

    def __getattr__(self, name):
        return getattr(self._collection, name)

    async def update_one(self, filter, update, *args, **kwargs):
        if filter == {}:
            await self._manager._fetch_root()
            if self._manager._root_id is None:
                raise RuntimeError("Refusing update_one({}): root document could not be resolved")
            filter = {"_id": self._manager._root_id}
        return await self._collection.update_one(filter, update, *args, **kwargs)


class DatabaseManager:
    """
    Centralized Database Manager with In-Memory Caching.
    Reduces the number of redundant MongoDB query calls.
    """

    def __init__(self, collection: AsyncIOMotorCollection):
        self._raw_collection = collection
        self._cache_data: Dict[str, Any] = {}
        self._last_fetch_time: float = 0
        self._cache_ttl: int = 60  # Cache duration (seconds)
        self._lock = asyncio.Lock()
        self._root_id = None
        self.collection = _RootSafeCollectionProxy(self, collection)

    async def _fetch_root(self, force: bool = False) -> Dict[str, Any]:
        """Fetch the root document and cache it."""
        current_time = time.time()
        # Return cache if valid
        if (
            not force
            and self._cache_data
            and (current_time - self._last_fetch_time < self._cache_ttl)
        ):
            return self._cache_data

        async with self._lock:
            # Re-check condition inside lock to avoid race conditions
            if (
                not force
                and self._cache_data
                and (current_time - self._last_fetch_time < self._cache_ttl)
            ):
                return self._cache_data

            try:
                # Protection: Exclude user docs strictly, find the actual root config doc
                data = await self.collection.find_one(
                    {"user_id": {"$exists": False}, "guilds": {"$exists": True}}
                )
                if not data:
                    # Fallback for older schema
                    data = await self.collection.find_one(
                        {"user_id": {"$exists": False}}
                    )

                if not data:
                    data = {"guilds": {}, "users": {}, "history": {}}
                    # Ensure document is created properly to avoid missing _id
                    res = await self.collection.insert_one(data)
                    data["_id"] = res.inserted_id

                self._root_id = data.get("_id")

                self._cache_data = data
                self._last_fetch_time = time.time()
                return self._cache_data
            except Exception as e:
                print(f"[DatabaseManager] Failed to fetch root: {e}")
                # Fallback to expired cache or empty dict
                return (
                    self._cache_data
                    if self._cache_data
                    else {"guilds": {}, "users": {}, "history": {}}
                )

    async def get_guild(
        self, guild_id: Union[int, str], force: bool = False
    ) -> Dict[str, Any]:
        """Get settings for a specific guild."""
        gid = str(guild_id)
        data = await self._fetch_root(force=force)
        guilds = data.get("guilds", {})
        return guilds.get(gid, {})

    async def get_user(
        self, user_id: Union[int, str], force: bool = False
    ) -> Dict[str, Any]:
        """Get settings/premium data for a specific user."""
        uid = str(user_id)
        data = await self._fetch_root(force=force)
        users = data.get("users", {})
        return users.get(uid, {})

    async def get_lang(self, guild_id: Union[int, str], default: str = "en") -> str:
        """Helper to quickly get guild language."""
        guild_data = await self.get_guild(guild_id)
        return guild_data.get("lang", default)

    async def update_guild(
        self, guild_id: Union[int, str], update_dict: Dict[str, Any]
    ):
        """Update specific fields for a guild in both DB and Cache."""
        gid = str(guild_id)

        # Build MongoDB dot-notation for $set
        set_payload = {f"guilds.{gid}.{k}": v for k, v in update_dict.items()}

        try:
            # Protection: Only update the explicitly cached root document
            query = (
                {"_id": self._root_id}
                if self._root_id
                else {"user_id": {"$exists": False}}
            )
            await self.collection.update_one(query, {"$set": set_payload}, upsert=True)

            # Update local cache immediately to stay synchronized
            async with self._lock:
                if "guilds" not in self._cache_data:
                    self._cache_data["guilds"] = {}
                if gid not in self._cache_data["guilds"]:
                    self._cache_data["guilds"][gid] = {}

                for k, v in update_dict.items():
                    self._cache_data["guilds"][gid][k] = v
        except Exception as e:
            print(f"[DatabaseManager] Failed to update guild {gid}: {e}")

    async def unset_guild(self, guild_id: Union[int, str], fields: list[str]):
        """Remove specific fields from a guild in both DB and Cache."""
        gid = str(guild_id)
        unset_payload = {f"guilds.{gid}.{k}": "" for k in fields}

        try:
            query = (
                {"_id": self._root_id}
                if self._root_id
                else {"user_id": {"$exists": False}}
            )
            await self.collection.update_one(query, {"$unset": unset_payload})
            async with self._lock:
                if "guilds" in self._cache_data and gid in self._cache_data["guilds"]:
                    for k in fields:
                        self._cache_data["guilds"][gid].pop(k, None)
        except Exception as e:
            print(f"[DatabaseManager] Failed to unset guild {gid}: {e}")

    async def update_user(self, user_id: Union[int, str], update_dict: Dict[str, Any]):
        """Update specific fields for a user in both DB and Cache."""
        uid = str(user_id)
        set_payload = {f"users.{uid}.{k}": v for k, v in update_dict.items()}

        try:
            query = (
                {"_id": self._root_id}
                if self._root_id
                else {"user_id": {"$exists": False}}
            )
            await self.collection.update_one(query, {"$set": set_payload}, upsert=True)

            async with self._lock:
                if "users" not in self._cache_data:
                    self._cache_data["users"] = {}
                if uid not in self._cache_data["users"]:
                    self._cache_data["users"][uid] = {}

                for k, v in update_dict.items():
                    self._cache_data["users"][uid][k] = v
        except Exception as e:
            print(f"[DatabaseManager] Failed to update user {uid}: {e}")

    async def invalidate_cache(self):
        """Force the cache to clear."""
        async with self._lock:
            self._cache_data = {}
            self._last_fetch_time = 0

    # --- User Specific Documents (Favorites & Playlists) ---
    # These queries use {"user_id": "..."} documents instead of the root document.

    async def get_user_doc(self, user_id: Union[int, str]) -> Dict[str, Any]:
        """Fetch the standalone user document (playlists, favorites). Not cached as it updates frequently."""
        uid = str(user_id)
        try:
            doc = await self.collection.find_one({"user_id": uid})
            return doc or {}
        except Exception as e:
            print(f"[DatabaseManager] Error fetching user doc {uid}: {e}")
            return {}

    async def update_user_doc(
        self, user_id: Union[int, str], update_query: Dict[str, Any]
    ):
        """Directly run an update query (like $set, $addToSet, $pull) on the standalone user document."""
        uid = str(user_id)
        try:
            await self.collection.update_one(
                {"user_id": uid}, update_query, upsert=True
            )
        except Exception as e:
            print(f"[DatabaseManager] Failed to update user doc {uid}: {e}")
