from aiolimiter import AsyncLimiter

# The limiter is process-global so every LLMService instance shares the same budget.
LLM_RATE_LIMITER = AsyncLimiter(max_rate=60, time_period=60)
