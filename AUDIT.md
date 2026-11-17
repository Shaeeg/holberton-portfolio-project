# Portfolio readiness audit

Baseline: 16 passing integration tests. Flask combines setup, persistence and routes in one factory. SQLite serializes writes, webhook secrets guard normalized intake, and Telegram long polling shares ingestion with the webhook. The browser polls with ETags and connection backoff. CI tests the Docker build and health endpoint.

| Priority | Finding | Action |
| --- | --- | --- |
| P0 | Operator reads and writes were public with the production entry point. | Require operator credentials, use a separately selected loopback demo mode, and reject cross-origin browser writes. |
| P1 | Failed Telegram command replies could delay subsequent messages. Inline assets made strict CSP impractical. | Isolate reply failures, extract static assets, and add browser security headers. |
| P1 | Dashboard controls lacked clear hierarchy and a focused ticket creation flow. | Add responsive navigation, status accents, focus styling and a native creation dialog with feedback. |
| P2 | The application factory still owns most persistence and route logic. The dashboard reloads an entire ticket list when the representation changes. | Keep SQLite and polling for the demo. Split persistence and paginate or adopt a change feed if ticket volume warrants it. |
| P2 | No physical-provider WhatsApp or email test. No separate operator roles. | Document adapter requirements and shared operator access. Validate providers once credentials and accounts are available. |
| P3 | Outbound status updates would require durable delivery tracking. | Keep private on-demand status as the supported workflow. Consider an outbox for future notifications. |
