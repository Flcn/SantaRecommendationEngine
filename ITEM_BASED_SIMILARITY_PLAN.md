# Item-Based Similarity System Implementation Plan

**Document Purpose:** Complete specification for implementing item-based similarity system to replace user-based similarity calculation in MySanta Recommendation Engine.

**Created:** 2025-07-06  
**Status:** Ready for Implementation  
**Priority:** High - Fixes collaborative filtering for 128k users

## Executive Summary

### Current Problem
- User similarity calculation limited to 20-user batches
- Only 24 total user similarities found across all 128k users
- Collaborative filtering severely limited by poor similarity coverage
- New users cannot get collaborative recommendations

### Proposed Solution
Replace user-to-user similarity with item-to-item similarity matrix:
- Calculate which items are frequently liked together
- Compute user similarities on-demand via their liked items
- Scale from O(users²) to O(items²): 128k users → 16k items
- Enable instant similarity calculation for new users

### Expected Benefits
- **50k+ item similarities** vs 24 user similarities
- **Instant new user coverage** - no waiting for full sync
- **10x faster** similarity calculation
- **Better recommendation quality** for collaborative filtering

## Current System Analysis

### Recommendation Flow (Already Perfect ✅)
```
User State → Algorithm Used
├── 0 interactions → Popular items by demographics
├── 1-2 interactions → Content-based filtering  
└── 3+ interactions → Collaborative filtering
```

### Current Collaborative Filtering Implementation
**File:** `app/recommendation_service_v2.py:330-379`
```python
async def _get_collaborative_recommendations(user_id: str, geo_id: int, user_likes: List[str]):
    # 1. Get similar users from user_similarities table
    similar_users = await db.execute_recommendations_query(similar_users_query, user_id, max_similar_users)
    
    # 2. Get items liked by similar users
    recommendations = await db.execute_main_query(recommendations_query, similar_user_ids, geo_id, user_likes)
```

### Current Similarity Calculation Problem
**File:** `full_sync.py:418-441`
```sql
-- PROBLEM: Only compares users within same batch
WITH user_items AS (
    SELECT user_id::text, array_agg(handpicked_present_id) as liked_items
    FROM handpicked_likes
    WHERE user_id::text = ANY($1::varchar[])  -- ❌ Limited to batch only
    GROUP BY user_id
),
similarities AS (
    SELECT u1.user_id, u2.user_id, overlap
    FROM user_items u1
    CROSS JOIN user_items u2  -- ❌ Only within batch (20×20=400 comparisons)
    WHERE u1.user_id != u2.user_id
)
```

**Result:** 24 total similarities across all users instead of expected 50k+

## Item-Based Similarity System Design

### Core Algorithm

#### Step 1: Item-to-Item Similarity Matrix
```sql
-- Calculate which items are frequently liked together
WITH item_pairs AS (
    SELECT 
        l1.handpicked_present_id as item_a,
        l2.handpicked_present_id as item_b,
        COUNT(*) as co_occurrence_count
    FROM handpicked_likes l1
    JOIN handpicked_likes l2 ON l1.user_id = l2.user_id
    WHERE l1.handpicked_present_id != l2.handpicked_present_id
      AND l1.handpicked_present_id < l2.handpicked_present_id  -- Avoid duplicates
    GROUP BY l1.handpicked_present_id, l2.handpicked_present_id
    HAVING COUNT(*) >= 3  -- Minimum 3 users must like both items
),
item_totals AS (
    SELECT 
        handpicked_present_id as item_id,
        COUNT(*) as total_likes
    FROM handpicked_likes
    GROUP BY handpicked_present_id
)
SELECT 
    ip.item_a,
    ip.item_b,
    ip.co_occurrence_count,
    it1.total_likes as item_a_total_likes,
    it2.total_likes as item_b_total_likes,
    -- Jaccard similarity: intersection / union
    ip.co_occurrence_count::float / (it1.total_likes + it2.total_likes - ip.co_occurrence_count) as similarity_score
FROM item_pairs ip
JOIN item_totals it1 ON ip.item_a = it1.item_id
JOIN item_totals it2 ON ip.item_b = it2.item_id
WHERE ip.co_occurrence_count::float / (it1.total_likes + it2.total_likes - ip.co_occurrence_count) >= 0.1  -- 10% minimum similarity
ORDER BY similarity_score DESC;
```

