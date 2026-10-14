# EasyDown API client for Python

A small synchronous client for applications that import a **public, single-post
media URL** into a backend. It submits that URL to EasyDown, validates the response,
and gives your application normalized media or the separate platform data.
It does not download files, scrape profiles, or bypass access controls.

This is a first-party client maintained for EasyDown. The Python library is open
source under ISC; the hosted developer API is a **paid, credit-based service**.
API access requires an account, a Bearer token, and available credits. New
registrations receive 10 trial credits. The free browser downloader is a separate
product. Parse costs depend on the platform and processing outcome; do not assume
every failure is free or that retrying cannot incur another charge.

The [EasyDown API reference](https://easydown.org/docs/en/api) explains supported
platforms, authentication, current billing rules, and response fields.

## Install and make one request

Requires Python 3.10 or newer, with no third-party runtime dependencies.

```sh
python -m pip install easydown-api-client
```

Keep the token in a server environment variable. Do not place it in frontend code,
notebooks shared with others, committed examples, or logs. Set `PUBLIC_POST_URL`
to a supported public single-post URL that you are authorized to process.

```python
import os
from easydown_api_client import EasyDownClient, EasyDownError

client = EasyDownClient(os.environ["EASYDOWN_API_TOKEN"], timeout=60)

try:
    media = client.parse(os.environ["PUBLIC_POST_URL"])
except EasyDownError as error:
    # These fields omit the token, submitted URL and raw response body.
    print(error.kind, error.http_status, error.code)
else:
    print(media["platform"], len(media["images"]), len(media["videos"]))
```

`parse()` calls `POST /api/v1/parse` with a JSON `url` field and returns the
normalized object in `data` directly. `duration` is passed through without
assigning a unit. Images preserve response order. Multiple video entries may
represent renditions of one clip; their count is not a post count or credit count.

## Keep platform-specific data separate

Use a platform endpoint when your application also needs the upstream-shaped
fields. This returns a different envelope from the unified endpoint:

```python
result = client.parse_platform("tiktok", os.environ["PUBLIC_POST_URL"])
media = result["media"]
platform_data = result["platformData"]
platform_data_version = result["platformDataVersion"]
```

The client leaves `platformData` intact and verifies that the normalized media
matches the requested platform. Your code should check the version and optional
fields before reading platform-specific values.

Accepted endpoint names are `tiktok`, `douyin`, `toutiao`, `youtube`, `twitter`,
`instagram`, `threads`, `xiaohongshu`, `bilibili`, `kuaishou`, and `weibo`.
X uses `twitter`; RedNote uses `xiaohongshu`. Support for a platform does not promise
that every post is available. Private posts, account/profile crawling and live
streams are outside this client's documented use case.

## Failure handling and credentials

- `kind="http"`: an unsuccessful HTTP response, including redirects, 401 or 429.
- `kind="api"`: an API error envelope. A recognized documented API error `code`
  is available when it is returned in an otherwise successful HTTP response.
- `kind="invalid_response"`: malformed JSON, an oversized response, or missing
  documented media fields.
- `kind="timeout"` or `"network"`: transport failure. Neither establishes whether
  the server processed or charged a request.

There are **no automatic retries**. Decide retry policy in your application after
checking request outcome and the current billing reference. Responses larger
than 8 MiB are rejected. The default 60-second timeout applies to socket
operations; it is not a total wall-clock deadline or server-side guarantee.

The default transport only sends the Bearer token to the fixed HTTPS API host,
does not follow redirects, and does not attach cookies. Returned media URLs and
any required media headers are data for your application; treat them as sensitive
and potentially short-lived. This client never fetches those URLs automatically.
Do not expose a server token through client-side apps or untrusted proxy code.

## Offline testing

```sh
python -m unittest -v test_client
```

Tests use mock transports and mocked HTTP responses, not a real API token or paid
request. They cover request shape, both response envelopes, carousel order,
redirect refusal, malformed media, status errors, timeout behavior, and safe
error messages. A custom `transport(request, timeout)` can return `HttpResponse`
for your own offline tests; it receives the Authorization header, so use only
trusted code. No network request happens on import or construction.

Version 0.1.0 is an initial release. Code and documentation were prepared with AI
assistance and checked against the published API contract. Offline tests are not
a live-service reliability claim.
