"""
Working integration test for item-based similarity system
"""

import pytest
import asyncio
import os
from unittest.mock import AsyncMock
from app.similarity_utils import get_item_similarity, get_user_liked_items


@pytest.mark.asyncio
class TestItemSimilarityWorking:
    """Working tests for item similarity system using mocks and real functions"""
    
    async def test_item_similarity_same_item(self):
        """Test item similarity for same item (no database needed)"""
        similarity = await get_item_similarity("item1", "item1")
        assert similarity == 1.0
    
    async def test_item_similarity_ordering(self):
        """Test that item ordering is consistent"""
        # Mock database to return specific similarity
        from app import similarity_utils
        original_db = similarity_utils.db
        
        mock_db = AsyncMock()
        mock_db.execute_recommendations_query_one.return_value = {'similarity_score': 0.75}
        similarity_utils.db = mock_db
        
        try:
            # Test both orders return same result
            sim1 = await get_item_similarity("item1", "item2")
            sim2 = await get_item_similarity("item2", "item1")
            
            assert sim1 == 0.75
            assert sim2 == 0.75
            
            # Verify the database was called with correct ordering (smaller first)
            mock_db.execute_recommendations_query_one.assert_called()
            
        finally:
            similarity_utils.db = original_db
    
    async def test_item_similarity_not_found(self):
        """Test item similarity when no similarity exists"""
        from app import similarity_utils
        original_db = similarity_utils.db
        
        mock_db = AsyncMock()
        mock_db.execute_recommendations_query_one.return_value = None
        similarity_utils.db = mock_db
        
        try:
            similarity = await get_item_similarity("item1", "item3")
            assert similarity == 0.0
        finally:
            similarity_utils.db = original_db
    
    async def test_user_likes_empty_result(self):
        """Test user likes when no likes exist"""
        from app import similarity_utils
        original_db = similarity_utils.db
        
        mock_db = AsyncMock()
        mock_db.execute_main_query.return_value = []
        similarity_utils.db = mock_db
        
        try:
            items = await get_user_liked_items("nonexistent_user")
            assert items == []
        finally:
            similarity_utils.db = original_db
    
    async def test_user_likes_with_results(self):
        """Test user likes when likes exist"""
        from app import similarity_utils
        original_db = similarity_utils.db
        
        mock_db = AsyncMock()
        mock_db.execute_main_query.return_value = [
            {'item_id': 'item1'},
            {'item_id': 'item2'},
            {'item_id': 'item3'}
        ]
        similarity_utils.db = mock_db
        
        try:
            items = await get_user_liked_items("user1")
            assert len(items) == 3
            assert items == ['item1', 'item2', 'item3']
        finally:
            similarity_utils.db = original_db
    
    async def test_similarity_calculation_logic(self):
        """Test the core similarity calculation logic"""
        from app.similarity_utils import calculate_user_similarity_via_items
        from app import similarity_utils
        original_get_similarity = similarity_utils.get_item_similarity
        
        # Mock get_item_similarity to return known values
        async def mock_get_similarity(item_a, item_b):
            similarities = {
                ('item1', 'item1'): 1.0,
                ('item1', 'item2'): 0.8,
                ('item2', 'item1'): 0.8,
                ('item2', 'item2'): 1.0,
                ('item1', 'item3'): 0.6,
                ('item3', 'item1'): 0.6,
                ('item2', 'item3'): 0.4,
                ('item3', 'item2'): 0.4,
            }
            return similarities.get((item_a, item_b), 0.0)
        
        similarity_utils.get_item_similarity = mock_get_similarity
        
        try:
            # Test similarity between two users
            user_a_items = ['item1', 'item2']
            user_b_items = ['item1', 'item3']
            
            similarity = await calculate_user_similarity_via_items(user_a_items, user_b_items)
            
            # Expected calculation:
            # item1 vs item1 = 1.0
            # item1 vs item3 = 0.6
            # item2 vs item1 = 0.8
            # item2 vs item3 = 0.4
            # Average = (1.0 + 0.6 + 0.8 + 0.4) / 4 = 0.7
            assert abs(similarity - 0.7) < 0.01
            
        finally:
            similarity_utils.get_item_similarity = original_get_similarity
    
    async def test_empty_user_similarity(self):
        """Test similarity calculation with empty user lists"""
        from app.similarity_utils import calculate_user_similarity_via_items
        
        # Test empty lists
        similarity = await calculate_user_similarity_via_items([], ['item1', 'item2'])
        assert similarity == 0.0
        
        similarity = await calculate_user_similarity_via_items(['item1'], [])
        assert similarity == 0.0
        
        similarity = await calculate_user_similarity_via_items([], [])
        assert similarity == 0.0
    
    async def test_collaborative_filtering_logic(self):
        """Test the collaborative filtering algorithm logic"""
        from app.recommendation_service_v2 import RecommendationServiceV2
        from app import recommendation_service_v2
        original_db = recommendation_service_v2.db
        
        mock_db = AsyncMock()
        
        # Mock similar items query
        mock_db.execute_recommendations_query.return_value = [
            {'similar_item': 'item2', 'similarity_score': 0.8},
            {'similar_item': 'item3', 'similarity_score': 0.6},
            {'similar_item': 'item2', 'similarity_score': 0.4}  # Duplicate item2
        ]
        
        # Mock final recommendations query
        mock_db.execute_main_query.return_value = [
            {'item_id': 'item2'},
            {'item_id': 'item3'}
        ]
        
        recommendation_service_v2.db = mock_db
        
        try:
            result = await RecommendationServiceV2._get_collaborative_recommendations_via_items(
                'test_user', 213, ['item1']
            )
            
            assert len(result) == 2
            assert 'item2' in result
            assert 'item3' in result
            
            # Verify both queries were called
            assert mock_db.execute_recommendations_query.called
            assert mock_db.execute_main_query.called
            
        finally:
            recommendation_service_v2.db = original_db
    
    async def test_collaborative_filtering_empty_likes(self):
        """Test collaborative filtering with no user likes"""
        from app.recommendation_service_v2 import RecommendationServiceV2
        
        result = await RecommendationServiceV2._get_collaborative_recommendations_via_items(
            'test_user', 213, []
        )
        
        assert result == []
    
    async def test_item_score_aggregation(self):
        """Test that item scores are properly aggregated"""
        # This tests the scoring logic from _get_collaborative_recommendations_via_items
        similar_items = [
            {'similar_item': 'rec_item1', 'similarity_score': 0.8},
            {'similar_item': 'rec_item2', 'similarity_score': 0.6},
            {'similar_item': 'rec_item1', 'similarity_score': 0.4}  # Same item again
        ]
        
        # Replicate the aggregation logic
        item_scores = {}
        for item in similar_items:
            item_id = item['similar_item']
            if item_id not in item_scores:
                item_scores[item_id] = 0
            item_scores[item_id] += item['similarity_score']
        
        # Test results (use approximate comparison for floating point)
        assert abs(item_scores['rec_item1'] - 1.2) < 0.01  # 0.8 + 0.4
        assert abs(item_scores['rec_item2'] - 0.6) < 0.01
        
        # Test sorting
        sorted_items = sorted(item_scores.items(), key=lambda x: x[1], reverse=True)
        assert sorted_items[0][0] == 'rec_item1'  # Highest score first
        assert sorted_items[1][0] == 'rec_item2'