#### Step 2: User Similarity via Items
```python
async def calculate_user_similarity_via_items(user_a_items: List[str], user_b_items: List[str]) -> float:
    """Calculate similarity between two users based on their items"""
    
    if not user_a_items or not user_b_items:
        return 0.0
    
    total_similarity = 0.0
    comparisons = 0
    
    for item_a in user_a_items:
        for item_b in user_b_items:
            if item_a == item_b:
                # Same item = perfect similarity
                similarity = 1.0
            else:
                # Look up item similarity from matrix
                similarity = await get_item_similarity(item_a, item_b)
            
            total_similarity += similarity
            comparisons += 1
    
    return total_similarity / comparisons if comparisons > 0 else 0.0

async def get_item_similarity(item_a: str, item_b: str) -> float:
    """Get similarity between two items from the similarity matrix"""
    # Check both directions since we store item_a < item_b
    query = """
        SELECT similarity_score 
        FROM item_similarities 
        WHERE (item_a = $1 AND item_b = $2) 
           OR (item_a = $2 AND item_b = $1)
        LIMIT 1
    """
    result = await db.execute_recommendations_query_one(query, item_a, item_b)
    return result['similarity_score'] if result else 0.0
```

#### Step 3: New Collaborative Filtering Algorithm
```python
async def _get_collaborative_recommendations_via_items(
    user_id: str, 
    geo_id: int, 
    user_likes: List[str]
) -> List[str]:
    """Get collaborative recommendations using item-based similarity"""
    
    if not user_likes:
        return []
    
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
          AND similarity_score >= 0.2  -- Minimum similarity threshold
        ORDER BY similarity_score DESC
        LIMIT 200
    """
    
    similar_items = await db.execute_recommendations_query(
        similar_items_query, user_likes
    )
    
    if not similar_items:
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
    
    return [row['item_id'] for row in results]
```

## Database Schema Changes

### New Table: item_similarities
```sql
-- Item-to-item similarity matrix
CREATE TABLE item_similarities (
    item_a VARCHAR(36) NOT NULL,  -- UUID as string (always smaller UUID)
    item_b VARCHAR(36) NOT NULL,  -- UUID as string (always larger UUID)
    similarity_score DECIMAL(6,4) NOT NULL DEFAULT 0,
    co_occurrence_count INTEGER NOT NULL DEFAULT 0,
    item_a_total_likes INTEGER NOT NULL DEFAULT 0,
    item_b_total_likes INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(item_a, item_b),
    CONSTRAINT check_item_order CHECK (item_a < item_b)  -- Prevent duplicates
);

-- Indexes for fast item similarity lookups
CREATE INDEX idx_item_similarities_lookup_a ON item_similarities(item_a, similarity_score DESC);
CREATE INDEX idx_item_similarities_lookup_b ON item_similarities(item_b, similarity_score DESC);
CREATE INDEX idx_item_similarities_updated ON item_similarities(updated_at);
CREATE INDEX idx_item_similarities_score ON item_similarities(similarity_score DESC);
```

### Updated Schema File
**File:** `schema_minimal.sql`
- Add `item_similarities` table after `user_similarities` table
- Keep existing tables for backward compatibility during migration

## Implementation Plan

### Phase 1: Infrastructure Setup
**Estimated Time:** 2-3 hours

1. **Update Database Schema**
   - Add `item_similarities` table to `schema_minimal.sql`
   - Create migration script for existing databases
   - Apply to local development environment

2. **Add Helper Functions**
   - `get_item_similarity(item_a, item_b)` function
   - `calculate_user_similarity_via_items()` function
   - Add to new file: `app/similarity_utils.py`

### Phase 2: Item Similarity Calculation
**Estimated Time:** 4-5 hours

1. **Update full_sync.py**
   - Add `_build_item_similarity_matrix()` method
   - Replace user similarity batch processing
   - Add progress logging for item similarity computation

2. **Implementation Details**
   ```python
   @staticmethod
   async def _build_item_similarity_matrix():
       """Build item-to-item similarity matrix"""
       logger.info("🔗 Step 4: Building item-to-item similarity matrix...")
       start_time = time.time()
       
       # Clear existing item similarities
       await db.execute_recommendations_command("DELETE FROM item_similarities")
       
       # Calculate item similarities using the SQL query above
       similarity_query = """..."""  # Full query from design section
       
       similarities = await db.execute_main_query(similarity_query)
       
       # Batch insert similarities
       if similarities:
           # Build batch insert...
           await db.execute_recommendations_command(insert_query, *params)
       
       logger.info(f"✅ Created {len(similarities)} item similarities")
   ```

