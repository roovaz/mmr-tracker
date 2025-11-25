// API Base URL
const API_BASE = window.location.origin;

// DOM Elements
const urlsInput = document.getElementById('urls-input');
const submitBtn = document.getElementById('submit-btn');
const clearBtn = document.getElementById('clear-btn');
const submitResult = document.getElementById('submit-result');
const jobsFilter = document.getElementById('jobs-filter');
const refreshJobsBtn = document.getElementById('refresh-jobs');
const jobsList = document.getElementById('jobs-list');
const userSearch = document.getElementById('user-search');
const refreshUsersBtn = document.getElementById('refresh-users');
const usersList = document.getElementById('users-list');
const modal = document.getElementById('detail-modal');
const modalBody = document.getElementById('modal-body');
const closeBtn = document.querySelector('.close-btn');

// Tab handling
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

        tab.classList.add('active');
        document.getElementById(`${tab.dataset.tab}-tab`).classList.add('active');
    });
});

// Load stats
async function loadStats() {
    try {
        const response = await fetch(`${API_BASE}/api/stats`);
        const data = await response.json();

        document.getElementById('total-users').textContent = data.total_users;
        document.getElementById('total-snapshots').textContent = data.total_snapshots;
        document.getElementById('jobs-pending').textContent = data.jobs_pending;
        document.getElementById('jobs-completed').textContent = data.jobs_completed;
        document.getElementById('jobs-failed').textContent = data.jobs_failed;
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Submit URLs for scraping
submitBtn.addEventListener('click', async () => {
    const text = urlsInput.value.trim();
    if (!text) {
        showResult('Please enter at least one URL', 'error');
        return;
    }

    const urls = text.split('\n')
        .map(url => url.trim())
        .filter(url => url.length > 0);

    if (urls.length === 0) {
        showResult('Please enter valid URLs', 'error');
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting...';

    try {
        const response = await fetch(`${API_BASE}/api/scrape`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls })
        });

        const data = await response.json();

        if (response.ok) {
            showResult(data.message, 'success');
            urlsInput.value = '';
            loadJobs();
            loadStats();
        } else {
            showResult(data.detail || 'Error submitting URLs', 'error');
        }
    } catch (error) {
        showResult(`Error: ${error.message}`, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit for Scraping';
    }
});

clearBtn.addEventListener('click', () => {
    urlsInput.value = '';
    submitResult.className = 'result-message';
    submitResult.style.display = 'none';
});

function showResult(message, type) {
    submitResult.textContent = message;
    submitResult.className = `result-message ${type}`;
}

// Load Jobs
async function loadJobs() {
    const status = jobsFilter.value;
    const url = status
        ? `${API_BASE}/api/jobs?status=${status}&limit=100`
        : `${API_BASE}/api/jobs?limit=100`;

    try {
        const response = await fetch(url);
        const jobs = await response.json();

        if (jobs.length === 0) {
            jobsList.innerHTML = '<p class="loading">No jobs found</p>';
            return;
        }

        jobsList.innerHTML = jobs.map(job => `
            <div class="list-item" onclick="showJobDetail('${job.id}')">
                <div class="list-item-header">
                    <span class="list-item-title">${truncateUrl(job.url)}</span>
                    <span class="status-badge status-${job.status}">${job.status}</span>
                </div>
                <div class="list-item-meta">
                    <span>${formatDate(job.created_at)}</span>
                    ${job.error_message ? `<span>${truncate(job.error_message, 50)}</span>` : ''}
                </div>
            </div>
        `).join('');
    } catch (error) {
        jobsList.innerHTML = `<p class="loading">Error loading jobs: ${error.message}</p>`;
    }
}

// Load Users
async function loadUsers() {
    try {
        const response = await fetch(`${API_BASE}/api/users?limit=100`);
        const users = await response.json();

        if (users.length === 0) {
            usersList.innerHTML = '<p class="loading">No users found</p>';
            return;
        }

        const searchTerm = userSearch.value.toLowerCase();
        const filteredUsers = users.filter(u =>
            u.username.toLowerCase().includes(searchTerm)
        );

        usersList.innerHTML = filteredUsers.map(user => `
            <div class="user-card">
                <div class="user-card-header" onclick="toggleSnapshots('${user.username}')">
                    <span class="user-name">@${user.username}</span>
                    <span class="snapshot-count">${user.snapshots.length} snapshots</span>
                </div>
                <div class="snapshots-list" id="snapshots-${user.username}">
                    ${user.snapshots.map(snap => `
                        <div class="snapshot-item" onclick="event.stopPropagation(); showSnapshotDetail('${snap.id}')">
                            <div class="list-item-header">
                                <span>${snap.profile_code}</span>
                                <span class="status-badge status-${snap.status}">${snap.status}</span>
                            </div>
                            <div class="list-item-meta">
                                <span>${formatDate(snap.scraped_at)}</span>
                                ${snap.display_name ? `<span>${snap.display_name}</span>` : ''}
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `).join('');
    } catch (error) {
        usersList.innerHTML = `<p class="loading">Error loading users: ${error.message}</p>`;
    }
}

function toggleSnapshots(username) {
    const el = document.getElementById(`snapshots-${username}`);
    el.classList.toggle('expanded');
}

// Show Job Detail
async function showJobDetail(jobId) {
    try {
        const response = await fetch(`${API_BASE}/api/jobs/${jobId}`);
        const job = await response.json();

        modalBody.innerHTML = `
            <h2>Job Details</h2>
            <div class="detail-section">
                <h3>URL</h3>
                <div class="detail-value">${job.url}</div>
            </div>
            <div class="detail-grid">
                <div class="detail-section">
                    <h3>Status</h3>
                    <div class="detail-value">
                        <span class="status-badge status-${job.status}">${job.status}</span>
                    </div>
                </div>
                <div class="detail-section">
                    <h3>Created At</h3>
                    <div class="detail-value">${formatDate(job.created_at)}</div>
                </div>
            </div>
            ${job.completed_at ? `
            <div class="detail-section">
                <h3>Completed At</h3>
                <div class="detail-value">${formatDate(job.completed_at)}</div>
            </div>
            ` : ''}
            ${job.error_message ? `
            <div class="detail-section">
                <h3>Error</h3>
                <div class="detail-value" style="color: var(--danger);">${job.error_message}</div>
            </div>
            ` : ''}
            ${job.snapshot_id ? `
            <div class="detail-section">
                <button class="primary-btn" onclick="showSnapshotDetail('${job.snapshot_id}')">
                    View Snapshot Data
                </button>
            </div>
            ` : ''}
        `;

        modal.classList.add('active');
    } catch (error) {
        alert(`Error loading job: ${error.message}`);
    }
}

// Show Snapshot Detail
async function showSnapshotDetail(snapshotId) {
    try {
        const response = await fetch(`${API_BASE}/api/snapshots/${snapshotId}`);
        const snap = await response.json();

        modalBody.innerHTML = `
            <h2>Snapshot Details</h2>

            <div class="detail-section">
                <h3>User</h3>
                <div class="detail-value">@${snap.username}</div>
            </div>

            <div class="detail-grid">
                <div class="detail-section">
                    <h3>Profile Code</h3>
                    <div class="detail-value">${snap.profile_code}</div>
                </div>
                <div class="detail-section">
                    <h3>Scraped At</h3>
                    <div class="detail-value">${formatDate(snap.scraped_at)}</div>
                </div>
            </div>

            <div class="detail-section">
                <h3>Full URL</h3>
                <div class="detail-value">
                    <a href="${snap.full_url}" target="_blank" style="color: var(--primary);">${snap.full_url}</a>
                </div>
            </div>

            ${snap.display_name ? `
            <div class="detail-section">
                <h3>Display Name</h3>
                <div class="detail-value">${snap.display_name}</div>
            </div>
            ` : ''}

            ${snap.business_name ? `
            <div class="detail-section">
                <h3>Business Name</h3>
                <div class="detail-value">${snap.business_name}</div>
            </div>
            ` : ''}

            ${snap.description ? `
            <div class="detail-section">
                <h3>Description</h3>
                <div class="detail-value">${snap.description}</div>
            </div>
            ` : ''}

            ${snap.website_url ? `
            <div class="detail-section">
                <h3>Website</h3>
                <div class="detail-value">
                    <a href="${snap.website_url}" target="_blank" style="color: var(--primary);">${snap.website_url}</a>
                </div>
            </div>
            ` : ''}

            <div class="detail-grid">
                ${snap.country ? `
                <div class="detail-section">
                    <h3>Country</h3>
                    <div class="detail-value">${snap.country}</div>
                </div>
                ` : ''}

                ${snap.industry ? `
                <div class="detail-section">
                    <h3>Industry</h3>
                    <div class="detail-value">${snap.industry}</div>
                </div>
                ` : ''}
            </div>

            ${snap.logo_url ? `
            <div class="detail-section">
                <h3>Logo</h3>
                <div class="detail-value">
                    <img src="${snap.logo_url}" alt="Logo" style="max-width: 200px; max-height: 100px;">
                </div>
            </div>
            ` : ''}

            ${snap.metrics ? `
            <div class="detail-section">
                <h3>Metrics</h3>
                <div class="detail-value json">${JSON.stringify(snap.metrics, null, 2)}</div>
            </div>
            ` : ''}

            ${snap.all_data ? `
            <div class="detail-section">
                <h3>All Extracted Data</h3>
                <div class="detail-value json">${JSON.stringify(snap.all_data, null, 2)}</div>
            </div>
            ` : ''}
        `;

        modal.classList.add('active');
    } catch (error) {
        alert(`Error loading snapshot: ${error.message}`);
    }
}

// Modal close
closeBtn.addEventListener('click', () => modal.classList.remove('active'));
modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.classList.remove('active');
});

// Event listeners
jobsFilter.addEventListener('change', loadJobs);
refreshJobsBtn.addEventListener('click', () => { loadJobs(); loadStats(); });
refreshUsersBtn.addEventListener('click', loadUsers);
userSearch.addEventListener('input', loadUsers);

// Helpers
function truncateUrl(url) {
    const match = url.match(/profile\.stripe\.com\/([^\/]+)\/([^\/]+)/);
    if (match) return `@${match[1]}/${match[2]}`;
    return url.length > 50 ? url.substring(0, 50) + '...' : url;
}

function truncate(str, len) {
    return str.length > len ? str.substring(0, len) + '...' : str;
}

function formatDate(dateStr) {
    return new Date(dateStr).toLocaleString();
}

// Initial load
loadStats();
loadJobs();
loadUsers();

// Auto-refresh every 10 seconds
setInterval(() => {
    loadStats();
    loadJobs();
}, 10000);
