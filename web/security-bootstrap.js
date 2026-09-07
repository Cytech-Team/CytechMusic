/* Adds the logged-in Discord bearer token to same-origin dashboard API calls. */
(() => {
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
