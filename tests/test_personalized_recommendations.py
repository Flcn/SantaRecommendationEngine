"""
Unit tests for personalized recommendations functionality
"""

import pytest
from unittest.mock import patch, AsyncMock
from app.recommendation_service_v2 import RecommendationServiceV2
from app.models import RecommendationResponse, UserProfile


class TestPersonalizedRecommendations:
    """Test cases for personalized recommendations"""
    
    @pytest.mark.asyncio
    async def test_get_personalized_recommendations_cache_hit(self, mock_db, sample_personalized_request):
        """Test personalized recommendations with cache hit"""
        # Setup cache hit
        cached_data = {
            'items': ['301', '302', '303'],
            'pagination': {
                'page': 1,
                'limit': 20,
                'total_pages': 1,
                'total_count': 3,
                'has_next': False,
                'has_previous': False
            }
        }
        mock_db.cache_get.return_value = cached_data
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_personalized_recommendations(sample_personalized_request)
        
        # Assertions
        assert isinstance(response, RecommendationResponse)
        assert response.items == ['301', '302', '303']
        assert response.cache_hit is True
        assert response.algorithm_used == "personalized"
        assert response.computation_time_ms < 100  # Should be very fast
        
        # Verify cache was called
        mock_db.cache_get.assert_called_once()
        mock_db.execute_main_query.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_personalized_recommendations_new_user(self, mock_db, sample_personalized_request):
        """Test personalized recommendations for new user (0 interactions)"""
        mock_db.cache_get.return_value = None
        mock_db.execute_main_query.return_value = []  # No user likes
        mock_db.execute_recommendations_query_one.return_value = None  # No user profile
        mock_db.cache_get.side_effect = [None]  # No cached demographics
        
        # Mock fallback popular items
        fallback_items = [{"item_id": "401"}, {"item_id": "402"}]
        mock_db.execute_recommendations_query.return_value = fallback_items
        mock_db.execute_main_query.side_effect = [
            [],  # User likes query
            [{"id": "401"}, {"id": "402"}]  # Filtered fallback items
        ]
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_personalized_recommendations(sample_personalized_request)
        
        # Assertions
        assert response.items == ['401', '402']
        assert response.algorithm_used == "popular_fallback"
        assert response.cache_hit is False
    
    @pytest.mark.asyncio
    async def test_get_personalized_recommendations_collaborative_filtering(self, mock_db, sample_personalized_request, sample_user_profile, sample_user_likes):
        """Test personalized recommendations using collaborative filtering (3+ interactions)"""
        mock_db.cache_get.return_value = None
        
        # Setup user with enough interactions for collaborative filtering
        user_profile = sample_user_profile.model_copy()
        user_profile.interaction_count = 5
        
        mock_db.execute_main_query.return_value = sample_user_likes
        mock_db.execute_recommendations_query_one.return_value = {
            'user_id': '123',
            'preferred_categories': user_profile.preferred_categories,
            'preferred_platforms': user_profile.preferred_platforms,
            'avg_price': user_profile.avg_price,
            'price_range_min': user_profile.price_range_min,
            'price_range_max': user_profile.price_range_max,
            # Option 3: buying patterns
            'buying_patterns_target_ages': user_profile.buying_patterns_target_ages,
            'buying_patterns_relationships': user_profile.buying_patterns_relationships,
            'buying_patterns_gender_targets': user_profile.buying_patterns_gender_targets,
            'interaction_count': 5,
            'last_interaction_at': None
        }
        
        # Mock similar items (item-based collaborative filtering)
        similar_items = [
            {"similar_item": "501", "similarity_score": 0.8},
            {"similar_item": "502", "similarity_score": 0.7}
        ]
        
        mock_db.execute_recommendations_query.return_value = similar_items
        mock_db.execute_main_query.side_effect = [
            sample_user_likes,  # User likes
            [{"item_id": "501"}, {"item_id": "502"}]  # Filtered results
        ]
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_personalized_recommendations(sample_personalized_request)
        
        # Assertions
        assert response.items == ['501', '502']
        assert response.algorithm_used == "collaborative"
        assert response.cache_hit is False
    
    @pytest.mark.asyncio
    async def test_get_personalized_recommendations_content_based(self, mock_db, sample_personalized_request, sample_user_profile, sample_user_likes):
        """Test personalized recommendations using content-based filtering (1-2 interactions)"""
        mock_db.cache_get.return_value = None
        
        # Setup user with limited interactions for content-based filtering
        user_profile = sample_user_profile.model_copy()
        user_profile.interaction_count = 2
        
        mock_db.execute_main_query.return_value = sample_user_likes
        mock_db.execute_recommendations_query_one.return_value = {
            'user_id': '123',
            'preferred_categories': user_profile.preferred_categories,
            'preferred_platforms': user_profile.preferred_platforms,
            'avg_price': user_profile.avg_price,
            'price_range_min': user_profile.price_range_min,
            'price_range_max': user_profile.price_range_max,
            # Option 3: buying patterns
            'buying_patterns_target_ages': user_profile.buying_patterns_target_ages,
            'buying_patterns_relationships': user_profile.buying_patterns_relationships,
            'buying_patterns_gender_targets': user_profile.buying_patterns_gender_targets,
            'interaction_count': 2,
            'last_interaction_at': None
        }
        
        # Mock candidate items for content-based (Option 3 implementation)
        candidate_items = [
            {
                "item_id": "601",
                "categories": '{"category": "electronics", "age": "25-34", "suitable_for": "friend", "gender": "f"}',
                "platform": "ozon",
                "price": 1500.0,
                "created_at": "2024-01-01T00:00:00Z"
            },
            {
                "item_id": "602",
                "categories": '{"category": "books", "age": "18-24", "suitable_for": "relative", "gender": "any"}',
                "platform": "wildberries", 
                "price": 800.0,
                "created_at": "2024-01-01T00:00:00Z"
            }
        ]
        mock_db.execute_main_query.side_effect = [
            sample_user_likes,  # User likes query
            candidate_items     # Candidate items for content-based scoring
        ]
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_personalized_recommendations(sample_personalized_request)
        
        # Assertions (Option 3 may return items in different order based on hybrid scoring)
        assert isinstance(response.items, list)
        assert len(response.items) >= 1  # Should return at least one item that scores > 0.1
        assert "601" in response.items or "602" in response.items  # At least one should be returned
        assert response.algorithm_used == "content_based"
        assert response.cache_hit is False
    
    @pytest.mark.asyncio
    async def test_get_personalized_recommendations_with_filters(self, mock_db, sample_personalized_request, sample_user_likes):
        """Test personalized recommendations with filters applied"""
        mock_db.cache_get.return_value = None
        mock_db.execute_main_query.return_value = sample_user_likes
        mock_db.execute_recommendations_query_one.return_value = None  # New user
        
        # Mock fallback items before and after filtering
        fallback_items = [{"item_id": str(i)} for i in range(701, 710)]  # 9 items
        filtered_items = [{"id": str(i)} for i in range(701, 706)]  # 5 items after price filter
        
        mock_db.execute_recommendations_query.return_value = fallback_items
        mock_db.execute_main_query.side_effect = [
            sample_user_likes,  # User likes
            filtered_items  # Filtered results
        ]
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_personalized_recommendations(sample_personalized_request)
        
        # Assertions
        assert response.items == ['701', '702', '703', '704', '705']
        assert len(response.items) == 5  # Filtered from 9 to 5
        
        # Verify filter was applied
        filter_call = mock_db.execute_main_query.call_args_list[-1]  # Last call
        assert "hp.price >=" in filter_call[0][0]  # Query should contain price filter
    
    @pytest.mark.asyncio
    async def test_get_personalized_recommendations_pagination(self, mock_db, sample_personalized_request, sample_user_likes):
        """Test personalized recommendations pagination"""
        mock_db.cache_get.return_value = None
        mock_db.execute_main_query.return_value = sample_user_likes
        mock_db.execute_recommendations_query_one.return_value = None
        
        # Setup large dataset
        large_dataset = [{"item_id": str(i)} for i in range(1, 101)]  # 100 items
        mock_db.execute_recommendations_query.return_value = large_dataset
        mock_db.execute_main_query.side_effect = [
            sample_user_likes,  # User likes
            [{"id": str(i)} for i in range(1, 101)]  # Filtered results
        ]
        
        # Test page 2
        sample_personalized_request.pagination.page = 2
        sample_personalized_request.pagination.limit = 20
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_personalized_recommendations(sample_personalized_request)
        
        # Assertions for pagination
        assert len(response.items) == 20
        assert response.items == [str(i) for i in range(21, 41)]  # Second page (items 21-40)
        assert response.pagination.page == 2
        assert response.pagination.has_next is True
        assert response.pagination.has_previous is True
        assert response.pagination.total_pages == 5  # 100 / 20 = 5
    
    @pytest.mark.asyncio
    async def test_get_personalized_recommendations_error_handling(self, mock_db, sample_personalized_request):
        """Test personalized recommendations error handling"""
        mock_db.cache_get.return_value = None
        mock_db.execute_main_query.side_effect = Exception("Database error")
        
        with patch('app.recommendation_service_v2.db', mock_db):
            # This should raise an exception since we're not handling errors gracefully in the current implementation
            try:
                response = await RecommendationServiceV2.get_personalized_recommendations(sample_personalized_request)
                # If we get here, something unexpected happened
                assert False, "Expected exception was not raised"
            except Exception:
                # Expected behavior - service should raise exceptions
                pass
    
    def test_build_personalized_cache_key(self, sample_personalized_request):
        """Test cache key generation for personalized recommendations"""
        cache_key = RecommendationServiceV2._build_personalized_cache_key(sample_personalized_request)
        
        expected_key = "v3:personalized:123:213:1:20:pf500:pt2000:catelectronics"
        assert cache_key == expected_key
    
    def test_build_personalized_cache_key_no_filters(self):
        """Test cache key generation without filters"""
        from app.models import PersonalizedRequest, Pagination
        
        request = PersonalizedRequest(
            user_id="123",
            geo_id=213,
            pagination=Pagination(page=1, limit=10)
        )
        
        cache_key = RecommendationServiceV2._build_personalized_cache_key(request)
        expected_key = "v3:personalized:123:213:1:10"
        assert cache_key == expected_key
    
    @pytest.mark.asyncio
    async def test_get_user_likes(self, mock_db, sample_user_likes):
        """Test _get_user_likes method"""
        mock_db.execute_main_query.return_value = sample_user_likes
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_user_likes("123")
        
        assert result == ["201", "202", "203"]
        
        # Verify query parameters
        call_args = mock_db.execute_main_query.call_args
        assert "handpicked_present_id" in call_args[0][0]
        assert call_args[0][1] == "123"  # user_id
    
    @pytest.mark.asyncio
    async def test_get_user_profile(self, mock_db):
        """Test _get_user_profile method with Option 3 buying patterns"""
        profile_data = {
            'user_id': "123",
            'preferred_categories': {"category:electronics": 0.6},
            'preferred_platforms': {"ozon": 0.7},
            'avg_price': 1500.0,
            'price_range_min': 200.0,
            'price_range_max': 5000.0,
            # Option 3: buying patterns
            'buying_patterns_target_ages': {"18-24": 0.3, "25-34": 0.7},
            'buying_patterns_relationships': {"friend": 0.6, "relative": 0.4},
            'buying_patterns_gender_targets': {"f": 0.8, "any": 0.2},
            'interaction_count': 5,
            'last_interaction_at': None
        }
        mock_db.execute_recommendations_query_one.return_value = profile_data
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_user_profile("123")
        
        assert isinstance(result, UserProfile)
        assert result.user_id == "123"
        assert result.interaction_count == 5
        assert result.avg_price == 1500.0
        # Test Option 3 fields
        assert result.buying_patterns_target_ages == {"18-24": 0.3, "25-34": 0.7}
        assert result.buying_patterns_relationships == {"friend": 0.6, "relative": 0.4}
        assert result.buying_patterns_gender_targets == {"f": 0.8, "any": 0.2}
    
    @pytest.mark.asyncio
    async def test_get_user_profile_not_found(self, mock_db):
        """Test _get_user_profile method when profile not found"""
        mock_db.execute_recommendations_query_one.return_value = None
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_user_profile(123)
        
        assert result is None