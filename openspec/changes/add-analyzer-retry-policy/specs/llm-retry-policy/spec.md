## ADDED Requirements

### Requirement: Retry parameters are tuned for batch analysis
The LLM client SHALL use conservative retry parameters by default to prevent individual requests from blocking the pipeline for extended periods.

#### Scenario: Default retry parameters
- **WHEN** `chat_with_retry()` is called without explicit `timeout`, `max_retries`, or `base_delay` parameters
- **THEN** the default values SHALL be `timeout=30.0`, `max_retries=2`, and `base_delay=2.0`

#### Scenario: Worst-case retry duration is bounded
- **WHEN** a request encounters retryable failures on every attempt
- **THEN** the total time spent on that single item SHALL NOT exceed 120 seconds

### Requirement: Only specific errors trigger retry
The retry mechanism SHALL distinguish between retryable and non-retryable errors, and SHALL NOT retry client errors or business logic failures.

#### Scenario: Connect errors are retried
- **WHEN** an `httpx.ConnectTimeout` or `httpx.ConnectError` occurs
- **THEN** the request SHALL be retried up to the configured `max_retries`

#### Scenario: Read timeout has limited retries
- **WHEN** an `httpx.ReadTimeout` occurs
- **THEN** the request SHALL be retried at most once, regardless of the configured `max_retries`

#### Scenario: Server errors are retried
- **WHEN** the API responds with HTTP status code 429, 502, 503, or 504
- **THEN** the request SHALL be retried up to the configured `max_retries`

#### Scenario: Client errors are not retried
- **WHEN** the API responds with HTTP status code 400, 401, 403, 404, or 422
- **THEN** the error SHALL be raised immediately without retry

#### Scenario: Business errors are not retried
- **WHEN** the HTTP call succeeds but the response parsing fails (e.g., `json.JSONDecodeError`)
- **THEN** the error SHALL NOT trigger a retry at the HTTP layer

### Requirement: Provider-specific backoff policies
The system SHALL support different retry backoff parameters for each LLM provider, configured in the provider definition.

#### Scenario: DeepSeek uses faster backoff
- **WHEN** retrying a request to the DeepSeek provider
- **THEN** the initial backoff delay SHALL be 1.5 seconds

#### Scenario: OpenAI uses slower backoff
- **WHEN** retrying a request to the OpenAI provider
- **THEN** the initial backoff delay SHALL be 3.0 seconds

#### Scenario: Qwen uses moderate backoff
- **WHEN** retrying a request to the Qwen provider
- **THEN** the initial backoff delay SHALL be 2.0 seconds

#### Scenario: Missing provider policy falls back to defaults
- **WHEN** a provider configuration does not include a `retry_policy`
- **THEN** the system SHALL use the global default `base_delay` and `max_retries`

### Requirement: Rate limit responses are respected
The system SHALL honor the `Retry-After` header when present in HTTP 429 responses, using it instead of calculated exponential backoff.

#### Scenario: Retry-After header is present
- **WHEN** an HTTP 429 response includes a `Retry-After` header with value `10`
- **THEN** the system SHALL wait exactly 10 seconds before the next retry attempt

#### Scenario: Retry-After header is absent
- **WHEN** an HTTP 429 response does not include a `Retry-After` header
- **THEN** the system SHALL fall back to exponential backoff with jitter

### Requirement: Pipeline layer remains unchanged
The retry mechanism SHALL be transparent to the pipeline orchestration layer, requiring no modifications to `pipeline.py`.

#### Scenario: Pipeline calls quick_chat without changes
- **WHEN** `analyze_item()` calls `quick_chat()` with existing parameters
- **THEN** the call SHALL succeed with the new retry behavior applied automatically
