from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class RecommendationRequest(BaseModel):
    """Request model for recommendations"""
    user_id: int
    geo_id: int
    limit: int = 10
    offset: int = 0
    
    # Optional filters
    price_from: Optional[float] = None
    price_to: Optional[float] = None
    gender: Optional[str] = None
    age: Optional[str] = None
    category: Optional[str] = None
    suitable_for: Optional[str] = None
    acquaintance_level: Optional[str] = None
    platform: Optional[str] = None


class PopularItemsRequest(BaseModel):
    """Request model for popular items"""
    geo_id: int
    limit: int = 10
    offset: int = 0
    user_id: Optional[int] = None  # For personalized popular items
    
    # Optional filters (same as recommendations)
    price_from: Optional[float] = None
    price_to: Optional[float] = None
    gender: Optional[str] = None
    age: Optional[str] = None
    category: Optional[str] = None
    suitable_for: Optional[str] = None
    acquaintance_level: Optional[str] = None
    platform: Optional[str] = None


class RecommendationResponse(BaseModel):
    """Response model for recommendations"""
    item_ids: List[int]
    total_count: int
    has_more: bool
    computation_time_ms: float
    algorithm_used: str


class SimilarUsersRequest(BaseModel):
    """Request for finding similar users"""
    user_id: int
    limit: int = 20


class UserProfile(BaseModel):
    """User profile for recommendations"""
    user_id: int
    gender: Optional[str] = None
    age_group: Optional[str] = None
    locale: Optional[str] = None
    avg_liked_price: Optional[float] = None
    preferred_categories: Dict[str, int] = {}
    liked_items: List[int] = []


class ItemFeatures(BaseModel):
    """Item features for content-based filtering"""
    item_id: int
    categories: Dict[str, Any] = {}
    price: float
    platform: str
    geo_id: int
    created_at: str