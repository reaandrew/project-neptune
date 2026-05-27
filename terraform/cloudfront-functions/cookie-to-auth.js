// BFF CloudFront Function (viewer-request).
//
// Reads the `auth_token` cookie issued by reaandrew/ara on passkey
// login and rewrites it into an `Authorization: Bearer <jwt>` header
// before the request is forwarded to api.projectneptune.* . This is the
// entire BFF — there is no Lambda. The API Gateway Lambda authorizer
// is what actually validates the JWT.
//
// We also strip the Cookie header from the upstream request so the
// JWT does not show up in API Gateway access logs.

function handler(event) {
    var request = event.request;
    var cookies = request.cookies || {};
    var token = cookies.auth_token && cookies.auth_token.value;
    if (token) {
        request.headers['authorization'] = { value: 'Bearer ' + token };
    }
    // Don't forward the raw cookie to the origin.
    delete request.cookies;
    if (request.headers.cookie) {
        delete request.headers.cookie;
    }
    return request;
}
