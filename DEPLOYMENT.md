# Deployment Guide

## Quick Start

1. **Add to main docker-compose.yml** (already done):
```yaml
recommendation_engine:
  build: 
    context: SantaRecommendationEngine
  ports:
    - "8001:8000"
  environment:
    - DATABASE_URL=postgresql://postgres:password@db:5432/postgres
    - REDIS_URL=redis://redis:6379
  depends_on:
    - db
    - redis
```

2. **Update Rails ENV_FILE**:
```bash
# Add to SecretSanta/ENV_FILE
RECOMMENDATION_SERVICE_URL=http://recommendation_engine:8000
USE_RECOMMENDATION_SERVICE=true
```

3. **Start the services**:
```bash
cd /home/cloud-user/mysanta
docker-compose up --build recommendation_engine
```

4. **Test the service**:
```bash
curl http://localhost:8001/health
```

## Migration Strategy

### Phase 1: A/B Testing (Recommended)
- Keep both Gorse and new service running
- Use `use_collaborative=1` parameter to test new service
- Compare performance and recommendation quality

### Phase 2: Gradual Migration
- Route increasing percentage of traffic to new service
- Monitor performance and error rates
- Keep fallback to Rails-based recommendations

### Phase 3: Complete Migration
- Remove Gorse service from docker-compose.yml
- Remove old collaborative filtering code
- Clean up unused gems and dependencies

## Monitoring

1. **Health Checks**:
```bash
curl http://localhost:8001/health
curl http://localhost:8001/stats
```

2. **Performance Monitoring**:
- Response times should be < 200ms
- Cache hit rates > 80%
- Memory usage < 100MB per worker

3. **Error Monitoring**:
- Check Rails logs for fallback usage
- Monitor Python service logs for errors
- Set up alerts for service downtime

## Required Database Indexes

For optimal performance, ensure these indexes exist:

```sql
-- Essential for collaborative filtering
CREATE INDEX CONCURRENTLY idx_handpicked_likes_user_present 
  ON handpicked_likes(user_id, handpicked_present_id);

CREATE INDEX CONCURRENTLY idx_handpicked_likes_present_user 
  ON handpicked_likes(handpicked_present_id, user_id);

-- For popularity scoring
CREATE INDEX CONCURRENTLY idx_handpicked_present_clicks_present_time 
  ON handpicked_present_clicks(handpicked_present_id, created_at);

-- For filtering
CREATE INDEX CONCURRENTLY idx_handpicked_presents_geo_status_user 
  ON handpicked_presents(geo_id, status, user_id);

-- For category filtering (if not exists)
CREATE INDEX CONCURRENTLY idx_handpicked_presents_categories 
  ON handpicked_presents USING gin(categories);

-- Partial index for in-stock items
CREATE INDEX CONCURRENTLY idx_handpicked_presents_in_stock 
  ON handpicked_presents(geo_id, created_at) 
  WHERE status = 'in_stock' AND user_id IS NULL;
```

## Configuration Tuning

### For Small Machines (< 2GB RAM):
```env
MAX_SIMILAR_USERS=20
MAX_RECOMMENDATION_ITEMS=100
CACHE_TTL_SIMILARITY=7200  # 2 hours
```

### For Medium Machines (2-8GB RAM):
```env
MAX_SIMILAR_USERS=50
MAX_RECOMMENDATION_ITEMS=200
CACHE_TTL_SIMILARITY=14400  # 4 hours
```

### For Production (8GB+ RAM):
```env
MAX_SIMILAR_USERS=100
MAX_RECOMMENDATION_ITEMS=500
CACHE_TTL_SIMILARITY=21600  # 6 hours
```

## Troubleshooting

### Service Won't Start
1. Check database connection string
2. Verify Redis is running
3. Check for port conflicts

### Slow Performance
1. Check database indexes
2. Monitor cache hit rates
3. Consider increasing cache TTLs
4. Reduce MAX_SIMILAR_USERS

### High Memory Usage
1. Reduce MAX_RECOMMENDATION_ITEMS
2. Decrease cache TTLs
3. Limit concurrent requests

### Recommendation Quality Issues
1. Check if enough user interaction data exists
2. Verify similarity algorithm parameters
3. Monitor algorithm distribution in responses

## Rollback Plan

If issues occur, quickly rollback:

1. **Disable new service in Rails**:
```ruby
# In Rails console or ENV
ENV['USE_RECOMMENDATION_SERVICE'] = 'false'
```

2. **Stop Python service**:
```bash
docker-compose stop recommendation_engine
```

3. **Re-enable Gorse** (if needed):
```bash
docker-compose up gorse
```

The system will automatically fall back to Rails-based recommendations.