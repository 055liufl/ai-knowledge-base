## ADDED Requirements

### Requirement: Network errors trigger automatic retry
The system SHALL retry LLM API calls when network-level failures occur, including connection errors, timeouts, and HTTP 5xx or 429 responses.

#### Scenario: Timeout recovery
- **WHEN** the LLM API request times out
- **THEN** the system SHALL wait using exponential backoff (base delay 1s, max delay 60s, jitter 0-0.5s) and retry, decrementing the remaining retry budget by 1

#### Scenario: Rate limit recovery
- **WHEN** the LLM API returns HTTP 429
- **THEN** the system SHALL parse the Retry-After header if present, wait min(retry_after, 60) seconds, or fall back to exponential backoff with base delay 1s, max delay 60s, jitter 0-0.5s

#### Scenario: Server error recovery
- **WHEN** the LLM API returns HTTP 5xx
- **THEN** the system SHALL retry with exponential backoff (base delay 1s, max delay 60s, jitter 0-0.5s)

#### Scenario: Non-retryable client errors
- **WHEN** the LLM API returns HTTP 400, 401, 403, or 404
- **THEN** the system SHALL fail immediately without retry and record the error as permanent

### Requirement: Content format errors trigger automatic retry
The system SHALL retry LLM API calls when the response body passes HTTP validation but fails content-level validation, consuming the same retry budget as network errors.

#### Scenario: Invalid JSON response
- **WHEN** the LLM returns HTTP 200 with content that cannot be parsed as valid JSON
- **THEN** the system SHALL retry the request if the remaining retry budget > 0

#### Scenario: Schema validation failure
- **WHEN** the LLM returns HTTP 200 with JSON missing required fields (summary, tags, tech_category, audience, score, key_insights)
- **THEN** the system SHALL retry if remaining budget > 0; if budget exhausted, record as permanent failure

#### Scenario: Empty content handling
- **WHEN** the LLM returns HTTP 200 with empty or null content
- **THEN** the system SHALL treat it as schema validation failure and retry

### Requirement: Retry budget is unified and observable
The system SHALL maintain a single retry budget per item, shared across network and content errors, with a default maximum of 3 retries.

#### Scenario: Shared budget consumption
- **GIVEN** max_retries=3
- **WHEN** a request fails with 503 (1 retry), then returns invalid JSON (1 retry), then succeeds
- **THEN** the response SHALL indicate retry_count=2 and remaining budget=1

#### Scenario: Budget exhaustion
- **GIVEN** max_retries=3
- **WHEN** all 4 attempts (initial + 3 retries) fail
- **THEN** the system SHALL record the failure as permanent and not retry this item in future runs unless explicitly forced

### Requirement: Permanent failures are tracked
The system SHALL record permanently failed items to prevent re-consumption of tokens on subsequent runs.

#### Scenario: Failed item tracking
- **WHEN** an item exhausts all retry attempts or encounters a non-retryable error
- **THEN** the system SHALL write a failure marker to knowledge/failed/{source}-{date}-{url_hash}.json containing the URL, error reason, timestamp, and cumulative retry count

#### Scenario: Skipping known failures on resume
- **WHEN** the pipeline encounters an item whose URL exists in either knowledge/articles/ or knowledge/failed/
- **THEN** the system SHALL skip analysis for that item

#### Scenario: Retry all failed items
- **WHEN** the pipeline runs with --retry-failed flag
- **THEN** the system SHALL scan knowledge/failed/ and re-analyze those URLs only, removing markers for successful retries

#### Scenario: Force retry specific URL
- **WHEN** the pipeline runs with --force-url=<url>
- **THEN** the system SHALL re-analyze that specific URL regardless of existing articles or failure markers

#### Scenario: Successful retry clears failure marker
- **GIVEN** an item has a failure marker in knowledge/failed/
- **WHEN** re-analysis succeeds
- **THEN** the system SHALL save to knowledge/articles/ and remove the failure marker

#### Scenario: Failed retry updates marker
- **GIVEN** an item has a failure marker
- **WHEN** re-analysis still fails after all retries
- **THEN** the system SHALL update the failure marker with new timestamp and cumulative retry count

### Requirement: Pipeline supports resume from interruption
The system SHALL skip already-analyzed items when re-running the pipeline.

#### Scenario: Duplicate URL detection
- **WHEN** the pipeline encounters an item whose URL already exists in knowledge/articles/
- **THEN** the system SHALL skip analysis for that item

#### Scenario: Fresh run behavior
- **WHEN** no matching article or failure marker exists for an item's URL
- **THEN** the system SHALL proceed with normal analysis

### Requirement: Single-item failure does not abort pipeline
The system SHALL isolate failures to individual items.

#### Scenario: Analysis failure handling
- **WHEN** an item fails permanently (budget exhausted or non-retryable error)
- **THEN** the system SHALL record the failure in statistics, write a failure marker, and continue to the next item

#### Scenario: Statistics accumulation
- **WHEN** the pipeline completes
- **THEN** the statistics SHALL include: collected, analyzed, saved, permanently_failed, skipped (duplicates + known failures), total_retries_consumed, average_retries_per_analyzed_item
