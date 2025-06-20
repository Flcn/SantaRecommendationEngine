"""
Main recommendation service that combines different algorithms
"""

import time
import logging
from typing import List, Dict, Any, Tuple, Optional
from app.database import db
from app.config import settings
from app.algorithms.collaborative import CollaborativeFilter
from app.algorithms.content_based import ContentBasedFilter
from app.algorithms.popularity import PopularityRecommender
from app.models import RecommendationRequest, PopularItemsRequest, RecommendationResponse

logger = logging.getLogger(__name__)


class RecommendationService:
    """Main recommendation service combining multiple algorithms"""
    
    @staticmethod
    async def get_recommendations(request: RecommendationRequest) -> RecommendationResponse:
        """
        Get personalized recommendations for a user
        Combines collaborative filtering, content-based, and popularity
        """
        start_time = time.time()
        
        try:
            # Check if user has enough data for personalized recommendations
            interaction_count = await CollaborativeFilter.get_user_interaction_count(request.user_id)
            
            if interaction_count >= 3:
                # User has enough data - use hybrid approach
                item_ids = await RecommendationService._get_hybrid_recommendations(request)
                algorithm_used = "hybrid"
            elif interaction_count > 0:
                # User has some data - use content-based + popular
                item_ids = await RecommendationService._get_content_popular_recommendations(request)
                algorithm_used = "content_popular"
            else:
                # New user - use popularity-based
                popular_request = PopularItemsRequest(
                    geo_id=request.geo_id,
                    limit=request.limit,
                    offset=request.offset,
                    user_id=request.user_id,
                    **request.dict(exclude={'user_id', 'geo_id', 'limit', 'offset'})
                )
                item_ids = await RecommendationService._get_popular_recommendations(popular_request)
                algorithm_used = "popularity"
            
            # Apply filters
            filtered_ids = await RecommendationService._apply_filters(item_ids, request)
            
            # Paginate
            paginated_ids = filtered_ids[request.offset:request.offset + request.limit]
            
            computation_time = (time.time() - start_time) * 1000
            
            return RecommendationResponse(
                item_ids=paginated_ids,
                total_count=len(filtered_ids),
                has_more=(request.offset + request.limit) < len(filtered_ids),
                computation_time_ms=computation_time,
                algorithm_used=algorithm_used
            )
            
        except Exception as e:
            logger.error(f"Error in recommendation service: {e}")
            # Fallback to popular items
            popular_request = PopularItemsRequest(
                geo_id=request.geo_id,
                limit=request.limit,
                offset=request.offset
            )
            item_ids = await RecommendationService._get_popular_recommendations(popular_request)
            
            computation_time = (time.time() - start_time) * 1000
            
            return RecommendationResponse(
                item_ids=item_ids,
                total_count=len(item_ids),
                has_more=False,
                computation_time_ms=computation_time,
                algorithm_used="fallback_popular"
            )
    
    @staticmethod
    async def _get_hybrid_recommendations(request: RecommendationRequest) -> List[int]:
        """
        Hybrid recommendations combining collaborative filtering, content-based, and popularity
        """
        # Get recommendations from each algorithm
        collaborative_recs = await CollaborativeFilter.get_collaborative_recommendations(
            request.user_id, request.geo_id, limit=100
        )
        
        content_recs = await ContentBasedFilter.get_content_recommendations(
            request.user_id, request.geo_id, limit=100
        )
        
        popular_recs = await PopularityRecommender.get_popular_items(
            request.geo_id, limit=50, user_id=request.user_id
        )
        
        # Combine with weights: 50% collaborative, 30% content, 20% popular
        item_scores: Dict[int, float] = {}
        
        # Collaborative filtering (50% weight)
        for item_id, score in collaborative_recs:
            item_scores[item_id] = item_scores.get(item_id, 0) + (score * 0.5)
        
        # Content-based (30% weight)
        for item_id, score in content_recs:
            item_scores[item_id] = item_scores.get(item_id, 0) + (score * 0.3)
        
        # Popularity (20% weight)
        max_popular_score = max([score for _, score in popular_recs]) if popular_recs else 1
        for item_id, score in popular_recs:
            normalized_score = score / max_popular_score if max_popular_score > 0 else 0
            item_scores[item_id] = item_scores.get(item_id, 0) + (normalized_score * 0.2)
        
        # Sort by combined score
        sorted_items = sorted(item_scores.items(), key=lambda x: x[1], reverse=True)
        return [item_id for item_id, _ in sorted_items[:settings.max_recommendation_items]]
    
    @staticmethod
    async def _get_content_popular_recommendations(request: RecommendationRequest) -> List[int]:
        """
        Content-based + popularity for users with some interaction history
        """
        content_recs = await ContentBasedFilter.get_content_recommendations(
            request.user_id, request.geo_id, limit=100
        )
        
        popular_recs = await PopularityRecommender.get_popular_items(
            request.geo_id, limit=50, user_id=request.user_id
        )
        
        # Combine: 70% content, 30% popular
        item_scores: Dict[int, float] = {}
        
        for item_id, score in content_recs:
            item_scores[item_id] = item_scores.get(item_id, 0) + (score * 0.7)
        
        max_popular_score = max([score for _, score in popular_recs]) if popular_recs else 1
        for item_id, score in popular_recs:
            normalized_score = score / max_popular_score if max_popular_score > 0 else 0
            item_scores[item_id] = item_scores.get(item_id, 0) + (normalized_score * 0.3)
        
        sorted_items = sorted(item_scores.items(), key=lambda x: x[1], reverse=True)
        return [item_id for item_id, _ in sorted_items[:settings.max_recommendation_items]]
    
    @staticmethod
    async def _get_popular_recommendations(request: PopularItemsRequest) -> List[int]:
        """Get popular items for new users or fallback"""
        popular_recs = await PopularityRecommender.get_popular_items(
            request.geo_id, 
            limit=settings.max_recommendation_items,
            user_id=request.user_id
        )
        return [item_id for item_id, _ in popular_recs]
    
    @staticmethod
    async def _apply_filters(item_ids: List[int], request: RecommendationRequest) -> List[int]:
        """
        Apply real-time filters to recommendation results
        This is fast since it only filters the pre-computed recommendation list
        """
        if not item_ids:
            return []
        
        # Build filter conditions
        filter_conditions = ["hp.id = ANY($1::int[])", "hp.status = 'in_stock'", "hp.geo_id = $2"]
        filter_params = [item_ids, request.geo_id]
        param_count = 2
        
        # Price filters
        if request.price_from is not None:
            param_count += 1
            filter_conditions.append(f"hp.price >= ${param_count}")
            filter_params.append(request.price_from)
        
        if request.price_to is not None:
            param_count += 1
            filter_conditions.append(f"hp.price <= ${param_count}")
            filter_params.append(request.price_to)
        
        # Category filters
        category_filters = ['gender', 'age', 'category', 'suitable_for', 'acquaintance_level']
        for cat_filter in category_filters:
            value = getattr(request, cat_filter, None)
            if value:
                param_count += 1
                filter_conditions.append(f"hp.categories ->> '{cat_filter}' = ${param_count}")
                filter_params.append(value)
        
        # Platform filter
        if request.platform:
            param_count += 1
            filter_conditions.append(f"hp.platform = ${param_count}")
            filter_params.append(request.platform)
        
        # Execute filter query
        filter_query = f"""
            SELECT id
            FROM handpicked_presents hp
            WHERE {' AND '.join(filter_conditions)}
            ORDER BY array_position($1::int[], hp.id)
        """
        
        try:
            filtered_results = await db.execute_query(filter_query, *filter_params)
            return [row['id'] for row in filtered_results]
        except Exception as e:
            logger.error(f"Error applying filters: {e}")
            return item_ids  # Return unfiltered if filter fails
    
    @staticmethod
    async def get_popular_items(request: PopularItemsRequest) -> RecommendationResponse:
        """Get popular items for a geographic region"""
        start_time = time.time()
        
        try:
            # Get popular items
            popular_items = await PopularityRecommender.get_popular_items(
                request.geo_id,
                limit=settings.max_recommendation_items,
                user_id=request.user_id
            )
            
            item_ids = [item_id for item_id, _ in popular_items]
            
            # Apply filters
            filter_request = RecommendationRequest(
                user_id=request.user_id or 0,
                geo_id=request.geo_id,
                limit=request.limit,
                offset=request.offset,
                **request.dict(exclude={'user_id', 'geo_id', 'limit', 'offset'})
            )
            filtered_ids = await RecommendationService._apply_filters(item_ids, filter_request)
            
            # Paginate
            paginated_ids = filtered_ids[request.offset:request.offset + request.limit]
            
            computation_time = (time.time() - start_time) * 1000
            
            return RecommendationResponse(
                item_ids=paginated_ids,
                total_count=len(filtered_ids),
                has_more=(request.offset + request.limit) < len(filtered_ids),
                computation_time_ms=computation_time,
                algorithm_used="popularity"
            )
            
        except Exception as e:
            logger.error(f"Error getting popular items: {e}")
            computation_time = (time.time() - start_time) * 1000
            
            return RecommendationResponse(
                item_ids=[],
                total_count=0,
                has_more=False,
                computation_time_ms=computation_time,
                algorithm_used="error_fallback"
            )
    
    @staticmethod
    async def get_similar_users(user_id: int, limit: int = 20) -> List[int]:
        """Get users similar to the given user"""
        return await CollaborativeFilter.find_similar_users(user_id, limit)
    
    @staticmethod
    async def get_similar_items(item_id: int, geo_id: int, limit: int = 20) -> List[int]:
        """Get items similar to the given item"""
        similar_items = await ContentBasedFilter.get_similar_items(item_id, geo_id, limit)
        return [item_id for item_id, _ in similar_items]