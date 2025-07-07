"""
Unit tests for helper methods and utility functions
"""

import pytest
from unittest.mock import patch, AsyncMock
from app.recommendation_service_v2 import RecommendationServiceV2
from app.models import Filters


class TestHelperMethods:
    """Test cases for helper methods"""
    
    @pytest.mark.unit
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
    
    @pytest.mark.unit
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
    
    @pytest.mark.unit
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
    
    @pytest.mark.unit
    def test_build_personalized_cache_key_basic(self):
        """Test basic cache key generation for personalized recommendations"""
        from app.models import PersonalizedRequest, Pagination
        
        request = PersonalizedRequest(
            user_id=456,
            geo_id=789,
            pagination=Pagination(page=1, limit=20)
        )
        
        cache_key = RecommendationServiceV2._build_personalized_cache_key(request)
        expected = "v3:personalized:456:789:1:20"
        assert cache_key == expected
    
    @pytest.mark.unit
    def test_build_personalized_cache_key_with_filters(self):
        """Test personalized cache key with filters"""
        from app.models import PersonalizedRequest, Pagination, Filters
        
        request = PersonalizedRequest(
            user_id=123,
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
        item_ids = [101, 102, 103]
        filters = Filters(price_from=500, price_to=2000)
        
        filtered_results = [{"id": 101}, {"id": 103}]
        mock_db.execute_main_query.return_value = filtered_results
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._apply_filters(item_ids, filters, 213)
        
        assert result == [101, 103]
        
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
        item_ids = [101, 102, 103]
        filters = Filters(
            category="electronics",
            suitable_for="friend",
            acquaintance_level="close"
        )
        
        filtered_results = [{"id": 102}]
        mock_db.execute_main_query.return_value = filtered_results
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._apply_filters(item_ids, filters, 213)
        
        assert result == [102]
        
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
        item_ids = [101, 102]
        filters = Filters(platform="ozon")
        
        filtered_results = [{"id": 101}]
        mock_db.execute_main_query.return_value = filtered_results
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._apply_filters(item_ids, filters, 213)
        
        assert result == [101]
        
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
        user_likes = [201, 202]
        
        fallback_items = [{"item_id": 301}, {"item_id": 302}]
        mock_db.execute_recommendations_query.return_value = fallback_items
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_fallback_popular_items(213, user_likes)
        
        assert result == [301, 302]
        
        # Verify query for fallback items
        call_args = mock_db.execute_recommendations_query.call_args
        query = call_args[0][0]
        params = call_args[0][1:]
        
        assert "gender = 'any'" in query
        assert "age_group = 'any'" in query
        assert "category = 'any'" in query
        assert 213 in params  # geo_id
    
    @pytest.mark.asyncio
    async def test_get_collaborative_recommendations(self, mock_db):
        """Test _get_collaborative_recommendations method"""
        user_id = 123
        geo_id = 213
        user_likes = [201, 202]
        
        # Mock similar users
        similar_users = [{"similar_user_id": 456}, {"similar_user_id": 789}]
        mock_db.execute_recommendations_query.return_value = similar_users
        
        # Mock collaborative recommendations
        collaborative_recs = [
            {"item_id": 501, "like_count": 3},
            {"item_id": 502, "like_count": 2}
        ]
        mock_db.execute_main_query.return_value = collaborative_recs
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_collaborative_recommendations(
                user_id, geo_id, user_likes
            )
        
        assert result == [501, 502]
        
        # Verify similar users query
        similar_users_call = mock_db.execute_recommendations_query.call_args
        assert "similar_user_id" in similar_users_call[0][0]
        assert user_id in similar_users_call[0][1:]
        
        # Verify collaborative recommendations query
        collab_call = mock_db.execute_main_query.call_args
        assert "COUNT(*) as like_count" in collab_call[0][0]
        assert [456, 789] in collab_call[0][1:]  # similar user ids
        assert geo_id in collab_call[0][1:]
    
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
        """Test _get_content_based_recommendations method"""
        user_id = 123
        geo_id = 213
        user_likes = [201, 202]
        
        content_items = [{"item_id": 601}, {"item_id": 602}]
        mock_db.execute_recommendations_query.return_value = content_items
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_content_based_recommendations(
                user_id, geo_id, user_likes, sample_user_profile
            )
        
        assert result == [601, 602]
        
        # Verify content-based query
        call_args = mock_db.execute_recommendations_query.call_args
        query = call_args[0][0]
        params = call_args[0][1:]
        
        # Should use preferred categories from profile and check if content-based query was made
        assert "category = ANY" in query or "item_id" in query
        assert geo_id in params
    
    @pytest.mark.asyncio
    async def test_get_content_based_recommendations_no_preferences(self, mock_db):
        """Test content-based recommendations with no user preferences"""
        from app.models import UserProfile
        
        user_id = 123
        geo_id = 213
        user_likes = [201, 202]
        
        # User profile with no preferred categories
        empty_profile = UserProfile(
            user_id=123,
            preferred_categories={},
            interaction_count=2
        )
        
        # Should fallback to popular items
        fallback_items = [{"item_id": 701}, {"item_id": 702}]
        mock_db.execute_recommendations_query.return_value = fallback_items
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._get_content_based_recommendations(
                user_id, geo_id, user_likes, empty_profile
            )
        
        assert result == [701, 702]
        mock_fallback.assert_called_once_with(geo_id, user_likes)