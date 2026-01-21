// WhosHere JavaScript utilities

// Toast notification system
const Toast = {
    container: null,

    init() {
        this.container = document.getElementById('toast-container');
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.id = 'toast-container';
            this.container.className = 'fixed bottom-4 right-4 z-50 space-y-2';
            document.body.appendChild(this.container);
        }
    },

    show(message, type = 'info', duration = 3000) {
        if (!this.container) this.init();

        const toast = document.createElement('div');
        const bgColor = {
            success: 'bg-green-500',
            error: 'bg-red-500',
            warning: 'bg-yellow-500',
            info: 'bg-blue-500'
        }[type] || 'bg-gray-700';

        toast.className = `${bgColor} text-white px-4 py-3 rounded-lg shadow-lg transform transition-all duration-300 translate-y-2 opacity-0`;
        toast.textContent = message;

        this.container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => {
            toast.classList.remove('translate-y-2', 'opacity-0');
        });

        // Auto remove
        setTimeout(() => {
            toast.classList.add('translate-y-2', 'opacity-0');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },

    success(message) { this.show(message, 'success'); },
    error(message) { this.show(message, 'error'); },
    warning(message) { this.show(message, 'warning'); },
    info(message) { this.show(message, 'info'); }
};

// Initialize toast on load
document.addEventListener('DOMContentLoaded', () => Toast.init());

// HTMX event handlers
document.body.addEventListener('htmx:afterRequest', function(evt) {
    const xhr = evt.detail.xhr;

    // Show toast for API responses
    if (evt.detail.pathInfo.requestPath.startsWith('/api/')) {
        try {
            const response = JSON.parse(xhr.responseText);
            if (response.message) {
                if (response.success === false) {
                    Toast.error(response.message);
                } else {
                    Toast.success(response.message);
                }
            }
        } catch (e) {
            // Not JSON, ignore
        }
    }
});

// Handle HTMX errors
document.body.addEventListener('htmx:responseError', function(evt) {
    Toast.error('An error occurred. Please try again.');
});

// Keyboard shortcuts
document.addEventListener('keydown', function(evt) {
    // Ctrl+K or Cmd+K for search focus
    if ((evt.ctrlKey || evt.metaKey) && evt.key === 'k') {
        evt.preventDefault();
        const searchInput = document.getElementById('search');
        if (searchInput) {
            searchInput.focus();
            searchInput.select();
        }
    }
});

// Auto-refresh present devices every 30 seconds
let refreshInterval = null;

function startAutoRefresh() {
    if (refreshInterval) return;
    refreshInterval = setInterval(() => {
        const presentDevices = document.getElementById('present-devices');
        if (presentDevices) {
            htmx.trigger(presentDevices, 'refresh');
        }
    }, 30000);
}

function stopAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
}

// Start auto-refresh when page is visible
document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
        stopAutoRefresh();
    } else {
        startAutoRefresh();
    }
});

// Initialize
document.addEventListener('DOMContentLoaded', startAutoRefresh);

// Utility: Format relative time
function formatRelativeTime(minutes) {
    if (minutes < 0) return 'Unknown';
    if (minutes === 0) return 'Just now';
    if (minutes === 1) return '1 minute ago';
    if (minutes < 60) return `${minutes} minutes ago`;
    const hours = Math.floor(minutes / 60);
    if (hours === 1) return '1 hour ago';
    if (hours < 24) return `${hours} hours ago`;
    const days = Math.floor(hours / 24);
    if (days === 1) return '1 day ago';
    return `${days} days ago`;
}

// Export utilities for use in templates
window.WhosHere = {
    Toast,
    formatRelativeTime,
    startAutoRefresh,
    stopAutoRefresh
};
