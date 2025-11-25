import os
import sys
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from sqlalchemy.orm import selectinload

import logging

# Configure logging to stdout for Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Log startup info
logger.info(f"Starting application...")
logger.info(f"Python version: {sys.version}")
logger.info(f"PORT env: {os.getenv('PORT', 'not set')}")
logger.info(f"DATABASE_URL env: {'set' if os.getenv('DATABASE_URL') else 'NOT SET'}")

from app.database import init_db, get_session, User, Snapshot, ScrapeJob, async_session
from app.models import (
    ProfileURLInput,
    SnapshotResponse,
    UserWithSnapshots,
    ScrapeJobResponse,
    ScrapeJobsSubmitResponse
)
from app.scraper import get_scraper, scraper
from app.utils import hash_url, parse_stripe_profile_url, normalize_url
from app.auth import (
    Token, LoginRequest, create_access_token, verify_admin, get_current_admin,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

# Track if database is initialized
db_initialized = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_initialized
    # Startup
    logger.info("Lifespan startup beginning...")

    # Initialize database
    try:
        logger.info("Initializing database...")
        await init_db()
        db_initialized = True
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        db_initialized = False

    # Skip playwright install at startup - it's already installed in Docker
    logger.info("Playwright browsers should be pre-installed in Docker image")

    logger.info("Application startup complete")
    yield

    # Shutdown
    logger.info("Shutting down...")
    try:
        await scraper.stop()
    except Exception as e:
        logger.error(f"Error stopping scraper: {e}")


app = FastAPI(
    title="MMR Tracker - Stripe Revenue Leaderboard",
    description="Track and display public Stripe MRR/revenue data",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== Helper Functions ==============

def extract_revenue_from_snapshot(snapshot: Snapshot) -> Optional[float]:
    """Extract revenue/MRR value from snapshot data"""
    if not snapshot.all_data:
        return None

    all_data = snapshot.all_data

    # Try to find revenue in various places
    # Check framework_data (Next.js data)
    if 'framework_data' in all_data:
        framework = all_data['framework_data']
        if isinstance(framework, dict):
            # Navigate through Next.js props
            props = framework.get('props', {})
            page_props = props.get('pageProps', {})

            # Look for revenue/mrr/volume fields
            for key in ['revenue', 'mrr', 'volume', 'total', 'amount', 'gross_volume']:
                if key in page_props:
                    val = page_props[key]
                    if isinstance(val, (int, float)):
                        return float(val)
                    if isinstance(val, str):
                        # Try to parse currency string
                        cleaned = re.sub(r'[^\d.]', '', val)
                        if cleaned:
                            try:
                                return float(cleaned)
                            except:
                                pass

    # Check main_text for revenue patterns
    if 'main_text' in all_data:
        text = all_data['main_text']
        # Look for patterns like "$1,234,567" or "1.2M"
        patterns = [
            r'\$[\d,]+(?:\.\d{2})?',  # $1,234.56
            r'[\d,]+(?:\.\d{2})?\s*(?:USD|usd)',  # 1234.56 USD
            r'\$[\d.]+[KMB]',  # $1.2M
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                # Take the largest value found
                values = []
                for match in matches:
                    cleaned = re.sub(r'[^\d.KMB]', '', match.upper())
                    multiplier = 1
                    if 'K' in cleaned:
                        multiplier = 1000
                        cleaned = cleaned.replace('K', '')
                    elif 'M' in cleaned:
                        multiplier = 1000000
                        cleaned = cleaned.replace('M', '')
                    elif 'B' in cleaned:
                        multiplier = 1000000000
                        cleaned = cleaned.replace('B', '')
                    try:
                        values.append(float(cleaned) * multiplier)
                    except:
                        pass
                if values:
                    return max(values)

    return None


def format_leaderboard_entry(user: User, snapshot: Snapshot) -> Dict[str, Any]:
    """Format a user/snapshot for the leaderboard"""
    all_data = snapshot.all_data or {}

    # Extract display name
    display_name = snapshot.display_name
    if not display_name and 'page_title' in all_data:
        display_name = all_data['page_title']
    if not display_name:
        display_name = user.username

    # Extract logo/image
    logo_url = snapshot.logo_url
    if not logo_url and 'images' in all_data and all_data['images']:
        # Try to find a logo image
        for img in all_data['images']:
            if 'logo' in img.get('alt', '').lower() or 'logo' in img.get('src', '').lower():
                logo_url = img['src']
                break
        if not logo_url and all_data['images']:
            logo_url = all_data['images'][0].get('src')

    # Extract revenue
    revenue = extract_revenue_from_snapshot(snapshot)

    # Extract description
    description = snapshot.description
    if not description and 'meta_tags' in all_data:
        description = all_data['meta_tags'].get('og:description') or all_data['meta_tags'].get('description')

    return {
        'id': str(snapshot.id),
        'user_id': str(user.id),
        'username': user.username,
        'display_name': display_name,
        'description': description,
        'logo_url': logo_url,
        'website_url': snapshot.website_url,
        'profile_url': snapshot.full_url,
        'revenue': revenue,
        'revenue_formatted': f"${revenue:,.0f}" if revenue else None,
        'country': snapshot.country,
        'industry': snapshot.industry,
        'scraped_at': snapshot.scraped_at.isoformat() if snapshot.scraped_at else None,
        'all_data': all_data,
    }


# ============== Public API Endpoints ==============

@app.get("/api/leaderboard")
async def get_leaderboard(
    limit: int = Query(100, le=500),
    session: AsyncSession = Depends(get_session)
):
    """Get public leaderboard data - sorted by revenue"""
    # Get all users with their latest snapshot
    result = await session.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    leaderboard = []
    for user in users:
        # Get latest successful snapshot for this user
        snapshot_result = await session.execute(
            select(Snapshot)
            .where(and_(Snapshot.user_id == user.id, Snapshot.status == 'success'))
            .order_by(desc(Snapshot.scraped_at))
            .limit(1)
        )
        snapshot = snapshot_result.scalar_one_or_none()

        if snapshot:
            entry = format_leaderboard_entry(user, snapshot)
            leaderboard.append(entry)

    # Sort by revenue (None values at the end)
    leaderboard.sort(key=lambda x: (x['revenue'] is None, -(x['revenue'] or 0)))

    return {
        'count': len(leaderboard),
        'entries': leaderboard[:limit]
    }


@app.get("/api/profile/{username}")
async def get_public_profile(username: str, session: AsyncSession = Depends(get_session)):
    """Get public profile data for a specific user"""
    result = await session.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Get latest successful snapshot
    snapshot_result = await session.execute(
        select(Snapshot)
        .where(and_(Snapshot.user_id == user.id, Snapshot.status == 'success'))
        .order_by(desc(Snapshot.scraped_at))
        .limit(1)
    )
    snapshot = snapshot_result.scalar_one_or_none()

    if not snapshot:
        raise HTTPException(status_code=404, detail="No data available for this profile")

    return format_leaderboard_entry(user, snapshot)


# ============== Admin Auth Endpoints ==============

@app.post("/api/admin/login", response_model=Token)
async def admin_login(login_data: LoginRequest):
    """Admin login endpoint"""
    if not verify_admin(login_data.username, login_data.password):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )

    access_token = create_access_token(
        data={"sub": login_data.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return Token(access_token=access_token, token_type="bearer")


@app.get("/api/admin/verify")
async def verify_admin_token(admin: str = Depends(get_current_admin)):
    """Verify admin token is valid"""
    return {"status": "ok", "username": admin}


# ============== Admin Protected Endpoints ==============

@app.post("/api/admin/scrape", response_model=ScrapeJobsSubmitResponse)
async def submit_scrape_jobs(
    input_data: ProfileURLInput,
    background_tasks: BackgroundTasks,
    admin: str = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Submit one or more Stripe profile URLs for scraping (Admin only)"""
    jobs_created = 0
    jobs_skipped = 0
    job_ids = []

    for url in input_data.urls:
        url = normalize_url(url)
        url_hash = hash_url(url)

        # Check for existing pending/processing job with same URL
        existing = await session.execute(
            select(ScrapeJob).where(
                and_(
                    ScrapeJob.url_hash == url_hash,
                    ScrapeJob.status.in_(['pending', 'processing'])
                )
            )
        )
        existing_job = existing.scalar_one_or_none()

        if existing_job:
            jobs_skipped += 1
            job_ids.append(existing_job.id)
            continue

        # Create new job
        job = ScrapeJob(
            url=url,
            url_hash=url_hash,
            status='pending'
        )
        session.add(job)
        await session.flush()

        job_ids.append(job.id)
        jobs_created += 1

        # Add background task
        background_tasks.add_task(process_scrape_job, job.id)

    await session.commit()

    return ScrapeJobsSubmitResponse(
        message=f"Submitted {jobs_created} new jobs, {jobs_skipped} duplicates skipped",
        jobs_created=jobs_created,
        jobs_skipped=jobs_skipped,
        job_ids=job_ids
    )


@app.get("/api/admin/jobs", response_model=List[ScrapeJobResponse])
async def get_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, le=200),
    admin: str = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Get all scrape jobs (Admin only)"""
    query = select(ScrapeJob).order_by(ScrapeJob.created_at.desc()).limit(limit)

    if status:
        query = query.where(ScrapeJob.status == status)

    result = await session.execute(query)
    jobs = result.scalars().all()

    return [ScrapeJobResponse.model_validate(job) for job in jobs]


@app.get("/api/admin/jobs/{job_id}", response_model=ScrapeJobResponse)
async def get_job(
    job_id: UUID,
    admin: str = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Get a specific scrape job (Admin only)"""
    result = await session.execute(
        select(ScrapeJob).where(ScrapeJob.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return ScrapeJobResponse.model_validate(job)


@app.get("/api/admin/users", response_model=List[UserWithSnapshots])
async def get_users(
    limit: int = Query(50, le=200),
    admin: str = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Get all users with their snapshots (Admin only)"""
    result = await session.execute(
        select(User).order_by(User.created_at.desc()).limit(limit)
    )
    users = result.scalars().all()

    response = []
    for user in users:
        # Get snapshots for this user
        snapshots_result = await session.execute(
            select(Snapshot)
            .where(Snapshot.user_id == user.id)
            .order_by(Snapshot.scraped_at.desc())
        )
        snapshots = snapshots_result.scalars().all()

        user_data = {
            'id': user.id,
            'username': user.username,
            'created_at': user.created_at,
            'snapshots': [
                SnapshotResponse(
                    **{k: v for k, v in snap.__dict__.items() if not k.startswith('_')},
                    username=user.username
                )
                for snap in snapshots
            ]
        }
        response.append(UserWithSnapshots(**user_data))

    return response


@app.get("/api/admin/stats")
async def get_admin_stats(
    admin: str = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Get scraper statistics (Admin only)"""
    from sqlalchemy import func

    try:
        users_count = await session.execute(select(func.count(User.id)))
        snapshots_count = await session.execute(select(func.count(Snapshot.id)))
        jobs_pending = await session.execute(
            select(func.count(ScrapeJob.id)).where(ScrapeJob.status == 'pending')
        )
        jobs_completed = await session.execute(
            select(func.count(ScrapeJob.id)).where(ScrapeJob.status == 'completed')
        )
        jobs_failed = await session.execute(
            select(func.count(ScrapeJob.id)).where(ScrapeJob.status == 'failed')
        )

        return {
            "status": "ok",
            "db_initialized": db_initialized,
            "total_users": users_count.scalar(),
            "total_snapshots": snapshots_count.scalar(),
            "jobs_pending": jobs_pending.scalar(),
            "jobs_completed": jobs_completed.scalar(),
            "jobs_failed": jobs_failed.scalar()
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {
            "status": "error",
            "db_initialized": db_initialized,
            "error": str(e),
            "total_users": 0,
            "total_snapshots": 0,
            "jobs_pending": 0,
            "jobs_completed": 0,
            "jobs_failed": 0
        }


# ============== Background Tasks ==============

async def process_scrape_job(job_id: UUID):
    """Background task to process a single scrape job"""
    async with async_session() as session:
        # Get the job
        result = await session.execute(
            select(ScrapeJob).where(ScrapeJob.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job or job.status != 'pending':
            return

        # Update status to processing
        job.status = 'processing'
        await session.commit()

        try:
            # Parse URL
            username, profile_code = parse_stripe_profile_url(job.url)

            # Get or create user
            user_result = await session.execute(
                select(User).where(User.username == username)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                user = User(username=username)
                session.add(user)
                await session.flush()

            # Scrape the profile
            scraper_instance = await get_scraper()
            profile_data = await scraper_instance.scrape_profile(job.url)

            # Create snapshot
            snapshot = Snapshot(
                user_id=user.id,
                profile_code=profile_code,
                full_url=job.url,
                display_name=profile_data.display_name,
                business_name=profile_data.business_name,
                description=profile_data.description,
                website_url=profile_data.website_url,
                logo_url=profile_data.logo_url,
                country=profile_data.country,
                industry=profile_data.industry,
                business_type=profile_data.business_type,
                metrics=profile_data.metrics,
                all_data=profile_data.all_data,
                raw_html=profile_data.raw_html,
                status='success'
            )
            session.add(snapshot)
            await session.flush()

            # Update job
            job.status = 'completed'
            job.completed_at = datetime.utcnow()
            job.snapshot_id = snapshot.id

            await session.commit()
            logger.info(f"Successfully scraped {job.url}")

        except Exception as e:
            logger.error(f"Error processing job {job_id}: {str(e)}")
            job.status = 'failed'
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            await session.commit()


# ============== Health Check ==============

@app.get("/api/health")
async def health_check():
    """Simple health check that doesn't require database"""
    return {"status": "ok", "db_initialized": db_initialized}


# ============== Static Files & Frontend ==============

frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'frontend')
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def serve_homepage():
        return FileResponse(os.path.join(frontend_path, 'index.html'))

    @app.get("/admin")
    async def serve_admin_login():
        return FileResponse(os.path.join(frontend_path, 'admin.html'))

    @app.get("/admin/dashboard")
    async def serve_admin_dashboard():
        return FileResponse(os.path.join(frontend_path, 'admin-dashboard.html'))

else:
    @app.get("/")
    async def root():
        return {"message": "MMR Tracker API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
