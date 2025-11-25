import os
import asyncio
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

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

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up...")
    await init_db()
    logger.info("Database initialized")

    # Install playwright browsers
    logger.info("Installing Playwright browsers...")
    proc = await asyncio.create_subprocess_shell(
        "playwright install chromium",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        logger.info("Playwright browsers installed")
    else:
        logger.warning(f"Playwright install warning: {stderr.decode()}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await scraper.stop()


app = FastAPI(
    title="Stripe Profile Scraper",
    description="Scrape and store Stripe public profile data",
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


# Background task to process scraping
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


@app.post("/api/scrape", response_model=ScrapeJobsSubmitResponse)
async def submit_scrape_jobs(
    input_data: ProfileURLInput,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """Submit one or more Stripe profile URLs for scraping"""
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


@app.get("/api/jobs", response_model=List[ScrapeJobResponse])
async def get_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session)
):
    """Get all scrape jobs"""
    query = select(ScrapeJob).order_by(ScrapeJob.created_at.desc()).limit(limit)

    if status:
        query = query.where(ScrapeJob.status == status)

    result = await session.execute(query)
    jobs = result.scalars().all()

    return [ScrapeJobResponse.model_validate(job) for job in jobs]


@app.get("/api/jobs/{job_id}", response_model=ScrapeJobResponse)
async def get_job(job_id: UUID, session: AsyncSession = Depends(get_session)):
    """Get a specific scrape job"""
    result = await session.execute(
        select(ScrapeJob).where(ScrapeJob.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return ScrapeJobResponse.model_validate(job)


@app.get("/api/users", response_model=List[UserWithSnapshots])
async def get_users(
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session)
):
    """Get all users with their snapshots"""
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


@app.get("/api/users/{username}", response_model=UserWithSnapshots)
async def get_user(username: str, session: AsyncSession = Depends(get_session)):
    """Get a specific user and their snapshots"""
    result = await session.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    snapshots_result = await session.execute(
        select(Snapshot)
        .where(Snapshot.user_id == user.id)
        .order_by(Snapshot.scraped_at.desc())
    )
    snapshots = snapshots_result.scalars().all()

    return UserWithSnapshots(
        id=user.id,
        username=user.username,
        created_at=user.created_at,
        snapshots=[
            SnapshotResponse(
                **{k: v for k, v in snap.__dict__.items() if not k.startswith('_')},
                username=user.username
            )
            for snap in snapshots
        ]
    )


@app.get("/api/snapshots/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(snapshot_id: UUID, session: AsyncSession = Depends(get_session)):
    """Get a specific snapshot"""
    result = await session.execute(
        select(Snapshot, User.username)
        .join(User, Snapshot.user_id == User.id)
        .where(Snapshot.id == snapshot_id)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    snapshot, username = row
    return SnapshotResponse(
        **{k: v for k, v in snapshot.__dict__.items() if not k.startswith('_')},
        username=username
    )


@app.get("/api/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Get scraper statistics"""
    from sqlalchemy import func

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
        "total_users": users_count.scalar(),
        "total_snapshots": snapshots_count.scalar(),
        "jobs_pending": jobs_pending.scalar(),
        "jobs_completed": jobs_completed.scalar(),
        "jobs_failed": jobs_failed.scalar()
    }


# Serve static files
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'frontend')
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(os.path.join(frontend_path, 'index.html'))
else:
    @app.get("/")
    async def root():
        return {"message": "Stripe Profile Scraper API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
