"""
Unit tests for popular items functionality
"""

import pytest
from unittest.mock import patch, AsyncMock
from app.recommendation_service_v2 import RecommendationServiceV2
from app.models import RecommendationResponse, PaginationInfo


class TestPopularItems:
    """Test cases for popular items recommendations"""
    
    @pytest.mark.unit
    async def test_get_popular_items_cache_hit(self, mock_db, sample_popular_request):
        """Test popular items with cache hit"""
        # Setup cache hit
        cached_data = {
            'items': [101, 102, 103],
            'pagination': {
                'page': 1,
                'limit': 20,
                'total_pages': 1,
                'has_next': False,
                'has_previous': False
            }
        }
        mock_db.cache_get.return_value = cached_data
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_popular_items(sample_popular_request)
        
        # Assertions
        assert isinstance(response, RecommendationResponse)
        assert response.items == [101, 102, 103]
        assert response.cache_hit is True
        assert response.algorithm_used == "popular"
        assert response.computation_time_ms < 100  # Should be very fast
        
        # Verify cache was called
        mock_db.cache_get.assert_called_once()
        mock_db.execute_recommendations_query.assert_not_called()
    
    @pytest.mark.unit
    async def test_get_popular_items_cache_miss(self, mock_db, sample_popular_request, sample_popular_items):
        """Test popular items with cache miss"""
        # Setup cache miss
        mock_db.cache_get.return_value = None
        mock_db.execute_recommendations_query.return_value = sample_popular_items
        mock_db.execute_main_query.return_value = sample_popular_items  # Filtered items
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_popular_items(sample_popular_request)
        
        # Assertions
        assert isinstance(response, RecommendationResponse)
        assert response.items == [101, 102, 103, 104, 105]
        assert response.cache_hit is False
        assert response.algorithm_used == "popular"
        assert response.pagination.page == 1
        assert response.pagination.limit == 20
        
        # Verify database queries were called
        mock_db.execute_recommendations_query.assert_called_once()
        mock_db.execute_main_query.assert_called_once()
        mock_db.cache_set.assert_called_once()
    
    @pytest.mark.unit
    async def test_get_popular_items_with_filters(self, mock_db, sample_popular_request, sample_popular_items):
        """Test popular items with price filters applied"""
        mock_db.cache_get.return_value = None
        mock_db.execute_recommendations_query.return_value = sample_popular_items
        
        # Mock filtered results (fewer items after price filter)
        filtered_items = [{"id": 101}, {"id": 103}]
        mock_db.execute_main_query.return_value = filtered_items
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_popular_items(sample_popular_request)
        
        # Assertions
        assert response.items == [101, 103]
        assert len(response.items) == 2
        
        # Verify filter query was called with price parameters
        filter_call = mock_db.execute_main_query.call_args
        assert "hp.price >=" in filter_call[0][0]  # Query should contain price filter
        assert 500 in filter_call[0][1:]  # price_from parameter
        assert 2000 in filter_call[0][1:]  # price_to parameter
    
    @pytest.mark.unit
    async def test_get_popular_items_pagination(self, mock_db, sample_popular_request):
        """Test popular items pagination"""
        # Setup large dataset
        large_dataset = [{"item_id": i} for i in range(1, 101)]  # 100 items
        mock_db.cache_get.return_value = None
        mock_db.execute_recommendations_query.return_value = large_dataset
        mock_db.execute_main_query.return_value = [{"id": i} for i in range(1, 101)]
        
        # Test page 1
        sample_popular_request.pagination.page = 1
        sample_popular_request.pagination.limit = 20
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_popular_items(sample_popular_request)
        
        # Assertions for pagination
        assert len(response.items) == 20
        assert response.items == list(range(1, 21))  # First 20 items
        assert response.pagination.page == 1
        assert response.pagination.has_next is True
        assert response.pagination.has_previous is False
        assert response.pagination.total_pages == 5  # 100 / 20 = 5
    
    @pytest.mark.unit
    async def test_get_popular_items_empty_result(self, mock_db, sample_popular_request):
        """Test popular items with empty result"""
        mock_db.cache_get.return_value = None
        mock_db.execute_recommendations_query.return_value = []
        mock_db.execute_main_query.return_value = []
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_popular_items(sample_popular_request)
        
        # Assertions
        assert response.items == []
        assert response.pagination.total_pages == 0
        assert response.pagination.has_next is False
        assert response.pagination.has_previous is False
    
    @pytest.mark.unit
    async def test_get_popular_items_error_handling(self, mock_db, sample_popular_request):
        """Test popular items error handling"""
        mock_db.cache_get.return_value = None
        mock_db.execute_recommendations_query.side_effect = Exception("Database error")
        
        with patch('app.recommendation_service_v2.db', mock_db):
            response = await RecommendationServiceV2.get_popular_items(sample_popular_request)
        
        # Should return empty result on error
        assert response.items == []
        assert response.algorithm_used == "popular_error"
        assert response.pagination.total_pages == 0
    
    @pytest.mark.unit
    def test_build_popular_cache_key(self, sample_popular_request):
        """Test cache key generation for popular items"""
        cache_key = RecommendationServiceV2._build_popular_cache_key(sample_popular_request)
        
        expected_key = "popular:213:f:25-34:electronics:1:20:pf500.0:pt2000.0"
        assert cache_key == expected_key
    
    @pytest.mark.unit
    def test_build_popular_cache_key_no_filters(self):
        """Test cache key generation without filters"""
        from app.models import PopularItemsRequest, UserParams, Pagination
        
        request = PopularItemsRequest(
            user_params=UserParams(geo_id=213),
            pagination=Pagination(page=1, limit=10)
        )
        
        cache_key = RecommendationServiceV2._build_popular_cache_key(request)
        expected_key = "popular:213:any:any:any:1:10"
        assert cache_key == expected_key
    
    @pytest.mark.unit
    async def test_query_popular_items(self, mock_db):
        """Test _query_popular_items method"""
        from app.models import PopularItemsRequest, UserParams
        
        request = PopularItemsRequest(
            user_params=UserParams(
                gender="f",
                age="25-34", 
                category="electronics",
                geo_id=213
            )
        )
        
        mock_db.execute_recommendations_query.return_value = [
            {"item_id": 101},
            {"item_id": 102}
        ]
        
        with patch('app.recommendation_service_v2.db', mock_db):
            result = await RecommendationServiceV2._query_popular_items(request)
        
        assert result == [101, 102]
        
        # Verify query parameters
        call_args = mock_db.execute_recommendations_query.call_args
        assert call_args[0][1] == 213  # geo_id
        assert call_args[0][2] == "f"  # gender
        assert call_args[0][3] == "25-34"  # age
        assert call_args[0][4] == "electronics"  # category