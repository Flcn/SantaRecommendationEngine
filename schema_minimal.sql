-- MySanta Recommendations Database Schema (Minimal)
-- This is a separate database for pre-computed recommendation data
-- Updated to support UUID user_ids from Rails

-- Drop existing tables if they exist (for clean recreation)
DROP TABLE IF EXISTS user_similarities CASCADE;
DROP TABLE IF EXISTS user_profiles CASCADE;
DROP TABLE IF EXISTS popular_items CASCADE;

-- Popular items by demographics (refreshed every 15 minutes)
CREATE TABLE popular_items (
    id SERIAL PRIMARY KEY,
    geo_id INTEGER NOT NULL,
    gender VARCHAR(10),
    age_group VARCHAR(20),
    category VARCHAR(50),
    item_id VARCHAR(36) NOT NULL,  -- UUID as string
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
    user_id VARCHAR(36) NOT NULL,  -- UUID as string
    similar_user_id VARCHAR(36) NOT NULL,  -- UUID as string
    similarity_score DECIMAL(6,4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, similar_user_id)
);

-- Indexes for similarity lookups
CREATE INDEX idx_user_similarities_lookup ON user_similarities(user_id, similarity_score DESC);
CREATE INDEX idx_user_similarities_updated ON user_similarities(updated_at);

-- User profiles cache (refreshed when user gets new likes)
CREATE TABLE user_profiles (
    user_id VARCHAR(36) PRIMARY KEY,  -- UUID as string
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

-- Item-to-item similarity matrix (NEW for item-based collaborative filtering)
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

-- Placeholder function for refresh_popular_items 
-- Real population happens in Python background jobs that query both databases
CREATE OR REPLACE FUNCTION refresh_popular_items() RETURNS void AS $$
BEGIN
    -- This function is kept for compatibility with existing code
    -- The actual data refresh is handled by the Python background job
    -- that can access both main and recommendations databases
    RAISE NOTICE 'refresh_popular_items() called - actual refresh handled by background job';
END;
$$ LANGUAGE plpgsql;

-- Simple function to clean up old cache data
CREATE OR REPLACE FUNCTION cleanup_cache_data() RETURNS void AS $$
BEGIN
    -- Clean up old similarity data (older than 24 hours)
    DELETE FROM user_similarities WHERE updated_at < NOW() - INTERVAL '24 hours';
    
    -- Clean up old popular items (older than 2 hours)  
    DELETE FROM popular_items WHERE updated_at < NOW() - INTERVAL '2 hours';
    
END;
$$ LANGUAGE plpgsql;