### Phase 3: Update Collaborative Filtering
**Estimated Time:** 3-4 hours

1. **New Collaborative Algorithm**
   - Create `_get_collaborative_recommendations_via_items()` method
   - Keep existing method as `_get_collaborative_recommendations_legacy()`
   - Add feature flag to switch between algorithms

2. **Integration**
   ```python
   # In recommendation_service_v2.py
   if settings.use_item_based_similarity:
       recommended_items = await RecommendationServiceV2._get_collaborative_recommendations_via_items(
           request.user_id, request.geo_id, user_likes
       )
   else:
       recommended_items = await RecommendationServiceV2._get_collaborative_recommendations_legacy(
           request.user_id, request.geo_id, user_likes
       )
   ```

### Phase 4: Real-Time User Similarity
**Estimated Time:** 2-3 hours

1. **User Profile Update Endpoint (Enhanced)**
   ```python
   @app.put("/user-profile/{user_id}")
   async def update_user_profile(user_id: str, profile_data: UserDemographicsUpdate):
       """Update user profile and trigger similarity calculation if needed"""
       
       # Update user demographics (existing functionality)
       await update_user_demographics(user_id, profile_data)
       
       # Check if user has enough interactions for collaborative filtering
       user_items = await get_user_liked_items(user_id)
       
       if len(user_items) >= 2:  # After 2+ likes, calculate similarities
           await calculate_and_store_user_similarities(user_id, user_items)
           return {
               "profile_updated": True,
               "similarities_calculated": True,
               "items_count": len(user_items),
               "message": "Profile updated and similarities calculated"
           }
       
       return {
           "profile_updated": True,
           "similarities_calculated": False,
           "items_count": len(user_items),
           "message": "Profile updated, not enough interactions for similarities"
       }
   ```

2. **New Like Tracking Endpoint**
   ```python
   @app.post("/user-interaction/{user_id}")
   async def track_user_interaction(user_id: str, interaction_data: UserInteractionUpdate):
       """Track user interaction and trigger similarity calculation when reaching 2+ likes"""
       
       interaction_type = interaction_data.interaction_type  # 'like', 'click', etc.
       
       if interaction_type == 'like':
           # Get current user's liked items
           user_items = await get_user_liked_items(user_id)
           
           if len(user_items) >= 2:  # After 2+ likes, calculate similarities
               await calculate_and_store_user_similarities(user_id, user_items)
               return {
                   "interaction_tracked": True,
                   "similarities_calculated": True,
                   "items_count": len(user_items),
                   "message": "Interaction tracked and similarities calculated"
               }
       
       return {
           "interaction_tracked": True,
           "similarities_calculated": False,
           "message": "Interaction tracked, not enough likes for similarities"
       }
   ```

3. **Similarity Calculation Helper Function**
   ```python
   async def calculate_and_store_user_similarities(user_id: str, user_items: List[str]):
       """Calculate similarities for a user and store in database"""
       
       if not user_items:
           return
       
       # Find candidate users who like similar items
       candidate_users = await find_candidate_users_via_items(user_items)
       
       # Calculate similarities
       similarities = []
       for candidate_user in candidate_users:
           similarity_score = await calculate_user_similarity_via_items(
               user_items, candidate_user['items']
           )
           if similarity_score >= 0.3:  # Minimum threshold
               similarities.append({
                   'user_id': candidate_user['user_id'],
                   'similarity_score': similarity_score
               })
       
       # Store in user_similarities table for caching
       if similarities:
           await store_user_similarities(user_id, similarities)
           logger.info(f"Calculated {len(similarities)} similarities for user {user_id}")
   ```

4. **Rails Integration Points**
   ```ruby
   # In Rails User model
   after_update :sync_to_recommendation_engine, if: :recommendation_relevant_changes?
   
   # In Rails HandpickedLike model (when user likes an item)
   after_create :trigger_similarity_calculation
   
   private
   
   def trigger_similarity_calculation
     RecommendationSyncJob.perform_later(
       user_id: user_id,
       action: 'interaction',
       interaction_type: 'like'
     )
   end
   ```

5. **Updated Pydantic Models**
   ```python
   class UserInteractionUpdate(BaseModel):
       interaction_type: str = Field(..., description="Type of interaction: like, click, etc.")
       item_id: Optional[str] = Field(None, description="ID of the item interacted with")
       timestamp: Optional[datetime] = Field(default_factory=datetime.now)
   ```

