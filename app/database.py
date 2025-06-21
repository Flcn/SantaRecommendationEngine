import asyncio
from typing import List, Dict, Any, Optional
import asyncpg
import redis
import json
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages dual database connections and caching"""
    
    def __init__(self):
        self.main_pool: Optional[asyncpg.Pool] = None  # Read-only main DB
        self.recommendations_pool: Optional[asyncpg.Pool] = None  # Read/write recommendations DB
        self.redis_client: Optional[redis.Redis] = None
    
    async def init_pools(self):
        """Initialize database connection pools"""
        try:
            # Main database pool (READ-ONLY)
            self.main_pool = await asyncpg.create_pool(
                settings.main_database_url,
                min_size=2,
                max_size=10,
                command_timeout=settings.max_query_time
            )
            
            # Recommendations database pool (READ/WRITE)
            self.recommendations_pool = await asyncpg.create_pool(
                settings.recommendations_database_url,
                min_size=2,
                max_size=15,
                command_timeout=settings.max_query_time
            )
            
            # Initialize Redis (separate database)
            self.redis_client = redis.from_url(settings.recommendations_redis_url, decode_responses=True)
            
            logger.info("Database connections initialized (main + recommendations + redis)")
        except Exception as e:
            logger.error(f"Failed to initialize databases: {e}")
            raise
    
    async def close(self):
        """Close all connections"""
        if self.main_pool:
            await self.main_pool.close()
        if self.recommendations_pool:
            await self.recommendations_pool.close()
        if self.redis_client:
            self.redis_client.close()
    
    async def execute_main_query(self, query: str, *args) -> List[Dict[str, Any]]:
        """Execute a query on main database (READ-ONLY)"""
        async with self.main_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def execute_main_query_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Execute a query on main database and return single result"""
        async with self.main_pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    async def execute_recommendations_query(self, query: str, *args) -> List[Dict[str, Any]]:
        """Execute a query on recommendations database"""
        async with self.recommendations_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def execute_recommendations_query_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Execute a query on recommendations database and return single result"""
        async with self.recommendations_pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    async def execute_recommendations_command(self, query: str, *args) -> str:
        """Execute a command on recommendations database (INSERT/UPDATE/DELETE)"""
        async with self.recommendations_pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    def cache_get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = self.redis_client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.warning(f"Cache get error for key {key}: {e}")
            return None
    
    def cache_set(self, key: str, value: Any, ttl: int):
        """Set value in cache"""
        try:
            self.redis_client.setex(key, ttl, json.dumps(value))
        except Exception as e:
            logger.warning(f"Cache set error for key {key}: {e}")
    
    def cache_delete(self, key: str):
        """Delete value from cache"""
        try:
            self.redis_client.delete(key)
        except Exception as e:
            logger.warning(f"Cache delete error for key {key}: {e}")
    
    async def refresh_popular_items(self):
        """Refresh popular items cache table"""
        try:
            await self.execute_recommendations_command("SELECT refresh_popular_items()")
            logger.info("Popular items refreshed successfully")
        except Exception as e:
            logger.error(f"Error refreshing popular items: {e}")
            raise
    
    async def cleanup_cache_data(self):
        """Clean up old cache data"""
        try:
            await self.execute_recommendations_command("SELECT cleanup_cache_data()")
            logger.info("Cache data cleaned up successfully")
        except Exception as e:
            logger.error(f"Error cleaning up cache data: {e}")


# Global database manager instance
db = DatabaseManager()