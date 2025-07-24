"""
Test cases for pagination-aware collaborative filtering
Tests that collaborative filtering respects the user's actual limit parameter
instead of using a hardcoded 100 items.
"""

import pytest
from unittest.mock import patch, AsyncMock
from app.recommendation_service_v2 import RecommendationServiceV2
from app.models import PersonalizedRequest, Pagination, UserProfile


class TestPaginationAwareCollaborative:
    """Test pagination-aware collaborative filtering behavior"""

    @pytest.fixture
    def mock_user_profile(self):
        """User profile with enough interactions for collaborative filtering"""
        return UserProfile(
            user_id="123",
            preferred_categories={"electronics": 0.6, "books": 0.4},
            preferred_platforms={"ozon": 0.7, "wildberries": 0.3},
            avg_price=1500.0,
            price_range_min=500.0,
            price_range_max=3000.0,
            buying_patterns_target_ages={"25-34": 0.8, "18-24": 0.2},
            buying_patterns_relationships={"friend": 0.6, "relative": 0.4},
            buying_patterns_gender_targets={"f": 0.7, "m": 0.3},
            interaction_count=5  # Enough for collaborative filtering
        )

    @pytest.fixture
    def sample_user_likes(self):
        """Sample user likes"""
        return [
            {"handpicked_present_id": "201"},
            {"handpicked_present_id": "202"},
            {"handpicked_present_id": "203"}
        ]

    @pytest.mark.asyncio
    async def test_collaborative_respects_page_1_limit_5(self, mock_db, mock_user_profile, sample_user_likes):
        """Test that collaborative filtering generates exactly enough items for page 1, limit 5"""
        
        # Setup request for page 1, limit 5 (needs 5 items total)
        request = PersonalizedRequest(
            user_id="123",
            geo_id=213,
            pagination=Pagination(page=1, limit=5)
        )

        mock_db.cache_get.return_value = None
        mock_db.execute_main_query.return_value = sample_user_likes
        mock_db.execute_recommendations_query_one.return_value = {
            'user_id': '123',
            'preferred_categories': mock_user_profile.preferred_categories,
            'preferred_platforms': mock_user_profile.preferred_platforms,
            'avg_price': mock_user_profile.avg_price,
            'price_range_min': mock_user_profile.price_range_min,
            'price_range_max': mock_user_profile.price_range_max,
            'buying_patterns_target_ages': mock_user_profile.buying_patterns_target_ages,
            'buying_patterns_relationships': mock_user_profile.buying_patterns_relationships,
            'buying_patterns_gender_targets': mock_user_profile.buying_patterns_gender_targets,
            'interaction_count': 5,
            'last_interaction_at': None
        }

        # Mock collaborative finding only 2 similar items
        similar_items = [
            {"similar_item": "501", "similarity_score": 0.8},
            {"similar_item": "502", "similarity_score": 0.7}
        ]
        mock_db.execute_recommendations_query.return_value = similar_items

        # Mock collaborative results + popular filler (should only request 3 more items, not 98)
        collaborative_results = [
            {"item_id": "501", "popularity_boost": 3},
            {"item_id": "502", "popularity_boost": 2}
        ]
        popular_filler = [
            {"item_id": "601"},
            {"item_id": "602"},
            {"item_id": "603"}  # Only 3 items to fill to 5 total
        ]
        
        mock_db.execute_main_query.side_effect = [
            sample_user_likes,  # User likes
            collaborative_results,  # Collaborative recommendations (2 items)
            popular_filler  # Popular filler (3 items to reach 5 total)
        ]

        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_personalized_recommendations(request)

        # Should have exactly 5 items (2 collaborative + 3 popular)
        assert len(response.items) == 5
        assert response.items == ['501', '502', '601', '602', '603']
        assert response.algorithm_used == "collaborative"

        # Verify that popular filler was called with limit=3 (not 98)
        popular_call = mock_db.execute_main_query.call_args_list[-1]
        assert popular_call[0][-1] == 3  # Last parameter should be 3 (items to add)

    @pytest.mark.asyncio
    async def test_collaborative_respects_page_2_limit_10(self, mock_db, mock_user_profile, sample_user_likes):
        """Test that collaborative filtering generates enough items for page 2, limit 10 (needs 20 items total)"""
        
        # Setup request for page 2, limit 10 (needs offset 10 + limit 10 = 20 items total)
        request = PersonalizedRequest(
            user_id="123",
            geo_id=213,
            pagination=Pagination(page=2, limit=10)
        )

        mock_db.cache_get.return_value = None
        mock_db.execute_main_query.return_value = sample_user_likes
        mock_db.execute_recommendations_query_one.return_value = {
            'user_id': '123',
            'preferred_categories': mock_user_profile.preferred_categories,
            'preferred_platforms': mock_user_profile.preferred_platforms,
            'avg_price': mock_user_profile.avg_price,
            'price_range_min': mock_user_profile.price_range_min,
            'price_range_max': mock_user_profile.price_range_max,
            'buying_patterns_target_ages': mock_user_profile.buying_patterns_target_ages,
            'buying_patterns_relationships': mock_user_profile.buying_patterns_relationships,
            'buying_patterns_gender_targets': mock_user_profile.buying_patterns_gender_targets,
            'interaction_count': 5,
            'last_interaction_at': None
        }

        # Mock collaborative finding only 5 similar items
        similar_items = [
            {"similar_item": f"50{i}", "similarity_score": 0.8 - i*0.1} 
            for i in range(1, 6)
        ]
        mock_db.execute_recommendations_query.return_value = similar_items

        # Mock collaborative results + popular filler (should request 15 more items to reach 20 total)
        collaborative_results = [
            {"item_id": f"50{i}", "popularity_boost": 6-i} 
            for i in range(1, 6)  # 5 items
        ]
        popular_filler = [
            {"item_id": f"60{i}"} 
            for i in range(1, 16)  # 15 items to fill to 20 total
        ]
        
        mock_db.execute_main_query.side_effect = [
            sample_user_likes,  # User likes
            collaborative_results,  # Collaborative recommendations (5 items)
            popular_filler  # Popular filler (15 items to reach 20 total)
        ]

        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_personalized_recommendations(request)

        # Should have exactly 10 items on page 2 (items 11-20 from the 20 total)
        assert len(response.items) == 10
        assert response.pagination.page == 2
        assert response.pagination.total_count == 20
        assert response.algorithm_used == "collaborative"

        # Verify that popular filler was called with limit=15 (not 95)
        popular_call = mock_db.execute_main_query.call_args_list[-1]
        assert popular_call[0][-1] == 15  # Last parameter should be 15 (items to add)

    @pytest.mark.asyncio
    async def test_collaborative_no_filler_when_enough_similar_items(self, mock_db, mock_user_profile, sample_user_likes):
        """Test that no popular filler is added when collaborative filtering finds enough items"""
        
        # Setup request for page 1, limit 5 (needs 5 items total)
        request = PersonalizedRequest(
            user_id="123", 
            geo_id=213,
            pagination=Pagination(page=1, limit=5)
        )

        mock_db.cache_get.return_value = None
        mock_db.execute_main_query.return_value = sample_user_likes
        mock_db.execute_recommendations_query_one.return_value = {
            'user_id': '123',
            'preferred_categories': mock_user_profile.preferred_categories,
            'preferred_platforms': mock_user_profile.preferred_platforms,
            'avg_price': mock_user_profile.avg_price,
            'price_range_min': mock_user_profile.price_range_min,
            'price_range_max': mock_user_profile.price_range_max,
            'buying_patterns_target_ages': mock_user_profile.buying_patterns_target_ages,
            'buying_patterns_relationships': mock_user_profile.buying_patterns_relationships,
            'buying_patterns_gender_targets': mock_user_profile.buying_patterns_gender_targets,
            'interaction_count': 5,
            'last_interaction_at': None
        }

        # Mock collaborative finding 10 similar items (more than needed for 5 items)
        similar_items = [
            {"similar_item": f"50{i}", "similarity_score": 0.9 - i*0.05} 
            for i in range(1, 11)
        ]
        mock_db.execute_recommendations_query.return_value = similar_items

        # Mock collaborative results - 10 items (enough, no filler needed)
        collaborative_results = [
            {"item_id": f"50{i}", "popularity_boost": 11-i} 
            for i in range(1, 11)  # 10 items
        ]
        
        mock_db.execute_main_query.side_effect = [
            sample_user_likes,  # User likes
            collaborative_results  # Collaborative recommendations (10 items, no filler call)
        ]

        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_personalized_recommendations(request)

        # Should have exactly 5 items on page 1 (sliced from 10 available)
        assert len(response.items) == 5
        assert response.items == ['501', '502', '503', '504', '505']
        assert response.pagination.total_count == 10
        assert response.algorithm_used == "collaborative"

        # Verify that popular filler was NOT called (only 2 execute_main_query calls)
        assert mock_db.execute_main_query.call_count == 2  # Only user likes + collaborative, no filler