### Phase 5: Testing & Migration
**Estimated Time:** 3-4 hours

1. **A/B Testing Setup**
   - Add `USE_ITEM_BASED_SIMILARITY` environment variable
   - Run both algorithms in parallel
   - Compare recommendation quality and performance

2. **Migration Strategy**
   - Deploy with item-based disabled initially
   - Run full sync to populate item similarities
   - Enable item-based algorithm for 10% of users
   - Gradually increase to 100% based on metrics

3. **Performance Testing**
   - Measure response times for both algorithms
   - Compare recommendation diversity and quality
   - Monitor database load and cache hit rates

## Performance Analysis

### Expected Improvements

#### Similarity Coverage
- **Current:** 24 user similarities total
- **Expected:** 50k+ item similarities
- **User Coverage:** Every user with 1+ items gets instant similarities

#### Computation Time
- **Current:** 17 minutes for 10k users (limited similarities)
- **Expected:** 5-10 minutes for complete item matrix
- **New User:** Instant (< 100ms) vs waiting for next full sync

#### Recommendation Quality
- **Better Diversity:** Items similar to user's preferences vs only similar users' exact items
- **Cold Start:** New users get collaborative recommendations immediately
- **Accuracy:** Based on actual item relationships vs sparse user similarities

### Resource Requirements

#### Storage
- **Item Similarities:** ~50k records × 64 bytes = 3.2MB
- **Indexes:** ~10MB total
- **Cache Impact:** Minimal - same Redis usage

#### Computation
- **Full Sync:** Reduced from O(users²) to O(items²)
- **Real-time:** O(user_items × avg_similar_items) = O(10 × 50) = 500 operations
- **Memory:** Existing database connections sufficient

## Testing Strategy

### Unit Tests
```python
# tests/test_item_similarity.py
async def test_item_similarity_calculation():
    # Test item-to-item similarity matrix generation
    # Test user similarity via items
    # Test collaborative recommendations via items

async def test_new_user_similarity_endpoint():
    # Test instant similarity calculation for new users
    # Test empty result handling
    # Test performance benchmarks
```

### Integration Tests
- Test full sync with item similarity generation
- Test collaborative filtering with item-based algorithm
- Test A/B testing between old and new algorithms

### Performance Tests
- Benchmark response times for both algorithms
- Memory usage comparison
- Database load testing

## Rollback Plan

### If Issues Arise
1. **Immediate:** Set `USE_ITEM_BASED_SIMILARITY=false`
2. **Fallback:** Existing user similarity system remains functional
3. **Investigation:** Analyze logs and performance metrics
4. **Fix:** Address issues and re-enable gradually

### Success Criteria
- **Response Time:** < 100ms for 95% of requests
- **Recommendation Quality:** Equal or better diversity scores
- **Similarity Coverage:** > 10x current user similarities
- **New User Coverage:** Instant collaborative recommendations

## Monitoring & Metrics

### Key Performance Indicators
- Item similarity count and distribution
- User similarity calculation speed
- Collaborative filtering recommendation quality
- Cache hit rates and database load

### Logging Enhancements
```python
logger.info(f"Item similarities: {item_count}, User similarities: {user_count}")
logger.info(f"Collaborative filtering: {algorithm_used}, Items found: {item_count}, Response time: {duration}ms")
logger.info(f"New user similarity: {user_id}, Items: {len(user_items)}, Similarities found: {similarity_count}")
```

## Future Enhancements

### Phase 6: Advanced Features
1. **Incremental Updates:** Update item similarities as new likes are added
2. **Category-Specific Similarities:** Different similarity matrices per category
3. **Temporal Decay:** Weight recent interactions higher
4. **Machine Learning:** Use SantaML for advanced similarity computation

### Phase 7: Optimization
1. **Clustering:** Group similar items for faster lookups
2. **Approximation:** Use LSH for ultra-fast similarity estimation
3. **Distributed Computing:** Scale item similarity calculation across workers

## Conclusion

This item-based similarity system addresses the core limitation of the current collaborative filtering approach while maintaining the excellent recommendation flow already implemented. The migration can be done safely with A/B testing and gradual rollout.

**Next Steps:**
1. Review and approve this implementation plan
2. Begin Phase 1: Infrastructure setup
3. Implement and test each phase incrementally
4. Monitor performance and adjust as needed

The system will transform from finding 24 user similarities to generating 50k+ item similarities, enabling true collaborative filtering for all 128k users.