/* Runtime identity + bearer-token bootstrap for Community dashboard pages. */
(() => {
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
