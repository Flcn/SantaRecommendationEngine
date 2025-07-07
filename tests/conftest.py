"""
Test configuration and fixtures
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models import (
    PopularItemsRequest, 
    PersonalizedRequest, 
    UserParams, 
    Filters, 
    Pagination,
    UserProfile
)


@pytest.fixture
def mock_db():
    """Mock database manager"""
    mock_db = MagicMock()
    
    # Mock async methods
    mock_db.execute_main_query = AsyncMock()
    mock_db.execute_main_query_one = AsyncMock()
    mock_db.execute_recommendations_query = AsyncMock()
    mock_db.execute_recommendations_query_one = AsyncMock()
    
    # Mock cache methods
    mock_db.cache_get = MagicMock(return_value=None)
    mock_db.cache_set = MagicMock()
    mock_db.cache_delete = MagicMock()
    
    return mock_db


@pytest.fixture
def sample_popular_request():
    """Sample popular items request"""
    return PopularItemsRequest(
        user_params=UserParams(
            gender="f",
            age="25-34",
            category="electronics",
            geo_id=213
        ),
        filters=Filters(
            price_from=500,
            price_to=2000
        ),
        pagination=Pagination(page=1, limit=20)
    )


@pytest.fixture
def sample_personalized_request():
    """Sample personalized request"""
    return PersonalizedRequest(
        user_id="123",
        geo_id=213,
        filters=Filters(
            price_from=500,
            price_to=2000,
            category="electronics"
        ),
        pagination=Pagination(page=1, limit=20)
    )


@pytest.fixture
def sample_user_profile():
    """Sample user profile"""
    return UserProfile(
        user_id="123",
        preferred_categories={"category:electronics": 0.6, "category:books": 0.4},
        preferred_platforms={"ozon": 0.7, "wildberries": 0.3},
        avg_price=1500.0,
        price_range_min=200.0,
        price_range_max=5000.0,
        interaction_count=5
    )


@pytest.fixture
def sample_popular_items():
    """Sample popular items data"""
    return [
        {"item_id": "101"},
        {"item_id": "102"},
        {"item_id": "103"},
        {"item_id": "104"},
        {"item_id": "105"}
    ]


@pytest.fixture
def sample_user_likes():
    """Sample user likes data"""
    return [
        {"handpicked_present_id": "201"},
        {"handpicked_present_id": "202"},
        {"handpicked_present_id": "203"}
    ]