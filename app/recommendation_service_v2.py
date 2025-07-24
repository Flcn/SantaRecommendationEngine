"""
Clean recommendation service with two core APIs:
1. Popular items based on user demographics  
2. Personalized recommendations based on user likes
"""

import time
import logging
import math
import json
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
            
            logger.info(f"[DEBUG] Pagination: page={request.pagination.page}, limit={request.pagination.limit}, offset={start_idx}")
            logger.info(f"[DEBUG] Slicing: filtered_items[{start_idx}:{end_idx}] = {len(page_items)} items")
            if page_items:
                logger.info(f"[DEBUG] First few items: {page_items[:3]}")
            
            # Build pagination info
            pagination_info = PaginationInfo(
                page=request.pagination.page,
                limit=request.pagination.limit,
                total_pages=total_pages,
                total_count=total_count,
                has_next=request.pagination.page < total_pages,
                has_previous=request.pagination.page > 1
            )
            
            # Cache result
            cache_data = {
                'items': page_items,
                'pagination': pagination_info.model_dump()
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
            computation_time = (time.time() - start_time) * 1000
            logger.error(f"Popular items request failed in {computation_time:.2f}ms")
            raise
    
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
                
                # Fallback to content-based if collaborative returns 0 items
                if not recommended_items:
                    logger.info(f"Collaborative filtering returned 0 items for user {request.user_id}, falling back to content-based")
                    recommended_items = await RecommendationServiceV2._get_content_based_recommendations(
                        request.user_id, request.geo_id, user_likes, user_profile
                    )
                    algorithm_used = "collaborative_fallback_content"
            elif user_profile and user_profile.interaction_count > 0:
                # Use content-based for users with some data
                recommended_items = await RecommendationServiceV2._get_content_based_recommendations(
                    request.user_id, request.geo_id, user_likes, user_profile
                )
                algorithm_used = "content_based"
            else:
                # Fallback to popular items for new users
                recommended_items = await RecommendationServiceV2._get_fallback_popular_items(
                    request.geo_id, user_likes, request.user_id
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
                total_count=total_count,
                has_next=request.pagination.page < total_pages,
                has_previous=request.pagination.page > 1
            )
            
            # Cache result
            cache_data = {
                'items': page_items,
                'pagination': pagination_info.model_dump()
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
            computation_time = (time.time() - start_time) * 1000
            logger.error(f"Personalized recommendations request failed in {computation_time:.2f}ms")
            raise
    
    @staticmethod
    def _build_popular_cache_key(request: PopularItemsRequest) -> str:
        """Build cache key for popular items"""
        key_parts = [
            settings.cache_key_prefix,
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
                key_parts.append(f"pf{int(request.filters.price_from)}")
            if request.filters.price_to:
                key_parts.append(f"pt{int(request.filters.price_to)}")
            if request.filters.category:
                key_parts.append(f"cat{request.filters.category}")
        
        return ":".join(key_parts)
    
    @staticmethod
    def _build_personalized_cache_key(request: PersonalizedRequest) -> str:
        """Build cache key for personalized recommendations"""
        key_parts = [
            settings.cache_key_prefix,
            "personalized",
            str(request.user_id),
            str(request.geo_id),
            str(request.pagination.page),
            str(request.pagination.limit)
        ]
        
        # Add filter parts if present
        if request.filters:
            if request.filters.price_from:
                key_parts.append(f"pf{int(request.filters.price_from)}")
            if request.filters.price_to:
                key_parts.append(f"pt{int(request.filters.price_to)}")
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
            WHERE user_id::text = $1
        """
        
        results = await db.execute_main_query(query, user_id)
        return [str(row['handpicked_present_id']) for row in results]
    
    @staticmethod
    async def _get_user_profile(user_id: str) -> Optional[UserProfile]:
        """Get user profile from recommendations database (Option 3: with buying patterns)"""
        query = """
            SELECT user_id, preferred_categories, preferred_platforms, 
                   avg_price, price_range_min, price_range_max,
                   buying_patterns_target_ages, buying_patterns_relationships, 
                   buying_patterns_gender_targets,
                   interaction_count, last_interaction_at
            FROM user_profiles
            WHERE user_id = $1
        """
        
        result = await db.execute_recommendations_query_one(query, user_id)
        
        if result:
            # Parse JSON strings to dictionaries
            preferred_categories = result['preferred_categories'] or '{}'
            preferred_platforms = result['preferred_platforms'] or '{}'
            buying_patterns_target_ages = result['buying_patterns_target_ages'] or '{}'
            buying_patterns_relationships = result['buying_patterns_relationships'] or '{}'
            buying_patterns_gender_targets = result['buying_patterns_gender_targets'] or '{}'
            
            if isinstance(preferred_categories, str):
                preferred_categories = json.loads(preferred_categories)
            if isinstance(preferred_platforms, str):
                preferred_platforms = json.loads(preferred_platforms)
            if isinstance(buying_patterns_target_ages, str):
                buying_patterns_target_ages = json.loads(buying_patterns_target_ages)
            if isinstance(buying_patterns_relationships, str):
                buying_patterns_relationships = json.loads(buying_patterns_relationships)
            if isinstance(buying_patterns_gender_targets, str):
                buying_patterns_gender_targets = json.loads(buying_patterns_gender_targets)
            
            return UserProfile(
                user_id=result['user_id'],
                preferred_categories=preferred_categories,
                preferred_platforms=preferred_platforms,
                avg_price=float(result['avg_price']) if result['avg_price'] is not None else None,
                price_range_min=float(result['price_range_min']) if result['price_range_min'] is not None else None,
                price_range_max=float(result['price_range_max']) if result['price_range_max'] is not None else None,
                buying_patterns_target_ages=buying_patterns_target_ages,
                buying_patterns_relationships=buying_patterns_relationships,
                buying_patterns_gender_targets=buying_patterns_gender_targets,
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
        """Get collaborative filtering recommendations using item-based approach"""
        return await RecommendationServiceV2._get_collaborative_recommendations_via_items(
            user_id, geo_id, user_likes
        )
    
    @staticmethod
    async def _get_collaborative_recommendations_via_items(
        user_id: str, 
        geo_id: int, 
        user_likes: List[str]
    ) -> List[str]:
        """Get collaborative recommendations using item-based similarity"""
        
        if not user_likes:
            logger.info(f"[COLLABORATIVE] User {user_id} has no likes, returning empty")
            return []
        
        logger.info(f"[COLLABORATIVE] User {user_id} has {len(user_likes)} likes: {user_likes[:5]}...")
        
        # Get items similar to what user already likes
        similar_items_query = """
            SELECT 
                CASE 
                    WHEN item_a = ANY($1::text[]) THEN item_b
                    WHEN item_b = ANY($1::text[]) THEN item_a
                END as similar_item,
                similarity_score
            FROM item_similarities
            WHERE (item_a = ANY($1::text[]) OR item_b = ANY($1::text[]))
              AND similarity_score >= 0.1  -- Minimum similarity threshold (lowered from 0.2)
            ORDER BY similarity_score DESC
            LIMIT 200
        """
        
        similar_items = await db.execute_recommendations_query(
            similar_items_query, user_likes
        )
        
        logger.info(f"[COLLABORATIVE] Found {len(similar_items)} similar items from database")
        
        if not similar_items:
            logger.info(f"[COLLABORATIVE] No similar items found for user {user_id}, returning empty")
            return []
        
        # Weight similar items by their similarity scores
        item_scores = {}
        for item in similar_items:
            item_id = item['similar_item']
            if item_id not in item_scores:
                item_scores[item_id] = 0
            item_scores[item_id] += item['similarity_score']
        
        # Get top weighted items
        sorted_items = sorted(item_scores.items(), key=lambda x: x[1], reverse=True)
        item_ids = [item[0] for item in sorted_items[:100]]
        
        logger.info(f"[COLLABORATIVE] After scoring: {len(item_ids)} candidate items")
        
        # Filter by geo, stock, etc.
        recommendations_query = """
            SELECT hp.id::text as item_id,
                   COUNT(hl.user_id) as popularity_boost
            FROM handpicked_presents hp
            LEFT JOIN handpicked_likes hl ON hp.id = hl.handpicked_present_id
            WHERE hp.id::text = ANY($1::text[])
              AND hp.geo_id = $2
              AND hp.status = 'in_stock'
              AND hp.user_id IS NULL  -- Only public presents
              AND ($3::text[] IS NULL OR hp.id::text != ALL($3::text[]))
            GROUP BY hp.id
            ORDER BY popularity_boost DESC
            LIMIT 100
        """
        
        results = await db.execute_main_query(
            recommendations_query,
            item_ids,
            geo_id,
            user_likes if user_likes else None
        )
        
        collaborative_items = [row['item_id'] for row in results]
        logger.info(f"[COLLABORATIVE] Final filtered results: {len(collaborative_items)} items for user {user_id}")
        
        # If we don't have enough items, fill with popular items
        if len(collaborative_items) < 100:  # Target up to 100 items for pagination
            logger.info(f"[COLLABORATIVE] Not enough similar items ({len(collaborative_items)}), adding popular items to fill")
            
            # Get popular items to fill the gap
            excluded_items = set(collaborative_items + user_likes)
            popular_fill_query = """
                SELECT hp.id::text as item_id
                FROM handpicked_presents hp
                LEFT JOIN (
                    SELECT handpicked_present_id, COUNT(*) as like_count
                    FROM handpicked_likes
                    GROUP BY handpicked_present_id
                ) hl ON hp.id = hl.handpicked_present_id
                WHERE hp.geo_id = $1
                  AND hp.status = 'in_stock'
                  AND hp.user_id IS NULL  -- Only public presents
                  AND hp.id::text != ALL($2::text[])  -- Exclude already selected and liked items
                ORDER BY COALESCE(hl.like_count, 0) DESC
                LIMIT $3
            """
            
            items_needed = 100 - len(collaborative_items)
            popular_results = await db.execute_main_query(
                popular_fill_query,
                geo_id,
                list(excluded_items),
                items_needed
            )
            
            popular_items = [row['item_id'] for row in popular_results]
            logger.info(f"[COLLABORATIVE] Added {len(popular_items)} popular items as filler")
            
            # Combine results: collaborative items first, then popular items
            return collaborative_items + popular_items
        
        return collaborative_items
    
    @staticmethod
    async def _get_collaborative_recommendations_legacy(
        user_id: str, 
        geo_id: int, 
        user_likes: List[str]
    ) -> List[str]:
        """Get collaborative filtering recommendations (legacy user-based approach)"""
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
                hl.handpicked_present_id::text as item_id,
                COUNT(*) as like_count
            FROM handpicked_likes hl
            JOIN handpicked_presents hp ON hl.handpicked_present_id = hp.id
            WHERE hl.user_id::text = ANY($1::text[])
              AND hp.geo_id = $2
              AND hp.status = 'in_stock'
              AND hp.user_id IS NULL
              AND ($3::text[] IS NULL OR hl.handpicked_present_id::text != ALL($3::text[]))
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
        """
        Get content-based recommendations using Option 3 Hybrid Approach
        Combines category preferences + buying patterns for better targeting
        """
        from app.algorithms.content_based import ContentBasedFilter
        
        # Get candidate items from main database - pre-filter for stock status
        candidate_items_query = """
            SELECT 
                id::text as item_id,
                categories,
                price,
                platform,
                created_at
            FROM handpicked_presents
            WHERE geo_id = $1
              AND status = 'in_stock'
              AND user_id IS NULL
              AND ($2::text[] IS NULL OR id::text != ALL($2::text[]))
            ORDER BY created_at DESC
            LIMIT 500
        """
        
        candidate_items = await db.execute_main_query(
            candidate_items_query,
            geo_id,
            user_likes if user_likes else None
        )
        
        if not candidate_items:
            return await RecommendationServiceV2._get_fallback_popular_items(geo_id, user_likes, user_id)
        
        # Convert UserProfile to dict format for ContentBasedFilter
        user_profile_dict = {
            'category_preferences': user_profile.preferred_categories,
            'platform_preferences': user_profile.preferred_platforms,
            'avg_price': user_profile.avg_price,
            'buying_patterns_target_ages': user_profile.buying_patterns_target_ages,
            'buying_patterns_relationships': user_profile.buying_patterns_relationships,
            'buying_patterns_gender_targets': user_profile.buying_patterns_gender_targets
        }
        
        # Score each item using Option 3 hybrid algorithm
        scored_items = []
        for item in candidate_items:
            score = ContentBasedFilter.calculate_item_score(dict(item), user_profile_dict)
            if score > 0.05:  # Lowered threshold to include more items
                scored_items.append((item['item_id'], score))
        
        # Sort by score and return top items
        scored_items.sort(key=lambda x: x[1], reverse=True)
        return [item_id for item_id, score in scored_items[:100]]
    
    @staticmethod
    async def _get_fallback_popular_items(geo_id: int, user_likes: List[str], user_id: str = None) -> List[str]:
        """
        Get fallback popular items with demographic targeting if available
        
        Tries demographic-specific popular items first, then falls back to generic.
        Demographics come from cached user sync data from Rails.
        """
        # Try to get user demographics from cache if user_id provided
        user_demographics = None
        if user_id:
            try:
                cache_key = f"user_demographics:{user_id}"
                user_demographics = db.cache_get(cache_key)
                if user_demographics:
                    logger.info(f"Found cached demographics for user {user_id}: {user_demographics}")
            except Exception as e:
                logger.warning(f"Error getting user demographics from cache: {e}")
        
        # Build fallback chain: specific demographics -> gender only -> age only -> generic
        query_variants = []
        
        if user_demographics:
            gender = user_demographics.get('gender')
            age_group = user_demographics.get('age_group')
            
            # Try exact demographic match first
            if gender and age_group:
                query_variants.append({
                    'gender': gender,
                    'age_group': age_group,
                    'category': 'any',
                    'description': f"exact demographics ({gender}, {age_group})"
                })
            
            # Try gender only
            if gender:
                query_variants.append({
                    'gender': gender,
                    'age_group': 'any', 
                    'category': 'any',
                    'description': f"gender only ({gender})"
                })
            
            # Try age only
            if age_group:
                query_variants.append({
                    'gender': 'any',
                    'age_group': age_group,
                    'category': 'any', 
                    'description': f"age only ({age_group})"
                })
        
        # Always add generic fallback
        query_variants.append({
            'gender': 'any',
            'age_group': 'any',
            'category': 'any',
            'description': 'generic fallback'
        })
        
        # Try each variant until we get results
        for variant in query_variants:
            try:
                # Build dynamic query based on what's available
                where_conditions = ["geo_id = $1"]
                params = [geo_id]
                param_count = 1
                
                # Add gender condition
                param_count += 1
                where_conditions.append(f"gender = ${param_count}")
                params.append(variant['gender'])
                
                # Add age_group condition only if not 'any' (since 'any' doesn't exist in data)
                if variant['age_group'] != 'any':
                    param_count += 1
                    where_conditions.append(f"age_group = ${param_count}")
                    params.append(variant['age_group'])
                
                # Skip category filtering for now (let all categories through)
                
                # Get popular items but filter for in_stock status via main DB
                query = f"""
                    SELECT pi.item_id
                    FROM popular_items pi
                    WHERE {' AND '.join(where_conditions)}
                    ORDER BY pi.popularity_score DESC
                    LIMIT 100
                """
                
                popular_results = await db.execute_recommendations_query(query, *params)
                popular_items = [row['item_id'] for row in popular_results]
                
                if not popular_items:
                    continue
                
                # Filter for in_stock items using main database
                stock_query = """
                    SELECT id::text as item_id
                    FROM handpicked_presents
                    WHERE id::text = ANY($1::text[])
                      AND status = 'in_stock'
                      AND user_id IS NULL
                    ORDER BY array_position($1::text[], id::text)
                """
                
                results = await db.execute_main_query(stock_query, popular_items)
                
                items = [row['item_id'] for row in results]
                if items:
                    logger.info(f"Found {len(items)} popular items using {variant['description']}")
                    return items
                else:
                    logger.info(f"No items found for {variant['description']}, trying next fallback")
                    
            except Exception as e:
                logger.warning(f"Error querying popular items with {variant['description']}: {e}")
                continue
        
        # If we get here, something is wrong - return empty list
        logger.warning(f"No popular items found for geo_id {geo_id} with any fallback method")
        return []
    
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
        # Note: stock status already filtered in candidate selection
        filter_conditions = ["hp.id::text = ANY($1::text[])", "hp.geo_id = $2"]
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
            ORDER BY array_position($1::text[], hp.id::text)
        """
        
        try:
            filtered_results = await db.execute_main_query(filter_query, *filter_params)
            return [str(row['id']) for row in filtered_results]  # Convert UUID to string
        except Exception as e:
            logger.error(f"Error applying filters: {e}")
            return item_ids  # Return unfiltered if filter fails