"""
Utility functions for item-based and user-based similarity calculations.
Supports the new item-based collaborative filtering approach.
"""

import logging
from typing import List, Dict, Optional, Tuple
from app.database import db

logger = logging.getLogger(__name__)


async def get_item_similarity(item_a: str, item_b: str) -> float:
    """
    Get similarity between two items from the item_similarities table.
    
    Args:
        item_a: First item UUID
        item_b: Second item UUID
        
    Returns:
        Similarity score (0.0 to 1.0), or 0.0 if no similarity found
    """
    if item_a == item_b:
        return 1.0
    
    # Ensure consistent ordering (smaller UUID first)
    if item_a > item_b:
        item_a, item_b = item_b, item_a
    
    query = """
        SELECT similarity_score 
        FROM item_similarities 
        WHERE item_a = $1 AND item_b = $2
        LIMIT 1
    """
    
    try:
        result = await db.execute_recommendations_query_one(query, item_a, item_b)
        return float(result['similarity_score']) if result else 0.0
    except Exception as e:
        logger.error(f"Error getting item similarity for {item_a}, {item_b}: {e}")
        return 0.0


async def calculate_user_similarity_via_items(user_a_items: List[str], user_b_items: List[str]) -> float:
    """
    Calculate similarity between two users based on their liked items using item-based approach.
    
    Args:
        user_a_items: List of item UUIDs liked by user A
        user_b_items: List of item UUIDs liked by user B
        
    Returns:
        Similarity score (0.0 to 1.0)
    """
    if not user_a_items or not user_b_items:
        return 0.0
    
    total_similarity = 0.0
    comparisons = 0
    
    for item_a in user_a_items:
        for item_b in user_b_items:
            similarity = await get_item_similarity(item_a, item_b)
            total_similarity += similarity
            comparisons += 1
    
    return total_similarity / comparisons if comparisons > 0 else 0.0


async def find_candidate_users_via_items(user_items: List[str], limit: int = 100) -> List[Dict]:
    """
    Find candidate users who liked similar items to the given user.
    
    Args:
        user_items: List of item UUIDs liked by the target user
        limit: Maximum number of candidate users to return
        
    Returns:
        List of dictionaries with user_id and their liked items
    """
    if not user_items:
        return []
    
    # Find items similar to what the user likes
    similar_items_query = """
        SELECT 
            CASE 
                WHEN item_a = ANY($1::text[]) THEN item_b
                WHEN item_b = ANY($1::text[]) THEN item_a
            END as similar_item,
            similarity_score
        FROM item_similarities
        WHERE (item_a = ANY($1::text[]) OR item_b = ANY($1::text[]))
          AND similarity_score >= 0.2  -- Minimum similarity threshold
        ORDER BY similarity_score DESC
        LIMIT 500
    """
    
    try:
        similar_items = await db.execute_recommendations_query(similar_items_query, user_items)
        
        if not similar_items:
            return []
        
        # Get all items (original + similar)
        all_items = list(set(user_items + [item['similar_item'] for item in similar_items]))
        
        # Find users who liked these items
        candidate_users_query = """
            SELECT 
                user_id::text,
                array_agg(handpicked_present_id::text) as liked_items
            FROM handpicked_likes
            WHERE handpicked_present_id::text = ANY($1::text[])
            GROUP BY user_id
            HAVING COUNT(*) >= 2  -- At least 2 interactions
            ORDER BY COUNT(*) DESC
            LIMIT $2
        """
        
        candidate_users = await db.execute_main_query(candidate_users_query, all_items, limit)
        
        return [
            {
                'user_id': user['user_id'],
                'items': user['liked_items']
            }
            for user in candidate_users
        ]
        
    except Exception as e:
        logger.error(f"Error finding candidate users: {e}")
        return []


async def get_user_liked_items(user_id: str) -> List[str]:
    """
    Get all items liked by a specific user.
    
    Args:
        user_id: User UUID
        
    Returns:
        List of item UUIDs liked by the user
    """
    query = """
        SELECT handpicked_present_id::text as item_id
        FROM handpicked_likes
        WHERE user_id::text = $1
        ORDER BY created_at DESC
    """
    
    try:
        results = await db.execute_main_query(query, user_id)
        return [row['item_id'] for row in results]
    except Exception as e:
        logger.error(f"Error getting user liked items for {user_id}: {e}")
        return []


async def store_user_similarities(user_id: str, similarities: List[Dict]) -> bool:
    """
    Store user similarities in the database.
    
    Args:
        user_id: Target user UUID
        similarities: List of dicts with 'user_id' and 'similarity_score'
        
    Returns:
        True if successful, False otherwise
    """
    if not similarities:
        return True
    
    try:
        # Clear existing similarities for this user
        clear_query = "DELETE FROM user_similarities WHERE user_id = $1"
        await db.execute_recommendations_command(clear_query, user_id)
        
        # Insert new similarities
        insert_query = """
            INSERT INTO user_similarities (user_id, similar_user_id, similarity_score, updated_at)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
        """
        
        for sim in similarities:
            await db.execute_recommendations_command(
                insert_query, 
                user_id, 
                sim['user_id'], 
                sim['similarity_score']
            )
        
        logger.info(f"Stored {len(similarities)} similarities for user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error storing user similarities for {user_id}: {e}")
        return False


async def calculate_and_store_user_similarities(user_id: str, user_items: Optional[List[str]] = None) -> Dict:
    """
    Calculate similarities for a user and store them in the database.
    
    Args:
        user_id: Target user UUID
        user_items: Optional list of user's liked items (will fetch if not provided)
        
    Returns:
        Dictionary with calculation results
    """
    if user_items is None:
        user_items = await get_user_liked_items(user_id)
    
    if not user_items:
        return {
            'similarities_calculated': False,
            'total_found': 0,
            'items_count': 0,
            'message': 'No items liked yet'
        }
    
    # Find candidate users who like similar items
    candidate_users = await find_candidate_users_via_items(user_items)
    
    if not candidate_users:
        return {
            'similarities_calculated': False,
            'total_found': 0,
            'items_count': len(user_items),
            'message': 'No candidate users found'
        }
    
    # Calculate similarities
    similarities = []
    for candidate_user in candidate_users:
        if candidate_user['user_id'] == user_id:
            continue  # Skip self
            
        similarity_score = await calculate_user_similarity_via_items(
            user_items, candidate_user['items']
        )
        
        if similarity_score >= 0.3:  # Minimum threshold
            similarities.append({
                'user_id': candidate_user['user_id'],
                'similarity_score': similarity_score
            })
    
    # Store similarities if found
    stored = False
    if similarities:
        stored = await store_user_similarities(user_id, similarities)
    
    return {
        'similarities_calculated': stored,
        'total_found': len(similarities),
        'items_count': len(user_items),
        'candidate_users': len(candidate_users),
        'message': f'Calculated similarities for {len(similarities)} users'
    }