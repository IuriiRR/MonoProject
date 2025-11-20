# Sentry Integration Setup

This document outlines the steps to integrate Sentry for error tracking in the Chatbot and Django API projects.

## Prerequisites

1.  **Sentry Account**: You need a Sentry account. Sign up at [sentry.io](https://sentry.io/).
2.  **Projects**: Create two projects in Sentry:
    *   One for the **Django API** (Platform: Django).
    *   One for the **Chatbot** (Platform: Python).
3.  **DSN (Data Source Name)**: Get the DSN for each project. This is the unique key used to send errors to Sentry.

## Configuration

### 1. Environment Variables

You need to add the Sentry DSNs to your environment variables. We have provided a template in `sentry_secrets.env.example`.

**Action**:
1.  Copy the contents of `sentry_secrets.env.example` to your `.env` file (or create a new one if you are using a different method for secrets).
2.  Replace the placeholder values with your actual Sentry DSNs.

```bash
# Example .env additions
SENTRY_DSN_API=https://examplePublicKey@o0.ingest.sentry.io/0
SENTRY_DSN_CHATBOT=https://examplePublicKey@o0.ingest.sentry.io/0
```

### 2. Django API Integration

The `django_api` project has been configured to automatically initialize Sentry if `SENTRY_DSN_API` is present in the environment variables.

*   **File**: `django_api/api/api/settings.py`
*   **Library**: `sentry-sdk`

### 3. Chatbot Integration

The `chatbot` project has been configured to automatically initialize Sentry if `SENTRY_DSN_CHATBOT` is present in the environment variables.

*   **File**: `chatbot/src/bot.py`
*   **Library**: `sentry-sdk`

## Deployment

1.  **Rebuild Docker Images**: Since we added a new dependency (`sentry-sdk`), you need to rebuild your Docker images.

    ```bash
    docker-compose build
    ```

2.  **Restart Services**:

    ```bash
    docker-compose up -d
    ```

## Verification

To verify the installation:
1.  Trigger an error in the application (e.g., by temporarily adding a `1 / 0` line or using a test command).
2.  Check your Sentry dashboard to see if the error appears.
