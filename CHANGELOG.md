# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — unreleased

Initial release of the Python SDK, at feature parity with the Go and Node SDKs.

### Added

- `ConsoleClient` (sync) and `AsyncConsoleClient` (async) with an identical API.
- OAuth2 `client_credentials` authentication via `private_key_jwt` (Ed25519),
  with transparent minting, caching and re-mint on `401`.
- `client.otp.send(...)` — phone normalization, locale/template/variables,
  automatic idempotency keys, and transparent retries with backoff + jitter.
- Typed error taxonomy: `LinkError`, `ConfigError`, `ValidationError`,
  `ConnectionError`, `APIError`, `AuthenticationError`, `IdempotencyError`,
  `RateLimitError`.
- Full type hints shipped with a `py.typed` marker (PEP 561).
