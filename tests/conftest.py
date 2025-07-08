"""
Test configuration and fixtures
"""

import pytest
import asyncio
import asyncpg
import redis
import os
from unittest.mock import AsyncMock, MagicMock
from app.models import (
    PopularItemsRequest, 
    PersonalizedRequest, 
    UserParams, 
    Filters, 
    Pagination,
    UserProfile
)
from app.config import settings


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


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function", autouse=True)
async def clean_test_db():
    """Clean and seed test database before each test"""
    # Only run if we're testing with real database (not mocked)
    if os.getenv('USE_REAL_DB_FOR_TESTS') != 'true':
        yield
        return
        
    # Connect to recommendations database
    conn = None
    redis_client = None
    
    try:
        # Clean recommendations database
        conn = await asyncpg.connect(settings.recommendations_database_url)
        
        # Read and execute schema file to reset database
        schema_path = os.path.join(os.path.dirname(__file__), '..', 'schema_minimal.sql')
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        # Execute schema (this will drop and recreate tables)
        await conn.execute(schema_sql)
        
        # Insert test data
        await seed_test_data(conn)
        
        # Clean Redis cache
        redis_client = redis.from_url(settings.recommendations_redis_url, decode_responses=True)
        redis_client.flushdb()
        
        yield
        
    except Exception as e:
        print(f"Warning: Could not clean test database: {e}")
        yield
    finally:
        if conn:
            await conn.close()
        if redis_client:
            redis_client.close()


async def seed_test_data(conn):
    """Seed test database with sample data"""
    
    # Insert sample popular items
    popular_items_data = [
        (213, 'f', '25-34', 'electronics', '101', 0.9),
        (213, 'f', '25-34', 'electronics', '102', 0.8),
        (213, 'f', '25-34', 'electronics', '103', 0.7),
        (213, 'm', '25-34', 'electronics', '104', 0.6),
        (213, 'm', '25-34', 'electronics', '105', 0.5),
    ]
    
    await conn.executemany(
        """
        INSERT INTO popular_items (geo_id, gender, age_group, category, item_id, popularity_score)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        popular_items_data
    )
    
    # Insert sample user profiles
    user_profiles_data = [
        ('123', '{"category:electronics": 0.6, "category:books": 0.4}', '{"ozon": 0.7, "wildberries": 0.3}', 1500.0, 200.0, 5000.0, 5),
        ('456', '{"category:sports": 0.8, "category:music": 0.2}', '{"ozon": 0.5, "amazon": 0.5}', 800.0, 100.0, 2000.0, 3),
    ]
    
    await conn.executemany(
        """
        INSERT INTO user_profiles (user_id, preferred_categories, preferred_platforms, avg_price, price_range_min, price_range_max, interaction_count)
        VALUES ($1, $2::jsonb, $3::jsonb, $4, $5, $6, $7)
        """,
        user_profiles_data
    )
    
    # Insert sample user similarities
    user_similarities_data = [
        ('123', '456', 0.75),
        ('456', '789', 0.65),
    ]
    
    await conn.executemany(
        """
        INSERT INTO user_similarities (user_id, similar_user_id, similarity_score)
        VALUES ($1, $2, $3)
        """,
        user_similarities_data
    )
    
    # Insert sample item similarities
    item_similarities_data = [
        ('101', '102', 0.8, 15, 20, 18),
        ('101', '103', 0.7, 12, 20, 15),
        ('102', '103', 0.6, 10, 18, 15),
    ]
    
    await conn.executemany(
        """
        INSERT INTO item_similarities (item_a, item_b, similarity_score, co_occurrence_count, item_a_total_likes, item_b_total_likes)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        item_similarities_data
    )