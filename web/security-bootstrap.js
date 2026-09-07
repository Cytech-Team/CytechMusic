/* Runtime identity + bearer-token bootstrap for Community dashboard pages. */
(() => {
    const LEGACY_CYORI_CLIENT_ID = '1469606905948405833';

    // Load deployment identity before script.js/settings.js evaluate their constants.
    if (!window.CYTECHMUSIC_CLIENT_ID) {
        try {
            const xhr = new XMLHttpRequest();
            xhr.open('GET', '/api/proxy?action=runtime_config', false);
            xhr.send(null);
            if (xhr.status >= 200 && xhr.status < 300) {
                const runtime = JSON.parse(xhr.responseText || '{}');
                if (runtime.client_id) {
                    window.CYTECHMUSIC_CLIENT_ID = String(runtime.client_id);
                }
            }
        } catch (_) {
            // Fail closed: login/invite code will refuse to use an unknown client ID.
        }
    }

    function rewriteLegacyAppUrl(rawUrl) {
        if (!rawUrl || typeof rawUrl !== 'string' || !rawUrl.includes(LEGACY_CYORI_CLIENT_ID)) {
            return rawUrl;
        }
        const clientId = String(window.CYTECHMUSIC_CLIENT_ID || '');
        if (!/^\d{15,22}$/.test(clientId)) {
            return null;
        }
        return rawUrl.split(LEGACY_CYORI_CLIENT_ID).join(clientId);
    }

    // Old Community HTML/JS still contains some Cyori invite/vote links. Never allow
    // those stale links to send a Community deployer's users to the production Cyori app.
    const nativeOpen = window.open.bind(window);
    window.open = function securedOpen(url, ...args) {
        const safeUrl = rewriteLegacyAppUrl(String(url || ''));
        if (!safeUrl) {
            alert('Discord Client ID is not configured for this Community deployment.');
            return null;
        }
        return nativeOpen(safeUrl, ...args);
    };

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('a[href]').forEach((anchor) => {
            const rewritten = rewriteLegacyAppUrl(anchor.href);
            if (rewritten === null) {
                anchor.removeAttribute('href');
                anchor.setAttribute('aria-disabled', 'true');
            } else if (rewritten !== anchor.href) {
                anchor.href = rewritten;
            }
        });
    }, { once: true });

    const nativeFetch = window.fetch.bind(window);

    window.fetch = function securedFetch(input, init = {}) {
        let url;
        try {
            url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
        } catch (_) {
            return nativeFetch(input, init);
        }

        if (url.origin === window.location.origin && url.pathname.startsWith('/api/')) {
            const headers = new Headers(
                init.headers || (typeof Request !== 'undefined' && input instanceof Request ? input.headers : undefined)
            );
            if (window.accessToken && !headers.has('Authorization')) {
                headers.set('Authorization', `Bearer ${window.accessToken}`);
            }
            if (typeof init.body === 'string' && init.body.length && !headers.has('Content-Type')) {
                headers.set('Content-Type', 'application/json');
            }
            init = { ...init, headers };
        }

        return nativeFetch(input, init);
    };
})();
