"""
Clean recommendation service with two core APIs:
1. Popular items based on user demographics  
2. Personalized recommendations based on user likes
"""

import time
import logging
import math
from typing import List, Dict, Any, Tuple, Optional
from app.database import db
from app.config import settings
from app.models import (
    PopularItemsRequest, 
    PersonalizedRequest, 
    RecommendationResponse,
    PaginationInfo,
    UserProfile
)

logger = logging.getLogger(__name__)


class RecommendationServiceV2:
    """Clean recommendation service with dual database architecture"""
    
    @staticmethod
    async def get_popular_items(request: PopularItemsRequest) -> RecommendationResponse:
        """
        Get popular items based on user demographics
        Uses pre-computed popular_items table from recommendations DB
        """
        start_time = time.time()
        cache_hit = False
        
        try:
            # Build cache key
            cache_key = RecommendationServiceV2._build_popular_cache_key(request)
            
            # Check cache first
            cached_result = db.cache_get(cache_key)
            if cached_result:
                cache_hit = True
                return RecommendationResponse(
                    items=cached_result['items'],
                    pagination=PaginationInfo(**cached_result['pagination']),
                    computation_time_ms=(time.time() - start_time) * 1000,
                    algorithm_used="popular",
                    cache_hit=True
                )
            
            # Get popular items from recommendations DB
            logger.info(f"[DEBUG] Querying popular items for geo_id: {request.user_params.geo_id}")
            popular_items = await RecommendationServiceV2._query_popular_items(request)
            logger.info(f"[DEBUG] Found {len(popular_items)} popular items")
            
            # Apply real-time filters from main DB
            logger.info(f"[DEBUG] Applying filters: {request.filters}")
            filtered_items = await RecommendationServiceV2._apply_filters(
                popular_items, request.filters, request.user_params.geo_id
            )
            logger.info(f"[DEBUG] After filtering: {len(filtered_items)} items")
            
            # Calculate pagination
            total_count = len(filtered_items)
            total_pages = math.ceil(total_count / request.pagination.limit) if total_count > 0 else 0
            
            # Get page items
            start_idx = request.pagination.offset
            end_idx = start_idx + request.pagination.limit
            page_items = filtered_items[start_idx:end_idx]
            
            # Build pagination info
            pagination_info = PaginationInfo(
                page=request.pagination.page,
                limit=request.pagination.limit,
                total_pages=total_pages,
                has_next=request.pagination.page < total_pages,
                has_previous=request.pagination.page > 1
            )
            
            # Cache result
            cache_data = {
                'items': page_items,
                'pagination': pagination_info.dict()
            }
            db.cache_set(cache_key, cache_data, settings.cache_ttl_popular)
            
            computation_time = (time.time() - start_time) * 1000
            
            return RecommendationResponse(
                items=page_items,
                pagination=pagination_info,
                computation_time_ms=computation_time,
                algorithm_used="popular",
                cache_hit=cache_hit
            )
            
        except Exception as e:
            logger.error(f"Error getting popular items: {e}")
            # Return empty result on error
            computation_time = (time.time() - start_time) * 1000
            return RecommendationResponse(
                items=[],
                pagination=PaginationInfo(
                    page=request.pagination.page,
                    limit=request.pagination.limit,
                    total_pages=0,
                    has_next=False,
                    has_previous=False
                ),
                computation_time_ms=computation_time,
                algorithm_used="popular_error",
                cache_hit=False
            )
    
    @staticmethod
    async def get_personalized_recommendations(request: PersonalizedRequest) -> RecommendationResponse:
        """
        Get personalized recommendations based on user's likes
        Excludes items user has already liked
        """
        start_time = time.time()
        cache_hit = False
        
        try:
            # Build cache key
            cache_key = RecommendationServiceV2._build_personalized_cache_key(request)
            
            # Check cache first
            cached_result = db.cache_get(cache_key)
            if cached_result:
                cache_hit = True
                return RecommendationResponse(
                    items=cached_result['items'],
                    pagination=PaginationInfo(**cached_result['pagination']),
                    computation_time_ms=(time.time() - start_time) * 1000,
                    algorithm_used="personalized",
                    cache_hit=True
                )
            
            # Get user's liked items (to exclude)
            user_likes = await RecommendationServiceV2._get_user_likes(request.user_id)
            
            # Get user profile or build basic recommendations
            user_profile = await RecommendationServiceV2._get_user_profile(request.user_id)
            
            if user_profile and user_profile.interaction_count >= 3:
                # Use collaborative filtering for users with enough data
                recommended_items = await RecommendationServiceV2._get_collaborative_recommendations(
                    request.user_id, request.geo_id, user_likes
                )
                algorithm_used = "collaborative"
            elif user_profile and user_profile.interaction_count > 0:
                # Use content-based for users with some data
                recommended_items = await RecommendationServiceV2._get_content_based_recommendations(
                    request.user_id, request.geo_id, user_likes, user_profile
                )
                algorithm_used = "content_based"
            else:
                # Fallback to popular items for new users
                recommended_items = await RecommendationServiceV2._get_fallback_popular_items(
                    request.geo_id, user_likes
                )
                algorithm_used = "popular_fallback"
            
            # Apply real-time filters
            filtered_items = await RecommendationServiceV2._apply_filters(
                recommended_items, request.filters, request.geo_id
            )
            
            # Calculate pagination
            total_count = len(filtered_items)
            total_pages = math.ceil(total_count / request.pagination.limit) if total_count > 0 else 0
            
            # Get page items
            start_idx = request.pagination.offset
            end_idx = start_idx + request.pagination.limit
            page_items = filtered_items[start_idx:end_idx]
            
            # Build pagination info
            pagination_info = PaginationInfo(
                page=request.pagination.page,
                limit=request.pagination.limit,
                total_pages=total_pages,
                has_next=request.pagination.page < total_pages,
                has_previous=request.pagination.page > 1
            )
            
            # Cache result
            cache_data = {
                'items': page_items,
                'pagination': pagination_info.dict()
            }
            db.cache_set(cache_key, cache_data, settings.cache_ttl_personalized)
            
            computation_time = (time.time() - start_time) * 1000
            
            return RecommendationResponse(
                items=page_items,
                pagination=pagination_info,
                computation_time_ms=computation_time,
                algorithm_used=algorithm_used,
                cache_hit=cache_hit
            )
            
        except Exception as e:
            logger.error(f"Error getting personalized recommendations for user {request.user_id}: {e}")
            # Return empty result on error
            computation_time = (time.time() - start_time) * 1000
            return RecommendationResponse(
                items=[],
                pagination=PaginationInfo(
                    page=request.pagination.page,
                    limit=request.pagination.limit,
                    total_pages=0,
                    has_next=False,
                    has_previous=False
                ),
                computation_time_ms=computation_time,
                algorithm_used="personalized_error",
                cache_hit=False
            )
    
    @staticmethod
    def _build_popular_cache_key(request: PopularItemsRequest) -> str:
        """Build cache key for popular items"""
        key_parts = [
            "popular",
            str(request.user_params.geo_id),
            request.user_params.gender or "any",
            request.user_params.age or "any", 
            request.user_params.category or "any",
            str(request.pagination.page),
            str(request.pagination.limit)
        ]
        
        # Add filter parts if present
        if request.filters:
            if request.filters.price_from:
                key_parts.append(f"pf{request.filters.price_from}")
            if request.filters.price_to:
                key_parts.append(f"pt{request.filters.price_to}")
            if request.filters.category:
                key_parts.append(f"cat{request.filters.category}")
        
        return ":".join(key_parts)
    
    @staticmethod
    def _build_personalized_cache_key(request: PersonalizedRequest) -> str:
        """Build cache key for personalized recommendations"""
        key_parts = [
            "personalized",
            str(request.user_id),
            str(request.geo_id),
            str(request.pagination.page),
            str(request.pagination.limit)
        ]
        
        # Add filter parts if present
        if request.filters:
            if request.filters.price_from:
                key_parts.append(f"pf{request.filters.price_from}")
            if request.filters.price_to:
                key_parts.append(f"pt{request.filters.price_to}")
            if request.filters.category:
                key_parts.append(f"cat{request.filters.category}")
        
        return ":".join(key_parts)
    
    @staticmethod
    async def _query_popular_items(request: PopularItemsRequest) -> List[str]:
        """Query popular items from recommendations database"""
        query = """
            SELECT item_id
            FROM popular_items
            WHERE geo_id = $1
              AND ($2::text IS NULL OR gender = $2 OR gender = 'any')
              AND ($3::text IS NULL OR age_group = $3 OR age_group = 'any')
              AND ($4::text IS NULL OR category = $4 OR category = 'any')
            ORDER BY popularity_score DESC
            LIMIT 200
        """
        
        results = await db.execute_recommendations_query(
            query,
            request.user_params.geo_id,
            request.user_params.gender,
            request.user_params.age,
            request.user_params.category
        )
        
        return [row['item_id'] for row in results]
    
    @staticmethod
    async def _get_user_likes(user_id: str) -> List[str]:
        """Get user's liked items from main database"""
        query = """
            SELECT handpicked_present_id
            FROM handpicked_likes
            WHERE user_id = $1
        """
        
        results = await db.execute_main_query(query, user_id)
        return [row['handpicked_present_id'] for row in results]
    
    @staticmethod
    async def _get_user_profile(user_id: str) -> Optional[UserProfile]:
        """Get user profile from recommendations database"""
        query = """
            SELECT user_id, preferred_categories, preferred_platforms, 
                   avg_price, price_range_min, price_range_max,
                   interaction_count, last_interaction_at
            FROM user_profiles
            WHERE user_id = $1
        """
        
        result = await db.execute_recommendations_query_one(query, user_id)
        
        if result:
            return UserProfile(
                user_id=result['user_id'],
                preferred_categories=result['preferred_categories'] or {},
                preferred_platforms=result['preferred_platforms'] or {},
                avg_price=result['avg_price'],
                price_range_min=result['price_range_min'],
                price_range_max=result['price_range_max'],
                interaction_count=result['interaction_count'],
                last_interaction_at=str(result['last_interaction_at']) if result['last_interaction_at'] else None
            )
        
        return None
    
    @staticmethod
    async def _get_collaborative_recommendations(
        user_id: str, 
        geo_id: int, 
        user_likes: List[str]
    ) -> List[str]:
        """Get collaborative filtering recommendations"""
        # Get similar users from recommendations DB
        similar_users_query = """
            SELECT similar_user_id
            FROM user_similarities
            WHERE user_id = $1
            ORDER BY similarity_score DESC
            LIMIT $2
        """
        
        similar_users = await db.execute_recommendations_query(
            similar_users_query, user_id, settings.max_similar_users
        )
        
        if not similar_users:
            return []
        
        similar_user_ids = [row['similar_user_id'] for row in similar_users]
        
        # Get items liked by similar users from main DB
        recommendations_query = """
            SELECT 
                hl.handpicked_present_id as item_id,
                COUNT(*) as like_count
            FROM handpicked_likes hl
            JOIN handpicked_presents hp ON hl.handpicked_present_id = hp.id
            WHERE hl.user_id = ANY($1::int[])
              AND hp.geo_id = $2
              AND hp.status = 'in_stock'
              AND hp.user_id IS NULL
              AND ($3::int[] IS NULL OR hl.handpicked_present_id != ALL($3::int[]))
            GROUP BY hl.handpicked_present_id
            ORDER BY like_count DESC
            LIMIT 100
        """
        
        results = await db.execute_main_query(
            recommendations_query,
            similar_user_ids,
            geo_id,
            user_likes if user_likes else None
        )
        
        return [row['item_id'] for row in results]
    
    @staticmethod
    async def _get_content_based_recommendations(
        user_id: str,
        geo_id: int, 
        user_likes: List[str],
        user_profile: UserProfile
    ) -> List[str]:
        """Get content-based recommendations using user profile"""
        # Simple content-based: get popular items in user's preferred categories
        preferred_categories = list(user_profile.preferred_categories.keys())[:3]  # Top 3 categories
        
        if not preferred_categories:
            return await RecommendationServiceV2._get_fallback_popular_items(geo_id, user_likes)
        
        query = """
            SELECT item_id
            FROM popular_items
            WHERE geo_id = $1
              AND category = ANY($2::text[])
            ORDER BY popularity_score DESC
            LIMIT 100
        """
        
        results = await db.execute_recommendations_query(
            query, geo_id, preferred_categories
        )
        
        return [row['item_id'] for row in results]
    
    @staticmethod
    async def _get_fallback_popular_items(geo_id: int, user_likes: List[str]) -> List[str]:
        """Get fallback popular items"""
        query = """
            SELECT item_id
            FROM popular_items
            WHERE geo_id = $1
              AND gender = 'any'
              AND age_group = 'any'
              AND category = 'any'
            ORDER BY popularity_score DESC
            LIMIT 100
        """
        
        results = await db.execute_recommendations_query(query, geo_id)
        return [row['item_id'] for row in results]
    
    @staticmethod
    async def _apply_filters(
        item_ids: List[str], 
        filters: Optional[Any], 
        geo_id: int
    ) -> List[str]:
        """Apply real-time filters to item list using main database"""
        if not item_ids:
            return []
        
        if not filters:
            return item_ids
        
        # Build filter conditions - cast UUIDs properly
        filter_conditions = ["hp.id::text = ANY($1::varchar[])", "hp.geo_id = $2", "hp.status = 'in_stock'"]
        filter_params = [item_ids, geo_id]
        param_count = 2
        
        # Price filters
        if filters.price_from is not None:
            param_count += 1
            filter_conditions.append(f"hp.price >= ${param_count}")
            filter_params.append(filters.price_from)
        
        if filters.price_to is not None:
            param_count += 1
            filter_conditions.append(f"hp.price <= ${param_count}")
            filter_params.append(filters.price_to)
        
        # Category filters
        category_filters = ['category', 'suitable_for', 'acquaintance_level']
        for cat_filter in category_filters:
            value = getattr(filters, cat_filter, None)
            if value:
                param_count += 1
                filter_conditions.append(f"hp.categories ->> '{cat_filter}' = ${param_count}")
                filter_params.append(value)
        
        # Platform filter
        if filters.platform:
            param_count += 1
            filter_conditions.append(f"hp.platform = ${param_count}")
            filter_params.append(filters.platform)
        
        # Execute filter query on main DB
        filter_query = f"""
            SELECT id
            FROM handpicked_presents hp
            WHERE {' AND '.join(filter_conditions)}
            ORDER BY array_position($1::varchar[], hp.id::text)
        """
        
        try:
            filtered_results = await db.execute_main_query(filter_query, *filter_params)
            return [row['id'] for row in filtered_results]
        except Exception as e:
            logger.error(f"Error applying filters: {e}")
            return item_ids  # Return unfiltered if filter fails