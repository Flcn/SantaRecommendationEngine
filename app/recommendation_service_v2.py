"""
Clean recommendation service with two core APIs:
1. Popular items based on user demographics  
2. Personalized recommendations based on user likes
"""

import time
import logging
import math
import json
import hashlib
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

            items_needed = request.pagination.offset + request.pagination.limit

            # TIER 0: Wish-based recommendations (highest priority)
            if request.wish_text:
                logger.info(f"User {request.user_id} has wish_text, using wish-based tier")
                recommended_items = await RecommendationServiceV2._get_wish_based_recommendations(
                    user_id=request.user_id,
                    geo_id=request.geo_id,
                    wish_text=request.wish_text,
                    unwish_text=request.unwish_text,
                    locale=request.locale,
                    user_likes=user_likes,
                    items_needed=items_needed,
                    filters=request.filters
                )
                algorithm_used = "wish_based"

                # Supplement with fallback if wish-based returns insufficient results
                if len(recommended_items) < items_needed:
                    logger.info(f"[WISH] Only {len(recommended_items)}/{items_needed} items, supplementing with fallback")
                    user_profile = await RecommendationServiceV2._get_user_profile(request.user_id)
                    wish_item_set = set(recommended_items)

                    if user_profile and user_profile.interaction_count >= 3:
                        fallback_items = await RecommendationServiceV2._get_collaborative_recommendations(
                            request.user_id, request.geo_id, user_likes, items_needed,
                            filters=request.filters
                        )
                        algorithm_used = "wish_based_with_collaborative"
                    elif user_profile and user_profile.interaction_count > 0:
                        fallback_items = await RecommendationServiceV2._get_content_based_recommendations(
                            request.user_id, request.geo_id, user_likes, user_profile,
                            filters=request.filters
                        )
                        algorithm_used = "wish_based_with_content"
                    else:
                        fallback_items = await RecommendationServiceV2._get_fallback_popular_items(
                            request.geo_id, user_likes, request.user_id,
                            filters=request.filters
                        )
                        algorithm_used = "wish_based_with_popular"

                    # Append fallback items that aren't already in wish results
                    for item_id in fallback_items:
                        if item_id not in wish_item_set:
                            recommended_items.append(item_id)
                            wish_item_set.add(item_id)

            else:
                # Get user profile for existing algorithm tiers
                user_profile = await RecommendationServiceV2._get_user_profile(request.user_id)

                if user_profile and user_profile.interaction_count >= 3:
                    # Use collaborative filtering for users with enough data
                    recommended_items = await RecommendationServiceV2._get_collaborative_recommendations(
                        request.user_id, request.geo_id, user_likes, items_needed,
                        filters=request.filters
                    )
                    algorithm_used = "collaborative"

                    # Fallback to content-based if collaborative returns 0 items
                    if not recommended_items:
                        logger.info(f"Collaborative filtering returned 0 items for user {request.user_id}, falling back to content-based")
                        recommended_items = await RecommendationServiceV2._get_content_based_recommendations(
                            request.user_id, request.geo_id, user_likes, user_profile,
                            filters=request.filters
                        )
                        algorithm_used = "collaborative_fallback_content"
                elif user_profile and user_profile.interaction_count > 0:
                    # Use content-based for users with some data
                    recommended_items = await RecommendationServiceV2._get_content_based_recommendations(
                        request.user_id, request.geo_id, user_likes, user_profile,
                        filters=request.filters
                    )
                    algorithm_used = "content_based"
                else:
                    # Fallback to popular items for new users
                    recommended_items = await RecommendationServiceV2._get_fallback_popular_items(
                        request.geo_id, user_likes, request.user_id,
                        filters=request.filters
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
            if request.filters.gender:
                key_parts.append(f"g{request.filters.gender}")
            if request.filters.age:
                key_parts.append(f"age{request.filters.age}")

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
            if request.filters.gender:
                key_parts.append(f"g{request.filters.gender}")
            if request.filters.age:
                key_parts.append(f"age{request.filters.age}")

        # Add wish text hash to cache key
        if request.wish_text:
            wish_hash = hashlib.md5(request.wish_text.encode()).hexdigest()[:8]
            key_parts.append(f"wish{wish_hash}")
        if request.unwish_text:
            unwish_hash = hashlib.md5(request.unwish_text.encode()).hexdigest()[:8]
            key_parts.append(f"unwish{unwish_hash}")

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
        user_likes: List[str],
        items_needed: int = 100,
        filters: Optional[Any] = None
    ) -> List[str]:
        """Get collaborative filtering recommendations using item-based approach"""
        return await RecommendationServiceV2._get_collaborative_recommendations_via_items(
            user_id, geo_id, user_likes, items_needed, filters=filters
        )
    
    @staticmethod
    async def _get_collaborative_recommendations_via_items(
        user_id: str,
        geo_id: int,
        user_likes: List[str],
        items_needed: int = 100,
        filters: Optional[Any] = None
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
              AND similarity_score >= 0.1
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

        # Get top weighted items - over-fetch to account for filter shrinkage
        sorted_items = sorted(item_scores.items(), key=lambda x: x[1], reverse=True)
        fetch_limit = max(100, items_needed * 3)
        item_ids = [item[0] for item in sorted_items[:fetch_limit]]

        logger.info(f"[COLLABORATIVE] After scoring: {len(item_ids)} candidate items")

        # Filter by geo, stock, user filters, and exclude wishlist
        base_conditions = [
            "hp.id::text = ANY($1::text[])",
            "hp.geo_id = $2",
            "hp.status = 'in_stock'",
            "hp.user_id IS NULL",
            "($3::text[] IS NULL OR hp.id::text != ALL($3::text[]))",
            # Exclude items already in user's wishlist
            f"hp.id NOT IN (SELECT handpicked_present_id FROM handpicked_likes WHERE user_id::text = $4)"
        ]
        base_params = [item_ids, geo_id, user_likes if user_likes else None, user_id]
        param_count = 4

        # Push user filters into the query
        filter_conditions, filter_params = RecommendationServiceV2._build_filter_conditions(
            filters, "hp", param_count
        )
        all_conditions = base_conditions + filter_conditions
        all_params = base_params + filter_params

        recommendations_query = f"""
            SELECT hp.id::text as item_id,
                   COUNT(hl.user_id) as popularity_boost
            FROM handpicked_presents hp
            LEFT JOIN handpicked_likes hl ON hp.id = hl.handpicked_present_id
            WHERE {' AND '.join(all_conditions)}
            GROUP BY hp.id
            ORDER BY popularity_boost DESC
            LIMIT {fetch_limit}
        """

        results = await db.execute_main_query(
            recommendations_query, *all_params
        )

        collaborative_items = [row['item_id'] for row in results]
        logger.info(f"[COLLABORATIVE] Final filtered results: {len(collaborative_items)} items for user {user_id}")

        # If we don't have enough items, fill with popular items
        if len(collaborative_items) < items_needed:
            logger.info(f"[COLLABORATIVE] Not enough similar items ({len(collaborative_items)}/{items_needed}), adding popular items to fill")

            # Get popular items to fill the gap
            excluded_items = list(set(collaborative_items + user_likes))

            # Build popular fill query with same filters
            fill_conditions = [
                "hp.geo_id = $1",
                "hp.status = 'in_stock'",
                "hp.user_id IS NULL",
                "($2::text[] IS NULL OR hp.id::text != ALL($2::text[]))",
                f"hp.id NOT IN (SELECT handpicked_present_id FROM handpicked_likes WHERE user_id::text = $3)"
            ]
            fill_params = [geo_id, excluded_items if excluded_items else None, user_id]
            fill_param_count = 3

            fill_filter_conditions, fill_filter_params = RecommendationServiceV2._build_filter_conditions(
                filters, "hp", fill_param_count
            )
            fill_conditions.extend(fill_filter_conditions)
            fill_params.extend(fill_filter_params)

            items_to_add = items_needed - len(collaborative_items)
            popular_fill_query = f"""
                SELECT hp.id::text as item_id
                FROM handpicked_presents hp
                LEFT JOIN (
                    SELECT handpicked_present_id, COUNT(*) as like_count
                    FROM handpicked_likes
                    GROUP BY handpicked_present_id
                ) hl ON hp.id = hl.handpicked_present_id
                WHERE {' AND '.join(fill_conditions)}
                ORDER BY COALESCE(hl.like_count, 0) DESC
                LIMIT {items_to_add}
            """

            popular_results = await db.execute_main_query(
                popular_fill_query, *fill_params
            )

            popular_items = [row['item_id'] for row in popular_results]
            logger.info(f"[COLLABORATIVE] Added {len(popular_items)} popular items as filler")

            all_items = collaborative_items + popular_items
            return list(dict.fromkeys(all_items))

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
        user_profile: UserProfile,
        filters: Optional[Any] = None
    ) -> List[str]:
        """
        Get content-based recommendations using Option 3 Hybrid Approach
        Combines category preferences + buying patterns for better targeting
        """
        from app.algorithms.content_based import ContentBasedFilter

        # Build candidate query with pushed-down filters + wishlist exclusion
        base_conditions = [
            "geo_id = $1",
            "status = 'in_stock'",
            "user_id IS NULL",
            "($2::text[] IS NULL OR id::text != ALL($2::text[]))",
            f"id NOT IN (SELECT handpicked_present_id FROM handpicked_likes WHERE user_id::text = $3)"
        ]
        base_params = [geo_id, user_likes if user_likes else None, user_id]
        param_count = 3

        filter_conditions, filter_params = RecommendationServiceV2._build_filter_conditions(
            filters, "handpicked_presents", param_count
        )
        all_conditions = base_conditions + filter_conditions
        all_params = base_params + filter_params

        candidate_items_query = f"""
            SELECT
                id::text as item_id,
                categories,
                price,
                platform,
                created_at
            FROM handpicked_presents
            WHERE {' AND '.join(all_conditions)}
            ORDER BY created_at DESC
            LIMIT 500
        """

        candidate_items = await db.execute_main_query(
            candidate_items_query, *all_params
        )

        if not candidate_items:
            return await RecommendationServiceV2._get_fallback_popular_items(
                geo_id, user_likes, user_id, filters=filters
            )

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
            if score > 0.05:
                scored_items.append((item['item_id'], score))

        # Sort by score and return top items
        scored_items.sort(key=lambda x: x[1], reverse=True)
        return [item_id for item_id, score in scored_items[:100]]
    
    @staticmethod
    async def _get_fallback_popular_items(
        geo_id: int,
        user_likes: List[str],
        user_id: str = None,
        filters: Optional[Any] = None
    ) -> List[str]:
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

            if gender and age_group:
                query_variants.append({
                    'gender': gender,
                    'age_group': age_group,
                    'category': 'any',
                    'description': f"exact demographics ({gender}, {age_group})"
                })

            if gender:
                query_variants.append({
                    'gender': gender,
                    'age_group': 'any',
                    'category': 'any',
                    'description': f"gender only ({gender})"
                })

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
                # Build dynamic query for popular_items table
                where_conditions = ["geo_id = $1"]
                params = [geo_id]
                param_count = 1

                param_count += 1
                where_conditions.append(f"gender = ${param_count}")
                params.append(variant['gender'])

                if variant['age_group'] != 'any':
                    param_count += 1
                    where_conditions.append(f"age_group = ${param_count}")
                    params.append(variant['age_group'])

                # Over-fetch from popular_items to account for filter shrinkage
                query = f"""
                    SELECT pi.item_id
                    FROM popular_items pi
                    WHERE {' AND '.join(where_conditions)}
                    ORDER BY pi.popularity_score DESC
                    LIMIT 200
                """

                popular_results = await db.execute_recommendations_query(query, *params)
                popular_items = [row['item_id'] for row in popular_results]

                if not popular_items:
                    continue

                # Stock-check + push-down user filters + wishlist exclusion via main DB
                stock_conditions = [
                    "hp.id::text = ANY($1::text[])",
                    "hp.status = 'in_stock'",
                    "hp.user_id IS NULL"
                ]
                stock_params = [popular_items]
                stock_param_count = 1

                # Exclude items already in user's wishlist
                if user_id:
                    stock_param_count += 1
                    stock_conditions.append(
                        f"hp.id NOT IN (SELECT handpicked_present_id FROM handpicked_likes WHERE user_id::text = ${stock_param_count})"
                    )
                    stock_params.append(user_id)

                # Push user filters into stock-check query
                filter_conditions, filter_params = RecommendationServiceV2._build_filter_conditions(
                    filters, "hp", stock_param_count
                )
                stock_conditions.extend(filter_conditions)
                stock_params.extend(filter_params)

                stock_query = f"""
                    SELECT hp.id::text as item_id
                    FROM handpicked_presents hp
                    WHERE {' AND '.join(stock_conditions)}
                    ORDER BY array_position($1::text[], hp.id::text)
                """

                results = await db.execute_main_query(stock_query, *stock_params)

                items = [row['item_id'] for row in results]
                if items:
                    logger.info(f"Found {len(items)} popular items using {variant['description']}")
                    return items
                else:
                    logger.info(f"No items found for {variant['description']}, trying next fallback")

            except Exception as e:
                logger.warning(f"Error querying popular items with {variant['description']}: {e}")
                continue

        logger.warning(f"No popular items found for geo_id {geo_id} with any fallback method")
        return []
    
    @staticmethod
    def _build_filter_conditions(
        filters: Optional[Any],
        table_alias: str = "hp",
        param_offset: int = 0
    ) -> Tuple[List[str], List]:
        """
        Build SQL WHERE clauses from user filters for push-down into candidate queries.

        Returns (conditions, params) where conditions are SQL strings with $N placeholders
        and params are the corresponding values. param_offset is the number of existing
        parameters in the query (so new params start at $param_offset+1).
        """
        conditions = []
        params = []
        param_count = param_offset

        if not filters:
            return conditions, params

        if filters.price_from is not None:
            param_count += 1
            conditions.append(f"{table_alias}.price >= ${param_count}")
            params.append(filters.price_from)

        if filters.price_to is not None:
            param_count += 1
            conditions.append(f"{table_alias}.price <= ${param_count}")
            params.append(filters.price_to)

        if filters.category:
            param_count += 1
            conditions.append(f"{table_alias}.categories ->> 'category' = ${param_count}")
            params.append(filters.category)

        if filters.gender:
            param_count += 1
            conditions.append(f"({table_alias}.categories ->> 'gender' = ${param_count} OR {table_alias}.categories ->> 'gender' = 'any')")
            params.append(filters.gender)

        if filters.age:
            param_count += 1
            conditions.append(f"{table_alias}.categories ->> 'age' ILIKE ${param_count}")
            params.append(f"%{filters.age}%")

        # Category-type filters
        for cat_filter in ['suitable_for', 'acquaintance_level']:
            value = getattr(filters, cat_filter, None)
            if value:
                param_count += 1
                conditions.append(f"{table_alias}.categories ->> '{cat_filter}' = ${param_count}")
                params.append(value)

        if filters.platform:
            param_count += 1
            conditions.append(f"{table_alias}.platform = ${param_count}")
            params.append(filters.platform)

        return conditions, params

    @staticmethod
    async def _apply_filters(
        item_ids: List[str],
        filters: Optional[Any],
        geo_id: int
    ) -> List[str]:
        """Apply real-time filters to item list using main database (safety net)"""
        if not item_ids:
            return []

        if not filters:
            return item_ids

        # Build filter conditions - cast UUIDs properly
        # Note: stock status already filtered in candidate selection
        filter_conditions = ["hp.id::text = ANY($1::text[])", "hp.geo_id = $2"]
        filter_params = [item_ids, geo_id]
        param_count = 2

        # Use shared filter builder for remaining conditions
        extra_conditions, extra_params = RecommendationServiceV2._build_filter_conditions(
            filters, "hp", param_count
        )
        filter_conditions.extend(extra_conditions)
        filter_params.extend(extra_params)

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

    @staticmethod
    def _get_locale_search_config(locale: Optional[str]) -> Tuple[str, str]:
        """Map user locale to PostgreSQL text search config and tsvector column"""
        locale_map = {
            'ru': ('russian', 'searchable_ru'),
            'en': ('english', 'searchable_en'),
            'es': ('spanish', 'searchable_es'),
        }
        if locale and locale in locale_map:
            return locale_map[locale]
        return ('english', 'searchable_en')

    @staticmethod
    def _build_wish_tsquery(wish_text: str) -> Optional[str]:
        """
        Convert comma-separated wish keywords into a PostgreSQL tsquery string.
        "Kindle, flowers, iPhone" → "Kindle | flowers | iPhone"
        Each term uses & for multi-word phrases, combined with | across terms.
        """
        terms = [t.strip() for t in wish_text.split(',') if t.strip()]
        if not terms:
            return None

        tsquery_parts = []
        for term in terms:
            words = [w for w in term.split() if w]
            if words:
                tsquery_parts.append(' & '.join(words))

        return ' | '.join(tsquery_parts) if tsquery_parts else None

    @staticmethod
    async def _get_wish_based_recommendations(
        user_id: str,
        geo_id: int,
        wish_text: str,
        unwish_text: Optional[str],
        locale: Optional[str],
        user_likes: List[str],
        items_needed: int = 100,
        filters: Optional[Any] = None
    ) -> List[str]:
        """
        Wish-based recommendations: match parsed wish keywords against item names/descriptions
        using PostgreSQL full-text search. Unwish keywords exclude matching items.
        """
        # Truncate very long wish text
        wish_text = wish_text[:500]

        config_name, tsvector_col = RecommendationServiceV2._get_locale_search_config(locale)

        wish_tsquery = RecommendationServiceV2._build_wish_tsquery(wish_text)
        if not wish_tsquery:
            return []

        logger.info(f"[WISH] Building wish-based recs for user {user_id}, "
                     f"locale={locale}, config={config_name}, tsquery={wish_tsquery[:100]}")

        # Base conditions: FTS match + geo + in_stock + system items + wishlist exclusion
        base_conditions = [
            f"hp.{tsvector_col} @@ to_tsquery('{config_name}', $1)",
            "hp.geo_id = $2",
            "hp.status = 'in_stock'",
            "hp.user_id IS NULL",
            f"hp.id NOT IN (SELECT handpicked_present_id FROM handpicked_likes WHERE user_id::text = $3)"
        ]
        base_params = [wish_tsquery, geo_id, user_id]
        param_count = 3

        # Exclude already-liked items
        if user_likes:
            param_count += 1
            base_conditions.append(f"hp.id::text != ALL(${param_count}::text[])")
            base_params.append(user_likes)

        # Exclude unwish matches
        if unwish_text:
            unwish_text = unwish_text[:500]
            unwish_tsquery = RecommendationServiceV2._build_wish_tsquery(unwish_text)
            if unwish_tsquery:
                param_count += 1
                base_conditions.append(
                    f"NOT hp.{tsvector_col} @@ to_tsquery('{config_name}', ${param_count})"
                )
                base_params.append(unwish_tsquery)

        # Push user filters into the query
        filter_conditions, filter_params = RecommendationServiceV2._build_filter_conditions(
            filters, "hp", param_count
        )
        all_conditions = base_conditions + filter_conditions
        all_params = base_params + filter_params

        fetch_limit = max(200, items_needed * 3)

        query = f"""
            SELECT hp.id::text as item_id,
                   ts_rank(hp.{tsvector_col}, to_tsquery('{config_name}', $1)) as relevance
            FROM handpicked_presents hp
            WHERE {' AND '.join(all_conditions)}
            ORDER BY relevance DESC, hp.popularity_score DESC
            LIMIT {fetch_limit}
        """

        try:
            results = await db.execute_main_query(query, *all_params)
            item_ids = [row['item_id'] for row in results]
            logger.info(f"[WISH] Found {len(item_ids)} wish-matched items for user {user_id}")
            return item_ids
        except Exception as e:
            logger.error(f"[WISH] Error in wish-based recommendations for user {user_id}: {e}")
            return []