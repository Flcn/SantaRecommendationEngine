import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration"""
    
    # Database
    database_url: str = "postgresql://postgres:password@localhost:5432/postgres"
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    
    # Service settings
    debug: bool = False
    log_level: str = "info"
    
    # Cache TTL settings (in seconds)
    cache_ttl_similarity: int = 14400  # 4 hours
    cache_ttl_popular: int = 900       # 15 minutes  
    cache_ttl_recommendations: int = 7200  # 2 hours
    
    # Performance limits
    max_similar_users: int = 50
    max_recommendation_items: int = 200
    similarity_min_overlap: int = 2
    
    # Query performance limits
    max_query_time: float = 0.5  # 500ms max per query
    max_items_per_batch: int = 1000
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()