-- MySanta Recommendations Database Schema
-- This is a separate database for pre-computed recommendation data

-- Popular items by demographics (refreshed every 15 minutes)
CREATE TABLE popular_items (
    id SERIAL PRIMARY KEY,
    geo_id INTEGER NOT NULL,
    gender VARCHAR(10),
    age_group VARCHAR(20),
    category VARCHAR(50),
    item_id INTEGER NOT NULL,
    popularity_score DECIMAL(10,4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX idx_popular_items_lookup ON popular_items(geo_id, gender, age_group, category, popularity_score DESC);
CREATE INDEX idx_popular_items_item_id ON popular_items(item_id);
CREATE INDEX idx_popular_items_updated ON popular_items(updated_at);

-- User similarity cache (refreshed hourly for active users)  
CREATE TABLE user_similarities (
    user_id INTEGER NOT NULL,
    similar_user_id INTEGER NOT NULL,
    similarity_score DECIMAL(6,4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, similar_user_id)
);

-- Indexes for similarity lookups
CREATE INDEX idx_user_similarities_lookup ON user_similarities(user_id, similarity_score DESC);
CREATE INDEX idx_user_similarities_updated ON user_similarities(updated_at);

-- User profiles cache (refreshed when user gets new likes)
CREATE TABLE user_profiles (
    user_id INTEGER PRIMARY KEY,
    preferred_categories JSONB,
    preferred_platforms JSONB,
    avg_price DECIMAL(10,2),
    price_range_min DECIMAL(10,2),
    price_range_max DECIMAL(10,2),
    interaction_count INTEGER DEFAULT 0,
    last_interaction_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for user profile lookups
CREATE INDEX idx_user_profiles_updated ON user_profiles(updated_at);
CREATE INDEX idx_user_profiles_interaction_count ON user_profiles(interaction_count DESC);

-- Materialized view for popular items computation
CREATE MATERIALIZED VIEW popular_items_base AS
SELECT 
    hp.geo_id,
    COALESCE(hp.categories->>'gender', 'any') as gender,
    COALESCE(hp.categories->>'age', 'any') as age_group,
    COALESCE(hp.categories->>'category', 'any') as category,
    hp.id as item_id,
    
    -- Time-weighted popularity score
    COALESCE(click_scores.score, 0) + COALESCE(like_scores.score, 0) as popularity_score,
    
    -- For debugging
    COALESCE(click_scores.recent_clicks, 0) as recent_clicks,
    COALESCE(like_scores.recent_likes, 0) as recent_likes
    
FROM handpicked_presents hp
LEFT JOIN (
    -- Click scores with time weighting
    SELECT 
        handpicked_present_id,
        SUM(
            CASE 
                WHEN created_at > NOW() - INTERVAL '7 days' THEN 3.0
                WHEN created_at > NOW() - INTERVAL '30 days' THEN 2.0
                ELSE 1.0
            END
        ) as score,
        COUNT(*) as recent_clicks
    FROM handpicked_present_clicks 
    WHERE created_at > NOW() - INTERVAL '90 days'
    GROUP BY handpicked_present_id
) click_scores ON hp.id = click_scores.handpicked_present_id
LEFT JOIN (
    -- Like scores with time weighting (higher weight than clicks)
    SELECT 
        handpicked_present_id,
        SUM(
            CASE 
                WHEN created_at > NOW() - INTERVAL '7 days' THEN 5.0
                WHEN created_at > NOW() - INTERVAL '30 days' THEN 3.0
                ELSE 1.5
            END
        ) as score,
        COUNT(*) as recent_likes
    FROM handpicked_likes 
    WHERE created_at > NOW() - INTERVAL '90 days'
    GROUP BY handpicked_present_id
) like_scores ON hp.id = like_scores.handpicked_present_id

WHERE hp.status = 'in_stock' 
  AND hp.user_id IS NULL
  AND (COALESCE(click_scores.score, 0) + COALESCE(like_scores.score, 0)) > 0;

-- Index for the materialized view
CREATE INDEX idx_popular_items_base_lookup ON popular_items_base(geo_id, gender, age_group, category, popularity_score DESC);

-- Function to refresh popular items table
CREATE OR REPLACE FUNCTION refresh_popular_items() RETURNS void AS $$
BEGIN
    -- Refresh the materialized view first
    REFRESH MATERIALIZED VIEW popular_items_base;
    
    -- Clear old popular items
    DELETE FROM popular_items WHERE updated_at < NOW() - INTERVAL '1 hour';
    
    -- Insert new popular items with all demographic combinations
    INSERT INTO popular_items (geo_id, gender, age_group, category, item_id, popularity_score, updated_at)
    SELECT DISTINCT
        geo_id,
        gender,
        age_group, 
        category,
        item_id,
        popularity_score,
        CURRENT_TIMESTAMP
    FROM popular_items_base
    WHERE popularity_score > 0
    ON CONFLICT DO NOTHING;
    
    -- Also add 'any' combinations for broader matching
    INSERT INTO popular_items (geo_id, gender, age_group, category, item_id, popularity_score, updated_at)
    SELECT DISTINCT
        geo_id,
        'any',
        'any',
        'any',
        item_id,
        popularity_score,
        CURRENT_TIMESTAMP
    FROM popular_items_base
    WHERE popularity_score > 0
    ON CONFLICT DO NOTHING;
    
END;
$$ LANGUAGE plpgsql;

-- Function to clean up old cache data
CREATE OR REPLACE FUNCTION cleanup_cache_data() RETURNS void AS $$
BEGIN
    -- Clean up old similarity data (older than 24 hours)
    DELETE FROM user_similarities WHERE updated_at < NOW() - INTERVAL '24 hours';
    
    -- Clean up old popular items (older than 2 hours)  
    DELETE FROM popular_items WHERE updated_at < NOW() - INTERVAL '2 hours';
    
END;
$$ LANGUAGE plpgsql;