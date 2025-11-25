import os
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, DateTime, JSON, Text, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/stripe_profiles")

# Handle Railway's postgres:// vs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


class User(Base):
    """Unique user/business identified by their profile username"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False, index=True)  # e.g., "angelmatch"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Snapshot(Base):
    """A point-in-time snapshot of a user's profile data"""
    __tablename__ = "snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    profile_code = Column(String(50), nullable=False)  # e.g., "FL1A8oo4"
    full_url = Column(Text, nullable=False)
    scraped_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Scraped data
    display_name = Column(String(500))
    business_name = Column(String(500))
    description = Column(Text)
    website_url = Column(Text)
    logo_url = Column(Text)
    country = Column(String(100))
    industry = Column(String(255))
    business_type = Column(String(255))

    # Metrics (if publicly shared)
    metrics = Column(JSON)  # Store any charts/metrics data

    # Raw HTML for future parsing
    raw_html = Column(Text)

    # All extracted data as JSON
    all_data = Column(JSON)

    # Scrape status
    status = Column(String(50), default="pending")  # pending, success, failed
    error_message = Column(Text)

    __table_args__ = (
        UniqueConstraint('user_id', 'profile_code', 'scraped_at', name='unique_snapshot'),
        Index('idx_snapshot_lookup', 'user_id', 'scraped_at'),
    )


class ScrapeJob(Base):
    """Track scraping jobs for deduplication"""
    __tablename__ = "scrape_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(Text, nullable=False)
    url_hash = Column(String(64), nullable=False, index=True)  # SHA256 hash for dedup
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    snapshot_id = Column(UUID(as_uuid=True), ForeignKey("snapshots.id"))
    error_message = Column(Text)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
