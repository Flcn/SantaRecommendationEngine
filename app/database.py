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
            logger.info(f"Connecting to main database: {settings.main_database_url}")
            logger.info(f"Connecting to recommendations database: {settings.recommendations_database_url}")
            logger.info(f"Connecting to Redis: {settings.recommendations_redis_url}")
            
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
        if settings.is_development:
            logger.info(f"[MAIN DB] Executing query: {query}")
            logger.info(f"[MAIN DB] Parameters: {args}")
        
        async with self.main_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            result = [dict(row) for row in rows]
            
            if settings.is_development:
                logger.info(f"[MAIN DB] Result count: {len(result)}")
                if result and len(result) <= 5:  # Log first few results if small dataset
                    logger.info(f"[MAIN DB] Sample results: {result}")
            
            return result
    
    async def execute_main_query_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Execute a query on main database and return single result"""
        if settings.is_development:
            logger.info(f"[MAIN DB ONE] Executing query: {query}")
            logger.info(f"[MAIN DB ONE] Parameters: {args}")
        
        async with self.main_pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            result = dict(row) if row else None
            
            if settings.is_development:
                logger.info(f"[MAIN DB ONE] Result: {result}")
            
            return result
    
    async def execute_recommendations_query(self, query: str, *args) -> List[Dict[str, Any]]:
        """Execute a query on recommendations database"""
        if settings.is_development:
            logger.info(f"[REC DB] Executing query: {query}")
            logger.info(f"[REC DB] Parameters: {args}")
        
        async with self.recommendations_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            result = [dict(row) for row in rows]
            
            if settings.is_development:
                logger.info(f"[REC DB] Result count: {len(result)}")
                if result and len(result) <= 5:  # Log first few results if small dataset
                    logger.info(f"[REC DB] Sample results: {result}")
            
            return result
    
    async def execute_recommendations_query_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Execute a query on recommendations database and return single result"""
        if settings.is_development:
            logger.info(f"[REC DB ONE] Executing query: {query}")
            logger.info(f"[REC DB ONE] Parameters: {args}")
        
        async with self.recommendations_pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            result = dict(row) if row else None
            
            if settings.is_development:
                logger.info(f"[REC DB ONE] Result: {result}")
            
            return result
    
    async def execute_recommendations_command(self, query: str, *args) -> str:
        """Execute a command on recommendations database (INSERT/UPDATE/DELETE)"""
        async with self.recommendations_pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    def cache_get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = self.redis_client.get(key)
            result = json.loads(value) if value else None
            
            if settings.is_development:
                status = "HIT" if result is not None else "MISS"
                logger.info(f"[CACHE {status}] Key: {key}")
                if result and status == "HIT":
                    logger.info(f"[CACHE HIT] Value type: {type(result)}, size: {len(str(result)) if result else 0}")
            
            return result
        except Exception as e:
            logger.warning(f"Cache get error for key {key}: {e}")
            return None
    
    def cache_set(self, key: str, value: Any, ttl: int):
        """Set value in cache"""
        try:
            self.redis_client.setex(key, ttl, json.dumps(value))
            
            if settings.is_development:
                logger.info(f"[CACHE SET] Key: {key}, TTL: {ttl}s")
                logger.info(f"[CACHE SET] Value type: {type(value)}, size: {len(str(value)) if value else 0}")
        except Exception as e:
            logger.warning(f"Cache set error for key {key}: {e}")
    
    def cache_delete(self, key: str):
        """Delete value from cache"""
        try:
            self.redis_client.delete(key)
        except Exception as e:
            logger.warning(f"Cache delete error for key {key}: {e}")
    
    async def cache_set_async(self, key: str, value: any, ttl: int = 3600):
        """Async version of cache_set for use in endpoints"""
        self.cache_set(key, value, ttl)
    
    async def cache_delete_async(self, key: str):
        """Async version of cache_delete for use in endpoints"""
        self.cache_delete(key)
    
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