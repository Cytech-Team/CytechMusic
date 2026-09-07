export async function onRequest(context) {
    const response = await context.next();
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.toLowerCase().includes("text/html")) {
        return response;
    }

    return new HTMLRewriter()
        .on("head", {
            element(element) {
                element.append('<script src="/security-bootstrap.js"></script>', { html: true });
            },
        })
        .transform(response);
}
