# MySanta Recommendation Engine Tests

Comprehensive unit tests for the RecommendationServiceV2 engine.

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                     # Test fixtures and configuration
├── test_popular_items.py           # Popular items API tests
├── test_personalized_recommendations.py  # Personalized API tests
├── test_helpers.py                 # Helper methods and utilities tests
└── README.md                       # This file
```

## Test Coverage

### 1. Popular Items Tests (`test_popular_items.py`)
- ✅ Cache hit scenarios
- ✅ Cache miss scenarios  
- ✅ Filter application (price, category, etc.)
- ✅ Pagination functionality
- ✅ Empty result handling
- ✅ Error handling and fallbacks
- ✅ Cache key generation
- ✅ Database query validation

### 2. Personalized Recommendations Tests (`test_personalized_recommendations.py`)
- ✅ Cache hit scenarios
- ✅ New user fallback (0 interactions)
- ✅ Collaborative filtering (3+ interactions)
- ✅ Content-based filtering (1-2 interactions)
- ✅ Filter application with personalized data
- ✅ Pagination with personalized results
- ✅ Error handling
- ✅ User profile retrieval
- ✅ User likes exclusion

### 3. Helper Methods Tests (`test_helpers.py`)
- ✅ Cache key generation (both APIs)
- ✅ Filter application logic
- ✅ Collaborative filtering helpers
- ✅ Content-based filtering helpers
- ✅ Fallback recommendation logic
- ✅ Database query construction
- ✅ Error handling in filters

## Key Test Features

### Mocking Strategy
- **Database mocking**: All database calls are mocked using `AsyncMock`
- **Cache mocking**: Redis cache operations are mocked
- **Isolated testing**: Each test is completely isolated with fresh mocks

### Test Fixtures
- `mock_db`: Complete database manager mock
- `sample_popular_request`: Standard popular items request
- `sample_personalized_request`: Standard personalized request
- `sample_user_profile`: User profile with preferences
- `sample_popular_items`: Mock popular items data
- `sample_user_likes`: Mock user interaction data

### Test Categories
- **Unit tests**: Fast, isolated tests of individual methods
- **Algorithm tests**: Tests for recommendation logic
- **Integration tests**: End-to-end API behavior tests

## Running Tests

### Run All Tests
```bash
# Using pytest directly
pytest tests/ -v

# Using the test runner
python run_tests.py
```

### Run Specific Test Files
```bash
# Popular items tests only
python run_tests.py popular_items

# Personalized recommendations tests only  
python run_tests.py personalized_recommendations

# Helper methods tests only
python run_tests.py helpers
```

### Run Individual Tests
```bash
# Run specific test method
pytest tests/test_popular_items.py::TestPopularItems::test_get_popular_items_cache_hit -v

# Run specific test class
pytest tests/test_popular_items.py::TestPopularItems -v
```

## Test Scenarios Covered

### Popular Items API
1. **Cache Hit**: Fast response from cache
2. **Cache Miss**: Database query + cache population
3. **Demographic Filtering**: Gender, age, category matching
4. **Price Filtering**: Min/max price constraints
5. **Pagination**: Page-based result splitting
6. **Empty Results**: Graceful handling of no results
7. **Database Errors**: Fallback to empty results

### Personalized Recommendations API
1. **New Users**: Fallback to popular items
2. **Content-Based**: Profile-based recommendations  
3. **Collaborative**: Similar user recommendations
4. **User Exclusions**: Already liked items filtered out
5. **Profile Building**: User preference extraction
6. **Algorithm Selection**: Smart algorithm switching based on interaction count

### Utility Functions
1. **Cache Keys**: Consistent key generation
2. **Filters**: Real-time filtering logic
3. **Queries**: Database query construction
4. **Error Handling**: Graceful degradation

## Performance Considerations

### Test Speed
- All tests use mocks for fast execution
- No real database or network calls
- Tests complete in <5 seconds

### Coverage Areas
- ✅ Core business logic
- ✅ Error scenarios
- ✅ Edge cases (empty data, None values)
- ✅ Algorithm switching logic
- ✅ Cache behavior
- ✅ Pagination edge cases

## Adding New Tests

### For New Features
1. Add test fixtures to `conftest.py` if needed
2. Create new test file or add to existing file
3. Follow naming convention: `test_feature_name.py`
4. Use `@pytest.mark.unit` for unit tests

### Test Template
```python
@pytest.mark.unit
async def test_new_feature(self, mock_db, sample_request):
    """Test description"""
    # Setup
    mock_db.cache_get.return_value = None
    mock_db.execute_query.return_value = expected_data
    
    # Execute
    with patch('app.recommendation_service_v2.db', mock_db):
        result = await RecommendationServiceV2.new_method(sample_request)
    
    # Assert
    assert result.expected_property == expected_value
    mock_db.execute_query.assert_called_once()
```

## Quality Gates

All tests must pass before deployment:
- ✅ No test failures
- ✅ All edge cases covered  
- ✅ Error scenarios tested
- ✅ Mock usage validated
- ✅ Performance within bounds

These tests ensure the recommendation engine is reliable, performant, and handles all user scenarios gracefully.