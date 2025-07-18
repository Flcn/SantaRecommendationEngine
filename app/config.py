import os
from typing import Optional
from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration"""
    
    # Main Database (READ-ONLY for recommendations)
    main_database_url: str = "postgresql://postgres:password@db:5432/mysanta_main"
    
    # Recommendations Database (READ/WRITE for recommendations)  
    recommendations_database_url: str = "postgresql://postgres:password@db:5432/mysanta_recommendations"
    
    # Redis (separate database for recommendations)
    recommendations_redis_url: str = "redis://redis:6379/1"
    
    # Docker environment variable compatibility
    database_url: Optional[str] = None
    redis_url: Optional[str] = None
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Use DATABASE_URL if provided (for Docker compatibility)
        if self.database_url:
            self.main_database_url = self.database_url
            self.recommendations_database_url = self.database_url
        # Use REDIS_URL if provided (for Docker compatibility)  
        if self.redis_url:
            self.recommendations_redis_url = self.redis_url
    
    # Service settings
    app_env: str = "development"  # development/production
    debug: bool = False
    log_level: str = "info"
    
    # HTTP Basic Authentication
    basic_auth_username: str = os.getenv("BASIC_AUTH_USERNAME", "mysanta_service")
    basic_auth_password: str = os.getenv("BASIC_AUTH_PASSWORD", "change_me_in_production")
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.app_env.lower() == "development"
    
    # Cache TTL settings (in seconds)
    cache_ttl_popular: int = int(os.getenv("CACHE_TTL_POPULAR", "900"))          # 15 minutes default
    cache_ttl_personalized: int = int(os.getenv("CACHE_TTL_PERSONALIZED", "5"))  # 5 seconds default
    cache_ttl_user_profile: int = int(os.getenv("CACHE_TTL_USER_PROFILE", "14400"))  # 4 hours default
    
    # Cache key prefix (change to invalidate all caches)
    cache_key_prefix: str = "v3"
    
    # Performance limits
    max_similar_users: int = 20
    default_page_size: int = 20
    max_page_size: int = 100
    
    # Background job settings
    popular_items_refresh_minutes: int = 15
    user_profile_cache_hours: int = 4
    
    # Query performance limits
    max_query_time: float = float(os.getenv("MAX_QUERY_TIME", "10.0"))  # seconds max per query (for regular operations)
    full_sync_query_timeout: float = float(os.getenv("FULL_SYNC_QUERY_TIMEOUT", "300.0"))  # seconds max per query (for full sync operations only)
    
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False
    )


settings = Settings()