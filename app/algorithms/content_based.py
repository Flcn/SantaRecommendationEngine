"""
Content-based filtering algorithms
Recommends items based on item features and user preferences
"""

import logging
from typing import List, Tuple, Dict, Any, Optional
from app.database import db
from app.config import settings

logger = logging.getLogger(__name__)


class ContentBasedFilter:
    """Content-based recommendation using item features and user preferences"""
    
    @staticmethod
    async def get_user_profile(user_id: int) -> Dict[str, Any]:
        """
        Build user profile from their interaction history
        """
        cache_key = f"user_profile:{user_id}"
        
        cached_profile = db.cache_get(cache_key)
        if cached_profile:
            return cached_profile
        
        try:
            # Get user's liked items and their features
            profile_query = """
                SELECT 
                    hp.categories,
                    hp.price,
                    hp.platform,
                    hl.created_at as interaction_date
                FROM handpicked_likes hl
                JOIN handpicked_presents hp ON hl.handpicked_present_id = hp.id
                WHERE hl.user_id = $1
                ORDER BY hl.created_at DESC
                LIMIT 50  -- Limit to recent preferences
            """
            
            interactions = await db.execute_query(profile_query, user_id)
            
            if not interactions:
                return {}
            
            # Build preference profile
            profile = {
                'category_preferences': {},
                'platform_preferences': {},
                'price_range': {'min': float('inf'), 'max': 0, 'avg': 0},
                'interaction_count': len(interactions)
            }
            
            total_price = 0
            valid_prices = 0
            
            for interaction in interactions:
                categories = interaction.get('categories', {})
                price = interaction.get('price', 0)
                platform = interaction.get('platform', '')
                
                # Category preferences
                for cat_type, cat_value in categories.items():
                    if cat_value and cat_type != 'unknown':
                        key = f"{cat_type}:{cat_value}"
                        profile['category_preferences'][key] = profile['category_preferences'].get(key, 0) + 1
                
                # Platform preferences
                if platform:
                    profile['platform_preferences'][platform] = profile['platform_preferences'].get(platform, 0) + 1
                
                # Price preferences
                if price and price > 0:
                    profile['price_range']['min'] = min(profile['price_range']['min'], price)
                    profile['price_range']['max'] = max(profile['price_range']['max'], price)
                    total_price += price
                    valid_prices += 1
            
            # Calculate average price
            if valid_prices > 0:
                profile['price_range']['avg'] = total_price / valid_prices
            else:
                profile['price_range'] = {'min': 0, 'max': 0, 'avg': 0}
            
            # Normalize preference counts to percentages
            total_category_prefs = sum(profile['category_preferences'].values())
            if total_category_prefs > 0:
                for key in profile['category_preferences']:
                    profile['category_preferences'][key] /= total_category_prefs
            
            total_platform_prefs = sum(profile['platform_preferences'].values())
            if total_platform_prefs > 0:
                for key in profile['platform_preferences']:
                    profile['platform_preferences'][key] /= total_platform_prefs
            
            # Cache profile (longer TTL since preferences change slowly)
            db.cache_set(cache_key, profile, settings.cache_ttl_similarity)
            
            return profile
            
        except Exception as e:
            logger.error(f"Error building user profile for {user_id}: {e}")
            return {}
    
    @staticmethod
    def calculate_item_score(item: Dict[str, Any], user_profile: Dict[str, Any]) -> float:
        """
        Calculate content-based similarity score between item and user profile
        """
        if not user_profile:
            return 0.0
        
        score = 0.0
        
        # Category matching (40% weight)
        categories = item.get('categories', {})
        category_prefs = user_profile.get('category_preferences', {})
        
        for cat_type, cat_value in categories.items():
            if cat_value and cat_type != 'unknown':
                key = f"{cat_type}:{cat_value}"
                if key in category_prefs:
                    score += 0.4 * category_prefs[key]
        
        # Platform preference (20% weight)
        platform = item.get('platform', '')
        platform_prefs = user_profile.get('platform_preferences', {})
        if platform in platform_prefs:
            score += 0.2 * platform_prefs[platform]
        
        # Price similarity (30% weight)
        item_price = item.get('price', 0)
        price_range = user_profile.get('price_range', {})
        avg_price = price_range.get('avg', 0)
        
        if avg_price > 0 and item_price > 0:
            # Calculate price similarity (closer to average = higher score)
            price_diff = abs(item_price - avg_price) / avg_price
            price_similarity = max(0, 1 - price_diff)  # 0 to 1 scale
            score += 0.3 * price_similarity
        
        # Recency bonus (10% weight) - newer items get slight boost
        try:
            from datetime import datetime, timezone
            created_at = item.get('created_at')
            if created_at:
                if isinstance(created_at, str):
                    created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                else:
                    created_date = created_at
                    
                days_old = (datetime.now(timezone.utc) - created_date).days
                recency_score = max(0, 1 - (days_old / 365))  # Decay over a year
                score += 0.1 * recency_score
        except Exception:
            pass  # Skip recency scoring if date parsing fails
        
        return min(score, 1.0)  # Cap at 1.0
    
    @staticmethod
    async def get_content_recommendations(
        user_id: int,
        geo_id: int,
        limit: int = 50
    ) -> List[Tuple[int, float]]:
        """
        Get content-based recommendations for user
        """
        try:
            # Get user profile
            user_profile = await ContentBasedFilter.get_user_profile(user_id)
            
            if not user_profile:
                return []
            
            # Get user's already liked items to exclude
            user_likes_query = """
                SELECT handpicked_present_id 
                FROM handpicked_likes 
                WHERE user_id = $1
            """
            user_likes = await db.execute_query(user_likes_query, user_id)
            excluded_items = [row['handpicked_present_id'] for row in user_likes]
            
            # Get candidate items with their features
            items_query = """
                SELECT 
                    id,
                    categories,
                    price,
                    platform,
                    created_at
                FROM handpicked_presents
                WHERE geo_id = $1
                  AND status = 'in_stock'
                  AND user_id IS NULL
                  AND ($2::int[] IS NULL OR id != ALL($2::int[]))
                ORDER BY created_at DESC
                LIMIT $3
            """
            
            # Get more candidates than needed for scoring
            candidate_items = await db.execute_query(
                items_query,
                geo_id,
                excluded_items if excluded_items else None,
                limit * 3  # Get 3x items for scoring
            )
            
            # Score each item
            scored_items = []
            for item in candidate_items:
                score = ContentBasedFilter.calculate_item_score(item, user_profile)
                if score > 0:  # Only include items with positive scores
                    scored_items.append((item['id'], score))
            
            # Sort by score and return top items
            scored_items.sort(key=lambda x: x[1], reverse=True)
            return scored_items[:limit]
            
        except Exception as e:
            logger.error(f"Error getting content recommendations for user {user_id}: {e}")
            return []
    
    @staticmethod
    async def get_similar_items(
        item_id: int,
        geo_id: int,
        limit: int = 20
    ) -> List[Tuple[int, float]]:
        """
        Find items similar to a given item based on features
        """
        cache_key = f"similar_items:{item_id}:{limit}"
        
        cached_result = db.cache_get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            # Get target item features
            target_item_query = """
                SELECT categories, price, platform
                FROM handpicked_presents
                WHERE id = $1
            """
            target_item = await db.execute_query_one(target_item_query, item_id)
            
            if not target_item:
                return []
            
            # Get candidate items in same geo
            candidates_query = """
                SELECT id, categories, price, platform
                FROM handpicked_presents
                WHERE geo_id = $1
                  AND id != $2
                  AND status = 'in_stock'
                  AND user_id IS NULL
                LIMIT 200
            """
            
            candidates = await db.execute_query(candidates_query, geo_id, item_id)
            
            # Score similarity
            similar_items = []
            target_categories = target_item.get('categories', {})
            target_price = target_item.get('price', 0)
            target_platform = target_item.get('platform', '')
            
            for candidate in candidates:
                score = 0.0
                
                # Category similarity (60% weight)
                candidate_categories = candidate.get('categories', {})
                category_matches = 0
                total_categories = len(set(target_categories.keys()) | set(candidate_categories.keys()))
                
                if total_categories > 0:
                    for key in target_categories:
                        if key in candidate_categories and target_categories[key] == candidate_categories[key]:
                            category_matches += 1
                    score += 0.6 * (category_matches / total_categories)
                
                # Price similarity (25% weight)
                candidate_price = candidate.get('price', 0)
                if target_price > 0 and candidate_price > 0:
                    price_diff = abs(candidate_price - target_price) / target_price
                    price_similarity = max(0, 1 - price_diff)
                    score += 0.25 * price_similarity
                
                # Platform similarity (15% weight)
                if target_platform == candidate.get('platform', ''):
                    score += 0.15
                
                if score > 0.3:  # Only include reasonably similar items
                    similar_items.append((candidate['id'], score))
            
            # Sort and limit
            similar_items.sort(key=lambda x: x[1], reverse=True)
            result = similar_items[:limit]
            
            # Cache result
            db.cache_set(cache_key, result, settings.cache_ttl_recommendations)
            
            return result
            
        except Exception as e:
            logger.error(f"Error finding similar items for {item_id}: {e}")
            return []