// Public Leaderboard JavaScript

const API_BASE = window.location.origin;

// DOM Elements
const leaderboardBody = document.getElementById('leaderboard-body');
const heroTotalProfiles = document.getElementById('hero-total-profiles');
const heroTotalRevenue = document.getElementById('hero-total-revenue');
const modal = document.getElementById('profile-modal');
const modalBody = document.getElementById('profile-modal-body');
const closeBtn = document.querySelector('.close-btn');

// Load leaderboard data
async function loadLeaderboard() {
    try {
        const response = await fetch(`${API_BASE}/api/leaderboard?limit=100`);
        const data = await response.json();

        // Update hero stats
        heroTotalProfiles.textContent = data.count;

        // Calculate total revenue
        const totalRevenue = data.entries.reduce((sum, entry) => sum + (entry.revenue || 0), 0);
        heroTotalRevenue.textContent = formatCurrency(totalRevenue);

        // Render leaderboard
        if (data.entries.length === 0) {
            leaderboardBody.innerHTML = `
                <tr>
                    <td colspan="4" class="loading-row">No profiles tracked yet. Check back soon!</td>
                </tr>
            `;
            return;
        }

        leaderboardBody.innerHTML = data.entries.map((entry, index) => {
            const rank = index + 1;
            const rankClass = rank <= 3 ? `rank-${rank}` : 'rank-default';

            return `
                <tr onclick="showProfile('${entry.username}')">
                    <td class="rank-col">
                        <span class="rank-badge ${rankClass}">${rank}</span>
                    </td>
                    <td class="profile-col">
                        <div class="profile-cell">
                            <div class="profile-avatar">
                                ${entry.logo_url
                                    ? `<img src="${entry.logo_url}" alt="${entry.display_name}" onerror="this.parentElement.innerHTML='<div class=\\'profile-avatar-placeholder\\'>${getInitials(entry.display_name)}</div>'">`
                                    : `<div class="profile-avatar-placeholder">${getInitials(entry.display_name)}</div>`
                                }
                            </div>
                            <div class="profile-info">
                                <div class="profile-name">${escapeHtml(entry.display_name || entry.username)}</div>
                                <div class="profile-username">@${escapeHtml(entry.username)}</div>
                                ${entry.description ? `<div class="profile-description">${escapeHtml(truncate(entry.description, 60))}</div>` : ''}
                            </div>
                        </div>
                    </td>
                    <td class="revenue-col">
                        ${entry.revenue_formatted
                            ? `<span class="revenue-value">${entry.revenue_formatted}</span>`
                            : `<span class="revenue-unknown">-</span>`
                        }
                    </td>
                    <td class="details-col">
                        <button class="view-btn" onclick="event.stopPropagation(); showProfile('${entry.username}')">View</button>
                    </td>
                </tr>
            `;
        }).join('');

    } catch (error) {
        console.error('Error loading leaderboard:', error);
        leaderboardBody.innerHTML = `
            <tr>
                <td colspan="4" class="loading-row">Error loading leaderboard. Please try again.</td>
            </tr>
        `;
    }
}

// Show profile modal
async function showProfile(username) {
    try {
        const response = await fetch(`${API_BASE}/api/profile/${username}`);
        const profile = await response.json();

        modalBody.innerHTML = `
            <div class="profile-modal-header">
                <div class="profile-modal-avatar">
                    ${profile.logo_url
                        ? `<img src="${profile.logo_url}" alt="${profile.display_name}" onerror="this.style.display='none'">`
                        : `<div class="profile-avatar-placeholder" style="width:80px;height:80px;font-size:2rem;">${getInitials(profile.display_name)}</div>`
                    }
                </div>
                <div class="profile-modal-info" style="flex:1;">
                    <h2>${escapeHtml(profile.display_name || profile.username)}</h2>
                    <div class="username">@${escapeHtml(profile.username)}</div>
                </div>
                <div class="profile-modal-revenue">
                    <div class="value">${profile.revenue_formatted || '-'}</div>
                    <div class="label">Revenue</div>
                </div>
            </div>

            ${profile.description ? `
            <div class="detail-section">
                <h3>Description</h3>
                <p style="color: var(--text-secondary);">${escapeHtml(profile.description)}</p>
            </div>
            ` : ''}

            <div class="profile-modal-details">
                ${profile.website_url ? `
                <div class="profile-detail-item">
                    <div class="label">Website</div>
                    <div class="value"><a href="${profile.website_url}" target="_blank" rel="noopener">${truncate(profile.website_url, 40)}</a></div>
                </div>
                ` : ''}

                <div class="profile-detail-item">
                    <div class="label">Stripe Profile</div>
                    <div class="value"><a href="${profile.profile_url}" target="_blank" rel="noopener">View on Stripe</a></div>
                </div>

                ${profile.country ? `
                <div class="profile-detail-item">
                    <div class="label">Country</div>
                    <div class="value">${escapeHtml(profile.country)}</div>
                </div>
                ` : ''}

                ${profile.industry ? `
                <div class="profile-detail-item">
                    <div class="label">Industry</div>
                    <div class="value">${escapeHtml(profile.industry)}</div>
                </div>
                ` : ''}

                ${profile.scraped_at ? `
                <div class="profile-detail-item">
                    <div class="label">Last Updated</div>
                    <div class="value">${formatDate(profile.scraped_at)}</div>
                </div>
                ` : ''}
            </div>
        `;

        modal.classList.add('active');
    } catch (error) {
        console.error('Error loading profile:', error);
        alert('Error loading profile details');
    }
}

// Close modal
closeBtn.addEventListener('click', () => modal.classList.remove('active'));
modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.classList.remove('active');
});

// Escape key closes modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') modal.classList.remove('active');
});

// Helper functions
function formatCurrency(value) {
    if (value >= 1000000000) {
        return '$' + (value / 1000000000).toFixed(1) + 'B';
    }
    if (value >= 1000000) {
        return '$' + (value / 1000000).toFixed(1) + 'M';
    }
    if (value >= 1000) {
        return '$' + (value / 1000).toFixed(0) + 'K';
    }
    return '$' + value.toFixed(0);
}

function getInitials(name) {
    if (!name) return '?';
    const parts = name.split(/[\s-_]+/);
    if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
}

function truncate(str, len) {
    if (!str) return '';
    return str.length > len ? str.substring(0, len) + '...' : str;
}

function formatDate(dateStr) {
    return new Date(dateStr).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initial load
loadLeaderboard();

// Refresh every 60 seconds
setInterval(loadLeaderboard, 60000);
