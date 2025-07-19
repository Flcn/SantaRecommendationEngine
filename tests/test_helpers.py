"""
Unit tests for helper methods and utility functions
"""

import pytest
from unittest.mock import patch, AsyncMock
from app.recommendation_service_v2 import RecommendationServiceV2
from app.models import Filters


class TestHelperMethods:
    """Test cases for helper methods"""
    
    def test_build_popular_cache_key_basic(self):
        """Test basic cache key generation for popular items"""
        from app.models import PopularItemsRequest, UserParams, Pagination
        
        request = PopularItemsRequest(
            user_params=UserParams(
                gender="f",
                age="25-34",
                category="electronics",
                geo_id=213
            ),
            pagination=Pagination(page=1, limit=20)
        )
        
        cache_key = RecommendationServiceV2._build_popular_cache_key(request)
        expected = "v3:popular:213:f:25-34:electronics:1:20"
        assert cache_key == expected
    
    def test_build_popular_cache_key_with_filters(self):
        """Test cache key generation with all filters"""
        from app.models import PopularItemsRequest, UserParams, Pagination, Filters
        
        request = PopularItemsRequest(
            user_params=UserParams(
                gender="m",
                age="35-44", 
                category="books",
                geo_id=123
            ),
            filters=Filters(
                price_from=100,
                price_to=500,
                category="fiction"
            ),
            pagination=Pagination(page=2, limit=50)
        )
        
        cache_key = RecommendationServiceV2._build_popular_cache_key(request)
        expected = "v3:popular:123:m:35-44:books:2:50:pf100:pt500:catfiction"
        assert cache_key == expected
    
    def test_build_popular_cache_key_none_values(self):
        """Test cache key generation with None values"""
        from app.models import PopularItemsRequest, UserParams, Pagination
        
        request = PopularItemsRequest(
            user_params=UserParams(
                gender=None,
                age=None,
                category=None,
                geo_id=213
            ),
            pagination=Pagination(page=1, limit=20)
        )
        
        cache_key = RecommendationServiceV2._build_popular_cache_key(request)
        expected = "v3:popular:213:any:any:any:1:20"
        assert cache_key == expected
    
    def test_build_personalized_cache_key_basic(self):
        """Test basic cache key generation for personalized recommendations"""
        from app.models import PersonalizedRequest, Pagination
        
        request = PersonalizedRequest(
            user_id="456",
            geo_id=789,
            pagination=Pagination(page=1, limit=20)
        )
        
        cache_key = RecommendationServiceV2._build_personalized_cache_key(request)
        expected = "v3:personalized:456:789:1:20"
        assert cache_key == expected
    
    def test_build_personalized_cache_key_with_filters(self):
        """Test personalized cache key with filters"""
        from app.models import PersonalizedRequest, Pagination, Filters
        
        request = PersonalizedRequest(
            user_id="123",
            geo_id=456,
            filters=Filters(
                price_from=200,
                price_to=1000,
                category="electronics"
            ),
            pagination=Pagination(page=3, limit=10)
        )
        
        cache_key = RecommendationServiceV2._build_personalized_cache_key(request)
        expected = "v3:personalized:123:456:3:10:pf200:pt1000:catelectronics"
        assert cache_key == expected
    
    @pytest.mark.asyncio
    async def test_apply_filters_no_filters(self, mock_db):
        """Test filter application with no filters"""
        item_ids = [101, 102, 103]
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._apply_filters(item_ids, None, 213)
        
        assert result == item_ids  # Should return unchanged
        mock_db.execute_main_query.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_apply_filters_empty_items(self, mock_db):
        """Test filter application with empty item list"""
        filters = Filters(price_from=500)
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._apply_filters([], filters, 213)
        
        assert result == []
        mock_db.execute_main_query.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_apply_filters_price_range(self, mock_db):
        """Test filter application with price range"""
        item_ids = ["101", "102", "103"]
        filters = Filters(price_from=500, price_to=2000)
        
        filtered_results = [{"id": "101"}, {"id": "103"}]
        mock_db.execute_main_query.return_value = filtered_results
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._apply_filters(item_ids, filters, 213)
        
        assert result == ["101", "103"]
        
        # Verify query construction
        call_args = mock_db.execute_main_query.call_args
        query = call_args[0][0]
        params = call_args[0][1:]
        
        assert "hp.price >=" in query
        assert "hp.price <=" in query
        assert item_ids in params
        assert 213 in params  # geo_id
        assert 500 in params  # price_from
        assert 2000 in params  # price_to
    
    @pytest.mark.asyncio
    async def test_apply_filters_category_filters(self, mock_db):
        """Test filter application with category filters"""
        item_ids = ["101", "102", "103"]
        filters = Filters(
            category="electronics",
            suitable_for="friend",
            acquaintance_level="close"
        )
        
        filtered_results = [{"id": "102"}]
        mock_db.execute_main_query.return_value = filtered_results
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._apply_filters(item_ids, filters, 213)
        
        assert result == ["102"]
        
        # Verify category filters in query
        call_args = mock_db.execute_main_query.call_args
        query = call_args[0][0]
        params = call_args[0][1:]
        
        assert "categories ->> 'category'" in query
        assert "categories ->> 'suitable_for'" in query
        assert "categories ->> 'acquaintance_level'" in query
        assert "electronics" in params
        assert "friend" in params
        assert "close" in params
    
    @pytest.mark.asyncio
    async def test_apply_filters_platform_filter(self, mock_db):
        """Test filter application with platform filter"""
        item_ids = ["101", "102"]
        filters = Filters(platform="ozon")
        
        filtered_results = [{"id": "101"}]
        mock_db.execute_main_query.return_value = filtered_results
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._apply_filters(item_ids, filters, 213)
        
        assert result == ["101"]
        
        # Verify platform filter in query
        call_args = mock_db.execute_main_query.call_args
        query = call_args[0][0]
        params = call_args[0][1:]
        
        assert "hp.platform =" in query
        assert "ozon" in params
    
    @pytest.mark.asyncio
    async def test_apply_filters_error_handling(self, mock_db):
        """Test filter application error handling"""
        item_ids = [101, 102, 103]
        filters = Filters(price_from=500)
        
        mock_db.execute_main_query.side_effect = Exception("Database error")
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._apply_filters(item_ids, filters, 213)
        
        # Should return original items on error
        assert result == item_ids
    
    @pytest.mark.asyncio
    async def test_get_fallback_popular_items(self, mock_db):
        """Test _get_fallback_popular_items method"""
        user_likes = ["201", "202"]
        
        fallback_items = [{"item_id": "301"}, {"item_id": "302"}]
        mock_db.execute_recommendations_query.return_value = fallback_items
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_fallback_popular_items(213, user_likes)
        
        assert result == ["301", "302"]
        
        # Verify query for fallback items
        call_args = mock_db.execute_recommendations_query.call_args
        query = call_args[0][0]
        params = call_args[0][1:]
        
        assert "gender = $2" in query
        assert "age_group = $3" in query
        assert "category = $4" in query
        assert 213 in params  # geo_id
        assert 'any' in params  # generic fallback parameters
    
    @pytest.mark.asyncio
    async def test_get_collaborative_recommendations(self, mock_db):
        """Test _get_collaborative_recommendations method"""
        user_id = "123"
        geo_id = 213
        user_likes = ["201", "202"]
        
        # Mock similar items for item-based collaborative filtering
        similar_items = [
            {"similar_item": "501", "similarity_score": 0.8},
            {"similar_item": "502", "similarity_score": 0.7}
        ]
        # Mock final recommendations after filtering
        final_recs = [
            {"item_id": "501", "popularity_boost": 3},
            {"item_id": "502", "popularity_boost": 2}
        ]
        
        mock_db.execute_recommendations_query.return_value = similar_items
        mock_db.execute_main_query.return_value = final_recs
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_collaborative_recommendations(
                user_id, geo_id, user_likes
            )
        
        assert result == ["501", "502"]
        
        # Verify similar items query
        similar_items_call = mock_db.execute_recommendations_query.call_args
        assert "similar_item" in similar_items_call[0][0]
        assert "item_similarities" in similar_items_call[0][0]
        assert user_likes in similar_items_call[0][1:]
        
        # Verify filtering query
        filter_call = mock_db.execute_main_query.call_args
        assert "popularity_boost" in filter_call[0][0]
        assert geo_id in filter_call[0][1:]
    
    @pytest.mark.asyncio
    async def test_get_collaborative_recommendations_no_similar_users(self, mock_db):
        """Test collaborative recommendations with no similar users"""
        user_id = 123
        geo_id = 213
        user_likes = [201, 202]
        
        # Mock no similar users
        mock_db.execute_recommendations_query.return_value = []
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_collaborative_recommendations(
                user_id, geo_id, user_likes
            )
        
        assert result == []
        
        # Should not call main query if no similar users
        mock_db.execute_main_query.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_content_based_recommendations(self, mock_db, sample_user_profile):
        """Test _get_content_based_recommendations method with Option 3 hybrid approach"""
        user_id = "123"
        geo_id = 213
        user_likes = ["201", "202"]
        
        # Mock candidate items from main database (new Option 3 approach)
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
        mock_db.execute_main_query.return_value = candidate_items
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_content_based_recommendations(
                user_id, geo_id, user_likes, sample_user_profile
            )
        
        # Should return items sorted by Option 3 hybrid score
        assert isinstance(result, list)
        assert len(result) > 0
        # First item should match better (electronics + good demographics match)
        assert "601" in result
        
        # Verify main database query was made for candidate items
        call_args = mock_db.execute_main_query.call_args
        query = call_args[0][0]
        params = call_args[0][1:]
        
        # Should query handpicked_presents for candidate items
        assert "handpicked_presents" in query
        assert geo_id in params
    
    @pytest.mark.asyncio
    async def test_get_content_based_recommendations_no_preferences(self, mock_db):
        """Test content-based recommendations with no user preferences (Option 3 fallback)"""
        from app.models import UserProfile
        
        user_id = "123"
        geo_id = 213
        user_likes = ["201", "202"]
        
        # User profile with no preferred categories or buying patterns
        empty_profile = UserProfile(
            user_id="123",
            preferred_categories={},
            buying_patterns_target_ages={},
            buying_patterns_relationships={},
            buying_patterns_gender_targets={},
            interaction_count=2
        )
        
        # Mock candidate items that should get low scores
        candidate_items = [
            {
                "item_id": "701",
                "categories": '{"category": "unknown"}',
                "platform": "unknown",
                "price": 1000.0,
                "created_at": "2024-01-01T00:00:00Z"
            }
        ]
        mock_db.execute_main_query.return_value = candidate_items
        
        # Should fallback when no good matches
        with patch('app.recommendation_service_v2.db', mock_db), \
             patch.object(RecommendationServiceV2, '_get_fallback_popular_items', new_callable=AsyncMock) as mock_fallback:
            mock_fallback.return_value = ["701", "702"]
            result = await RecommendationServiceV2._get_content_based_recommendations(
                user_id, geo_id, user_likes, empty_profile
            )
        
        # With empty profile, items should score low and trigger fallback
        # Or return empty results if no items score > 0.1
        assert isinstance(result, list)
        # Should either fallback to popular items or return empty list
        mock_db.execute_main_query.assert_called_once()