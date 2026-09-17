"""B: security contract only. No authentication bypass or fake user."""
ACCESS_TTL_SECONDS = 900
REFRESH_TTL_SECONDS = 604800
ACCESS_COOKIE = "__Host-fm_access"
REFRESH_COOKIE = "__Host-fm_refresh"
CSRF_COOKIE = "__Host-fm_csrf"
# Implement JWT/sid/token_version, signed session-bound CSRF and Origin checks
# before registering ANY protected or modifying business endpoint.

