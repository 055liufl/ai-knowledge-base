## ADDED Requirements

### Requirement: Retry decorator wraps chat method
The system SHALL provide a `with_retry` decorator that wraps `chat()` to automatically retry on transient failures.

#### Scenario: Decorator is applied
- **WHEN** `chat()` is called through the `with_retry` decorator
- **THEN** transient failures SHALL trigger automatic retries according to the configured policy

### Requirement: Only specific exceptions trigger retry
The retry mechanism SHALL distinguish between retryable and non-retryable exceptions.

#### Scenario: Network timeout is retried
- **WHEN** an `httpx.TimeoutException` or `APITimeoutError` occurs
- **THEN** the request SHALL be retried up to `max_attempts - 1` times

#### Scenario: Connection error is retried
- **WHEN** an `httpx.ConnectError` or `APIConnectionError` occurs
- **THEN** the request SHALL be retried up to `max_attempts - 1` times

#### Scenario: Rate limit is retried
- **WHEN** a `RateLimitError` occurs
- **THEN** the request SHALL be retried up to `max_attempts - 1` times

#### Scenario: Server error is retried
- **WHEN** an `APIStatusError` with `status_code >= 500` occurs
- **THEN** the request SHALL be retried up to `max_attempts - 1` times

#### Scenario: JSON decode error is not retried
- **WHEN** a `json.JSONDecodeError` occurs after a successful HTTP response
- **THEN** the error SHALL be raised immediately without retry

#### Scenario: Content errors are not retried
- **WHEN** a `KeyError` or `ValueError` occurs during response processing
- **THEN** the error SHALL be raised immediately without retry

### Requirement: Exponential backoff with jitter
The retry mechanism SHALL use exponential backoff with capped delay and multiplicative jitter.

#### Scenario: Backoff calculation
- **WHEN** the first retry is attempted
- **THEN** the delay SHALL be `base_delay * 2^(attempt-1) * jitter` where `jitter` is in range `[1.0, 1.5)`

#### Scenario: Max delay cap
- **WHEN** the calculated delay exceeds `max_delay`
- **THEN** the actual delay SHALL be capped at `max_delay`

#### Scenario: Default retry parameters
- **WHEN** `with_retry` is used without explicit configuration
- **THEN** the default values SHALL be `max_attempts=3`, `base_delay=1.0`, `max_delay=20.0`

### Requirement: Cost tracking for all attempts
The system SHALL track API costs for every attempt, including failed retries.

#### Scenario: Failed attempt cost
- **WHEN** an API call fails before receiving a response
- **THEN** the cost tracker SHALL record `prompt_tokens=0`, `completion_tokens=0`

#### Scenario: Successful attempt cost
- **WHEN** an API call succeeds
- **THEN** the cost tracker SHALL record the actual `usage.prompt_tokens` and `usage.completion_tokens` from the response

### Requirement: Graceful degradation on exhaustion
When all retry attempts are exhausted, the system SHALL gracefully degrade instead of crashing the pipeline.

#### Scenario: Degraded fallback
- **WHEN** `max_attempts` are exhausted and the request still fails
- **THEN** the item SHALL use `raw_content[:200]` as the summary
- **AND** the item's `status` field SHALL be set to `"degraded"`
- **AND** the pipeline SHALL continue processing remaining items
