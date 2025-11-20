Application architecture:
![Architecture](docs/architecture.png)

Set environment variables in `.env` file:

## Configuration Keys

| Key                                 | Description                                                                                            | Required | Example                                                            |
|-------------------------------------|--------------------------------------------------------------------------------------------------------|:--------:|--------------------------------------------------------------------|
| `PORT_API_HOST`                     | TEMPLATE                                                                                               |    ✅     | `8000`                                                             |
| `PORT_API_CONTAINER`                | TEMPLATE                                                                                               |    ✅     | `8000`                                                             |
| `DB_NAME`                           | TEMPLATE                                                                                               |    ✅     | `someDBname`                                                       |
| `DB_USER`                           | TEMPLATE                                                                                               |    ✅     | `someDBuser`                                                       |
| `DB_PASSWORD`                       | TEMPLATE                                                                                               |    ✅     | `someDBpassword`                                                   |
| `DB_HOST`                           | for usage inside services. Corresponds with docker-compose names. Use `localhost` in case of local run |    ✅     | `database`                                                         |
| `CHAT_BOT_API_KEY`                  | TEMPLATE                                                                                               |    ✅     | `someAPIkeyForChatbot`                                             |
| `BOT_TOKEN`                         | TEMPLATE                                                                                               |    ✅     | `5421398104:1234123421341234123412342134` (put key from botfather) |
| `DEBUG`                             | can be empty                                                                                           |    ✅     |                                                                    |
| `API_HOST`                          | for usage inside services. Corresponds with docker-compose names. Use `localhost` in case of local run |    ✅     | `http://api:8000`                                                  |
| `DB_MODE`                           | TEMPLATE                                                                                               |    ✅     | `prod`                                                             |
| `CELERY_BROKER_URL`                 | TEMPLATE                                                                                               |    ✅     | `redis://redis:6379/0` or `redis://localhost:6379/0` for local run |
| `CELERY_RESULT_BACKEND`             | TEMPLATE                                                                                               |    ✅     | `django-db`         |
| `REACT_APP_API_HOST`                | TEMPLATE                                                                                               |    ✅     | `http://localhost:8000`                                            |
| `PORT_FRONTEND`                     | TEMPLATE                                                                                               |    ✅     | `3001`                                                             |
| `API_ADMIN_USERNAME`                | TEMPLATE                                                                                               |    ✅     | `admin`                                                            |
| `API_ADMIN_PASSWORD`                | TEMPLATE                                                                                               |    ✅     | `someadminpassword`                                                |
| `ALLOWED_HOSTS`                     | comaseparated hosts                                                                                    |    ✅     | `localhost,api`                                                    |
| `HOSTNAME_BACKEND`                  | TEMPLATE                                                                                               |    ✅     | `your_domain_backend.com`                                          | |
| `HOSTNAME_FRONTEND`                 | TEMPLATE                                                                                               |    ✅     | `your_domain_frontend.com`                                         |
| `PORT_ENTRY_NGINX`                  | TEMPLATE                                                                                               |    ✅     | `8000`                                                             |
| `PORT_INTERNAL_NGINX`               | TEMPLATE                                                                                               |    ✅     | `443`                                                              |
| `AUTOMATIC_ACCOUNT_REFRESH_MINUTES` | Run monoaccout refresh every <VALUE> minutes, default=`45`                                             |          | `45`                                                               |
| `IS_CI_TEST`                        | Indicates if it is ci test. Skips some celery related jobs, default=`false`                            |          | ``                                                                 |
| `APPLY_MONOBANK_WEBHOOKS`           | Indicates if monobank webhook should be set for each card, default=`false`                             |          | ``                                                                 |
| `SHOULD_AUTO_FETCH_TRANSACTIONS`    | Flag to fetch account data periodically, default=`false`                                               |          | ``                                                                 |
| `IS_WORKER`                         | Flag to differentiate backend from celery worker, default=`false`                                      |          | ``                                                                 |
| `WEBHOOK_URL`                       | Webhook URL for monobank to send new transactions                                                      |    ✅     | ``                                                                 |
| `LOGS_BOT_TOKEN`                    | Token for chat bot logs                                                                                |    ✅     | ``                                                                 |
| `LOGS_CHAT_ID`                      | Admin who receive telegram logs                                                                        |    ✅     | ``                                                                 |
| `ENV`                               | Stage of application (dev, prod, local...)                                                             |    ✅     | ``                                                                 |"
| `GOOGLE_API_KEY`                    | Google api key for LLM interractions (https://aistudio.google.com/apikey)                              |    ✅     | ``                                                                 |"
| `SENTRY_DSN_API`                    | Sentry DSN for Django API error tracking                                                               |          | `https://...@sentry.io/...`                                        |
| `SENTRY_DSN_CHATBOT`                | Sentry DSN for Chatbot error tracking                                                                  |          | `https://...@sentry.io/...`                                        |
## Additional Information

`pip install -r requirements.txt`

Run docker compose:

* All in docker with nginx:

`docker-compose -f docker-compose.yaml up --build`

* Local run in docker:

`docker-compose -f docker-compose-local.yaml up --build`

* Backend development:

`docker-compose -f docker-compose-local.yaml up redis worker celery_beat chatbot database web --build`

    python manage.py makemigrations
    python manage.py migrate
    python manage.py loaddata categories.json
    python manage.py loaddata categories_mso.json
    python manage.py loaddata currency.json
    python manage.py create_api_superuser

Local backend config for CELERY:

    celery --app=django_celery_example beat -l INFO
    celery --app=django_celery_example worker --loglevel=info

    export CELERY_BROKER_URL=redis://localhost:6379/0 && CELERY_RESULT_BACKEND=redis://localhost:6379  && celery --app=api worker -l INFO
    export CELERY_BROKER_URL=redis://localhost:6379/0 && CELERY_RESULT_BACKEND=redis://localhost:6379  && celery --app=api beat -l INFO
    python manage.py runserver

* Frontend development

  `docker-compose -f docker-compose-local.yaml up redis api worker celery_beat chatbot database --build`

NOTE: if you have troubles with `entrypoint.sh` - you can use command below (with services you need):

`docker-compose -f docker-compose-local.yaml -f docker-compose-local-alternative-api.yaml up --build`

## Error Tracking (Sentry)

Sentry integration is available for both the Django API and Chatbot services.

1.  **Setup**:
    *   Create projects in Sentry for "Django API" and "Chatbot".
    *   Get the DSN for each project.
2.  **Configuration**:
    *   Add `SENTRY_DSN_API` and `SENTRY_DSN_CHATBOT` to your `.env` file.
    *   See `SENTRY_SETUP.md` for detailed instructions.
