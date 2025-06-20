import asyncio
from typing import List, Dict, Any, Optional
import asyncpg
import redis
import json
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and caching"""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.redis_client: Optional[redis.Redis] = None
    
    async def init_pool(self):
        """Initialize database connection pool"""
        try:
            self.pool = await asyncpg.create_pool(
                settings.database_url,
                min_size=2,
                max_size=10,
                command_timeout=settings.max_query_time
            )
            
            # Initialize Redis
            self.redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            
            logger.info("Database connections initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    async def close(self):
        """Close all connections"""
        if self.pool:
            await self.pool.close()
        if self.redis_client:
            self.redis_client.close()
    
    async def execute_query(self, query: str, *args) -> List[Dict[str, Any]]:
        """Execute a query and return results as dict list"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def execute_query_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Execute a query and return single result"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    def cache_get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = self.redis_client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            return None
    
    def cache_set(self, key: str, value: Any, ttl: int):
        """Set value in cache"""
        try:
            self.redis_client.setex(key, ttl, json.dumps(value))
        except Exception as e:
            logger.warning(f"Cache set error: {e}")


# Global database manager instance
db = DatabaseManager()