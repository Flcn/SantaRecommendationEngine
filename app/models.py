from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator


class Pagination(BaseModel):
    """Pagination parameters"""
    page: int = Field(1, ge=1, description="Page number (1-based)")
    limit: int = Field(20, ge=1, le=100, description="Items per page")
    
    @property
    def offset(self) -> int:
        """Calculate offset from page and limit"""
        return (self.page - 1) * self.limit


class UserParams(BaseModel):
    """User demographic parameters for popular items"""
    gender: Optional[str] = Field(None, description="Gender: 'f', 'm', or 'any'")
    age: Optional[str] = Field(None, description="Age group: '18-24', '25-34', '35-44', '45+', etc.")
    category: Optional[str] = Field(None, description="Category preference")
    geo_id: int = Field(..., description="Geographic region ID")


class Filters(BaseModel):
    """Common filters for recommendations"""
    price_from: Optional[float] = Field(None, ge=0, description="Minimum price")
    price_to: Optional[float] = Field(None, ge=0, description="Maximum price") 
    category: Optional[str] = Field(None, description="Category filter")
    suitable_for: Optional[str] = Field(None, description="Suitable for: 'friend', 'family', 'colleague'")
    acquaintance_level: Optional[str] = Field(None, description="Acquaintance level: 'close', 'casual', 'formal'")
    platform: Optional[str] = Field(None, description="Platform filter")
    
    @field_validator('price_to')
    @classmethod
    def price_to_must_be_greater_than_price_from(cls, v, info):
        if info.data.get('price_from') is not None and v is not None:
            if v <= info.data['price_from']:
                raise ValueError('price_to must be greater than price_from')
        return v


class PopularItemsRequest(BaseModel):
    """Request model for popular items API"""
    user_params: UserParams
    filters: Optional[Filters] = None
    pagination: Pagination = Pagination()


class PersonalizedRequest(BaseModel):
    """Request model for personalized recommendations API"""
    user_id: str = Field(..., description="User ID for personalized recommendations (UUID string)")
    geo_id: int = Field(..., description="Geographic region ID")
    filters: Optional[Filters] = None
    pagination: Pagination = Pagination()


class PaginationInfo(BaseModel):
    """Pagination information in response"""
    page: int
    limit: int
    total_pages: int
    total_count: int
    has_next: bool
    has_previous: bool


class RecommendationResponse(BaseModel):
    """Response model for both popular and personalized recommendations"""
    items: List[str] = Field(..., description="List of recommended item IDs (UUID strings)")
    pagination: PaginationInfo
    computation_time_ms: float = Field(..., description="Time taken to compute recommendations")
    algorithm_used: str = Field(..., description="Algorithm used: 'popular', 'personalized', 'hybrid'")
    cache_hit: bool = Field(False, description="Whether result came from cache")


class SimilarUsersRequest(BaseModel):
    """Request for finding similar users"""
    user_id: str = Field(..., description="User ID (UUID string)")
    limit: int = Field(20, ge=1, le=100)


class UserProfile(BaseModel):
    """User profile for recommendations (Option 3 Hybrid Approach)"""
    user_id: str = Field(..., description="User ID (UUID string)")
    preferred_categories: Dict[str, float] = Field(default_factory=dict, description="What they like")
    preferred_platforms: Dict[str, float] = Field(default_factory=dict)
    avg_price: Optional[float] = None
    price_range_min: Optional[float] = None 
    price_range_max: Optional[float] = None
    # Buying patterns (Option 3): who they buy gifts for
    buying_patterns_target_ages: Dict[str, float] = Field(default_factory=dict, description="Ages they buy for")
    buying_patterns_relationships: Dict[str, float] = Field(default_factory=dict, description="Who they buy for")
    buying_patterns_gender_targets: Dict[str, float] = Field(default_factory=dict, description="Gender they buy for")
    interaction_count: int = 0
    last_interaction_at: Optional[str] = None


class ItemFeatures(BaseModel):
    """Item features for similarity calculations"""
    item_id: int
    categories: Dict[str, Any] = Field(default_factory=dict)
    price: float
    platform: str
    geo_id: int
    created_at: str


class UserDemographicsUpdate(BaseModel):
    """User demographics update from Rails for real-time sync"""
    gender: Optional[str] = Field(None, description="Gender: 'male', 'female', or None")
    age_group: Optional[str] = Field(None, description="Age group: '18-24', '25-34', '35-44', '45+', 'unknown'")
    locale: Optional[str] = Field(None, description="Locale: 'ru', 'en', etc.")
    geo_id: Optional[int] = Field(None, description="Geographic region ID")
    
    @field_validator('gender')
    @classmethod
    def normalize_gender(cls, v):
        """Convert Rails gender enum to recommendation engine format"""
        if v is None:
            return None
        gender_map = {'male': 'm', 'female': 'f'}
        return gender_map.get(v, v)


class ServiceStats(BaseModel):
    """Service statistics"""
    total_items: int
    total_likes: int  
    total_clicks: int
    active_users: int
    cache_hit_rate: Optional[float] = None