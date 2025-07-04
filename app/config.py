import os
from typing import Optional
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
    basic_auth_username: str = "mysanta_service"
    basic_auth_password: str = "change_me_in_production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.app_env.lower() == "development"
    
    # Cache TTL settings (in seconds)
    cache_ttl_popular: int = 900       # 15 minutes  
    cache_ttl_personalized: int = 5     # 5 seconds (for testing)
    cache_ttl_user_profile: int = 14400  # 4 hours
    
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
    max_query_time: float = 0.5  # 500ms max per query
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()