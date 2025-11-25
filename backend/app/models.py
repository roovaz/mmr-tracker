from pydantic import BaseModel, HttpUrl, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
import re


class ProfileURLInput(BaseModel):
    urls: List[str]

    @field_validator('urls')
    @classmethod
    def validate_urls(cls, v):
        pattern = r'^https?://profile\.stripe\.com/([^/]+)/([A-Za-z0-9]+)/?$'
        validated = []
        for url in v:
            url = url.strip()
            if not re.match(pattern, url):
                raise ValueError(f"Invalid Stripe profile URL format: {url}")
            validated.append(url)
        return validated


class ScrapedProfile(BaseModel):
    username: str
    profile_code: str
    full_url: str
    display_name: Optional[str] = None
    business_name: Optional[str] = None
    description: Optional[str] = None
    website_url: Optional[str] = None
    logo_url: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    business_type: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    all_data: Optional[Dict[str, Any]] = None
    raw_html: Optional[str] = None


class SnapshotResponse(BaseModel):
    id: UUID
    user_id: UUID
    username: str
    profile_code: str
    full_url: str
    scraped_at: datetime
    display_name: Optional[str]
    business_name: Optional[str]
    description: Optional[str]
    website_url: Optional[str]
    logo_url: Optional[str]
    country: Optional[str]
    industry: Optional[str]
    business_type: Optional[str]
    metrics: Optional[Dict[str, Any]]
    all_data: Optional[Dict[str, Any]]
    status: str
    error_message: Optional[str]

    class Config:
        from_attributes = True


class UserWithSnapshots(BaseModel):
    id: UUID
    username: str
    created_at: datetime
    snapshots: List[SnapshotResponse]

    class Config:
        from_attributes = True


class ScrapeJobResponse(BaseModel):
    id: UUID
    url: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime]
    snapshot_id: Optional[UUID]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class ScrapeJobsSubmitResponse(BaseModel):
    message: str
    jobs_created: int
    jobs_skipped: int  # Already processing duplicates
    job_ids: List[UUID]
