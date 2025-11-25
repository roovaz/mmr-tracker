# Stripe Profile Scraper

A web application that scrapes Stripe public profile pages (profile.stripe.com), stores data in PostgreSQL with user-based snapshots, and provides a web panel for input.

## Features

- **Duplicate Detection**: Same URL won't be processed twice if pending/processing
- **User-Based Storage**: Each username gets a unique ID
- **Timestamped Snapshots**: Multiple snapshots per user with timestamps
- **Background Processing**: URLs are processed asynchronously
- **Full Data Extraction**: Captures HTML, JS state, meta tags, and more
- **Real-time Stats**: Dashboard shows job status in real-time
- **PostgreSQL Storage**: Persistent, queryable database
- **Railway Ready**: One-click deployment with Docker

## Project Structure

```
stripe-profile-scraper/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI app
│   │   ├── database.py       # DB connection & models
│   │   ├── scraper.py        # Playwright scraper
│   │   ├── models.py         # Pydantic models
│   │   └── utils.py          # Helpers
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── docker-compose.yml
├── railway.toml
├── Procfile
└── README.md
```

## Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL
- Node.js (optional, for frontend development)

### Setup

1. Clone the repository:
```bash
git clone <repo-url>
cd stripe-profile-scraper
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
cd backend
pip install -r requirements.txt
playwright install chromium
```

4. Set up environment variables:
```bash
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/stripe_profiles"
```

5. Run the application:
```bash
python -m uvicorn app.main:app --reload
```

6. Open http://localhost:8000 in your browser

## Deployment to Railway

1. Go to [railway.app](https://railway.app)
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose your repository

5. **Add PostgreSQL Database:**
   - Click "New" -> "Database" -> "PostgreSQL"
   - Railway auto-creates `DATABASE_URL` environment variable

6. **Link Database to Service:**
   - Click on your web service
   - Go to "Variables"
   - Click "Add Variable Reference"
   - Select `DATABASE_URL` from the PostgreSQL service

7. **Deploy:**
   - Railway will automatically build and deploy
   - Wait for build to complete (Playwright install takes ~2-3 mins)

8. **Generate Domain:**
   - Click on your service
   - Go to "Settings" -> "Networking"
   - Click "Generate Domain"

## Usage

1. Open your deployed app URL
2. Paste Stripe profile URLs in the input box (one per line):
   ```
   https://profile.stripe.com/angelmatch/FL1A8oo4
   https://profile.stripe.com/another/XYZ123
   ```
3. Click "Submit for Scraping"
4. View jobs in the Jobs tab
5. View scraped data by user in the Users tab
6. Click any item to see full details

## API Endpoints

- `POST /api/scrape` - Submit URLs for scraping
- `GET /api/jobs` - List all scrape jobs
- `GET /api/jobs/{job_id}` - Get specific job details
- `GET /api/users` - List all users with snapshots
- `GET /api/users/{username}` - Get specific user and snapshots
- `GET /api/snapshots/{snapshot_id}` - Get specific snapshot details
- `GET /api/stats` - Get scraper statistics

## License

MIT
