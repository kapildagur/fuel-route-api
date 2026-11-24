# Security

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

## Reporting a vulnerability

Report a vulnerability privately through the repository's "Report a vulnerability" button under the Security tab (GitHub private vulnerability reporting). Do not open a public issue. Include the affected version, the steps to reproduce, and the impact you expect. You can expect an acknowledgement within five working days.

## Security considerations

| Area | Design |
| --- | --- |
| Secrets | The OpenRouteService key and the Django secret key come from the environment or a git-ignored `.env`. The key travels in the `Authorization` header, never in a URL, and is never logged. The server refuses to start without a secret key outside debug mode. |
| Input | Query parameters are validated before any lookup: each location is at most 200 characters, coordinates must be in range, and numbers have bounds. Input never builds a file path or a SQL string, and cache keys from input are bounded in number and hashed. |
| Abuse and cost | Anonymous clients are limited to `FUELROUTE_RATE_LIMIT` requests (60 a minute by default), which also protects the provider quota. Repeated questions are served from the cache. |
| Errors | Responses never contain stack traces or provider credentials. An unexpected failure returns a generic 500 and is logged in full. |
| Personal data | Locations can be street addresses, so they are not logged. Nothing is stored per request. |
| Browser | Every response carries a Content Security Policy, `X-Frame-Options: DENY` and `nosniff`. The map page runs one inline script with a per-response nonce, loads Leaflet from unpkg with a pinned integrity hash, and builds its content with `textContent`, so station names cannot inject markup. |
| Container | The image runs as an unprivileged user, and `compose.yaml` mounts its file system read-only. |
| Authentication | The API has no authentication: it reads public price data and returns no personal data. Put it behind an authenticating gateway before exposing it where the provider quota matters. |
