import hashlib
import re
from typing import Tuple, Optional


def hash_url(url: str) -> str:
    """Create a SHA256 hash of the URL for deduplication"""
    normalized = url.strip().lower().rstrip('/')
    return hashlib.sha256(normalized.encode()).hexdigest()


def parse_stripe_profile_url(url: str) -> Tuple[str, str]:
    """
    Parse a Stripe profile URL and return (username, profile_code)
    URL format: https://profile.stripe.com/{username}/{profile_code}
    """
    pattern = r'https?://profile\.stripe\.com/([^/]+)/([A-Za-z0-9]+)/?$'
    match = re.match(pattern, url.strip())
    if not match:
        raise ValueError(f"Invalid Stripe profile URL: {url}")
    return match.group(1), match.group(2)


def normalize_url(url: str) -> str:
    """Normalize URL for consistent storage"""
    url = url.strip()
    if not url.startswith('http'):
        url = 'https://' + url
    return url.rstrip('/')
