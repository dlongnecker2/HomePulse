# HomePulse Health Insights foundation

Status: Gate 4 is complete. Google Health uses the three minimum read-only
scopes, the Health Insights dashboard stores privacy-minimal daily summaries in
an isolated database, and relationship output remains suppressed until at least
14 complete, non-current overlap days are available.
## HomePulse architecture audit

1. `router_monitor.py` creates `Application`. `Application.__init__` constructs
   configuration, repositories, managers/services, scheduler, diagnostics, and
   plugin registries. `Application.initialize` initializes databases/services
   and registers jobs before `Dashboard` starts Flask.
2. Routes are nested functions registered with `@self.app.route` inside
   `Dashboard.register_routes`; the application currently does not use Flask
   blueprints.
3. Feature modules generally expose manager or service classes. Features with
   history use dedicated repository/database classes and model dataclasses.
4. `Scheduler` stores interval and daily jobs in memory. `Application` registers
   them centrally and runs the scheduler loop every ten seconds.
5. `Config` loads ignored `config.json`, recursively fills
   `config.defaults.json`, and delegates merge, validation, backup, and atomic
   replacement to `ConfigBackupService`.
6. Existing databases are dedicated SQLite files with `sqlite3.Row`, explicit
   commits, indexes, and feature-specific initialization.
7. `WeightProgressService.view_model` is the Weight Progress presentation/API
   payload. It contains summary cards, latest measurement, chart points,
   composition points, range metadata, tracking details, and configuration.
8. Weight Progress reads `weight_kg`, direct or derived body-fat percentage,
   derived muscle percentage (`muscle_mass_kg / weight_kg`), derived hydration
   percentage (`hydration_kg / weight_kg`), and reconciled visceral-fat index
   history through `WeightProgressDatabase`. Its current delayed Home Assistant
   update reconciliation and original measurement dates remain unchanged.
9. The frontend loads Chart.js from jsDelivr in `base.html`, embeds a JSON view
   model in a page-level `window` value, and uses feature-specific JavaScript.
10. Tests use `unittest`, temporary directories/databases, synthetic payloads,
    and `unittest.mock`.
11. Health Insights records a configured IANA timezone and uses `tzdata` for
    DST-safe conversion. Deployments should configure the timezone that matches
    the HomePulse host.
12. The repository previously had no user-health module; existing system-health
    code is unrelated to Health Insights.
13. Google Health, Fitbit, and MyNetDiary access is isolated behind the read-only
    Google Health client and local ignored credential/token files.
## Verified official API contract

- Base endpoint: `https://health.googleapis.com/v4`
- Authorization endpoint:
  `https://accounts.google.com/o/oauth2/v2/auth`
- Token and refresh endpoint: `https://oauth2.googleapis.com/token`
- HomePulse callback:
  `http://127.0.0.1:8765/oauth2/callback`
- Minimum scopes:
  - `https://www.googleapis.com/auth/googlehealth.nutrition.readonly`
  - `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`
  - `https://www.googleapis.com/auth/googlehealth.sleep.readonly`
- No write, location, profile, settings, weight, body-fat, or raw heart-rate
  scope is requested. Resting heart rate is excluded from the first audit
  because it would broaden access beyond these three minimum scopes.
- A local Windows loopback callback is officially supported. The diagnostic
  binds only `127.0.0.1`, validates the exact callback path and OAuth state,
  uses PKCE, requests offline access, and does not use the deprecated
  copy/paste authorization-code flow.
- The diagnostic requires downloaded Web Application (`web`) JSON with the
  exact HomePulse callback registered. It accepts Google's official legacy and
  current authorization/token endpoint aliases, rejects every other endpoint,
  and normalizes runtime use to the current endpoints listed above.
- Access tokens are short-lived. HomePulse refreshes them through the token
  endpoint and preserves a prior refresh token when a refresh response omits
  one; a returned rotated refresh token replaces it atomically.
- An External app in Testing requires the Google account in **Audience → Test
  users**. Testing-mode refresh tokens expire after seven days. Published-mode
  tokens generally remain valid until revoked or unused for a prolonged period.
  A one-user personal app can be tested as an allowlisted test user, but that
  means recurring authorization. Moving to **In production** may introduce
  Google verification and policy requirements; Google Health documents a
  100-user cap for unverified clients and a third-party security review above
  100 users.

### Endpoints, pagination, and ranges

Raw records use:

`GET /users/me/dataTypes/{data-type}/dataPoints`

The list response contains `dataPoints` and `nextPageToken`. Default page size
is 1,440 and the maximum is 10,000; exercise and sleep are capped at 25.
Current list documentation does not publish a general date-range maximum.
Filters are data-type-specific: interval and exercise records filter on civil
start time, sleep filters on civil end time, and daily records filter on date.

Daily data uses:

`POST /users/me/dataTypes/{data-type}/dataPoints:dailyRollUp`

It accepts a closed-open civil range and `windowSizeDays`. The maximum request
range is 14 days for `active-minutes` and `total-calories`, and 90 days for the
other initial rollups. The diagnostic chunks each endpoint independently and
protects against repeated pagination tokens.

Initial data types:

| Data | API data type | Initial operation |
|---|---|---|
| Food logs and nutrients | `nutrition-log` | list + dailyRollUp |
| Linked food resources | `food` | get only when referenced |
| Steps | `steps` | list + dailyRollUp |
| Exercise sessions | `exercise` | list |
| Active energy | `active-energy-burned` | list + dailyRollUp |
| Total expenditure estimate | `total-calories` | dailyRollUp |
| Active minutes | `active-minutes` | list + dailyRollUp |
| Active Zone Minutes | `active-zone-minutes` | list + dailyRollUp |
| Distance | `distance` | list + dailyRollUp |
| Sleep sessions and summary stages | `sleep` | list |

Nutrition logs can contain a stable resource name, session interval, nutrients,
energy, total carbohydrate/fat, meal type, a linked `food` resource, and food
display name. Protein, fiber, and sodium are nutrient entries. The API
normalizes nutrient weights to grams, so sodium is deliberately converted from
grams to milligrams for reporting.

Exercise records contain an identifiable resource name, interval, activity
type, active duration, summary calories, distance, steps, heart rate summary,
and Active Zone Minutes. Sleep records contain resource name, start/end,
create/update time, minutes asleep, and summary stage totals. The initial audit
does not retain granular sleep-stage segments.

Every data point can contain `dataSource.recordingMethod`, device metadata,
application metadata, and `dataSource.platform`. `FITBIT` explicitly identifies
Fitbit; `FITBIT_WEB_API` identifies the legacy path. MyNetDiary is considered
identified only when returned application metadata names it. Hashed application
identifiers can distinguish otherwise anonymous sources without displaying a
client ID. Google Health resource names are stable candidates for deduplication;
the audit hashes them before reporting.

Google's published default quotas are 86.4 million requests/day per project,
120,000/minute per project, and 300/minute per user. The client handles 429 and
transient 5xx responses with bounded backoff.

Official sources:

- [Google Health setup](https://developers.google.com/health/setup)
- [Google Health endpoints](https://developers.google.com/health/endpoints)
- [Google Health data types](https://developers.google.com/health/data-types)
- [List data points](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/list)
- [Daily rollup](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/dailyRollUp)
- [Calories and energy](https://developers.google.com/health/data-types/calories)
- [Quota and rate limits](https://developers.google.com/health/rate-limits)
- [Google OAuth for desktop apps](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Google OAuth overview](https://developers.google.com/identity/protocols/oauth2)
- [MyNetDiary Google Health integration](https://www.mynetdiary.com/calorie-counter-google-health-integration.html)

## Browser setup

Do not paste credentials or tokens into ChatGPT or Codex.

1. Open Google Cloud Console and create a project, or use the project selector
   to select the project dedicated to HomePulse.
2. Open **APIs & Services → Library**, search for **Google Health API**, open it,
   and click **Enable**.
3. Open **Google Auth Platform → Branding**. Enter an app name such as
   `HomePulse`, select the support email, and save the required contact
   information.
4. Open **Google Auth Platform → Audience**. Select **External**. Leave
   **Publishing status** as **Testing** for the first audit. Under **Test
   users**, click **Add users**, add the Google account—the same account
   used by Fitbit and Google Health—and save.
5. Open **Google Auth Platform → Data Access**. Click **Add or remove scopes**,
   search for **Google Health API**, and select only:
   - Google Health nutrition read-only
   - Google Health activity and fitness read-only
   - Google Health sleep read-only
6. Open **Google Auth Platform → Clients** and click **Create client**. Choose
   **Web application** (the Google Health setup flow labels the calling
   environment **Web Server**) and name it `HomePulse local`.
7. Under **Authorized redirect URIs**, add this exact value—same scheme, IP,
   port, and path:

   `http://127.0.0.1:8765/oauth2/callback`

8. Create the client and use **Download JSON**. Leave that downloaded file in
   Downloads; do not move it into the repository.
9. In PowerShell, select the existing downloaded credentials without displaying
   the client ID embedded in its filename, then configure HomePulse:

   ```powershell
   cd <HomePulse repository root>
   $GoogleCredentials = Get-ChildItem -LiteralPath "$env:USERPROFILE\Downloads" -Filter "client_secret_*.apps.googleusercontent.com.json" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
   if (-not $GoogleCredentials) { throw "Downloaded Google OAuth credentials JSON not found." }
   .\.venv\Scripts\python.exe .\scripts\google_health_audit.py configure --credentials-file $GoogleCredentials.FullName
   ```

10. Confirm PowerShell reports that the credential file, client ID, and client
    secret are present and shows:

    `configured_callback_uri: http://127.0.0.1:8765/oauth2/callback`

11. Start the browser authorization:

    ```powershell
    .\.venv\Scripts\python.exe scripts\google_health_audit.py authorize
    ```

12. In the browser, sign in with the allowlisted Google account, review the
    three read-only permissions, and continue. Wait for this exact PowerShell
    message:

    `Google Health authorization completed and tokens were stored locally.`

13. Verify safe status:

    ```powershell
    .\.venv\Scripts\python.exe scripts\google_health_audit.py status
    ```

14. Then run the non-writing audit:

    ```powershell
    .\.venv\Scripts\python.exe scripts\google_health_audit.py audit
    ```

### MyNetDiary check

1. Open MyNetDiary **Settings**.
2. Open **Apps and Devices**.
3. Locate **Google Health** and check whether it says linked.
4. If necessary, link it to the same Google account used by Fitbit and Google
   Health.
5. Use **Verify Link** or **Verify/Sync** when available to request a current
   synchronization.
6. Do not unlink the existing Fitbit connection for this audit and do not
   change MyNetDiary activity-level settings automatically.

MyNetDiary's official documentation says it exchanges the last two days after a
link is established or restored. Historical nutrition coverage therefore must
be verified by the read-only audit rather than assumed. If only recent records
appear, that describes the current Google Health connection and does not prove
that another service lost history. A user-provided CSV or spreadsheet import is
preferable to scraping or PDF OCR.
## Audit and data-quality rules

The audit defaults to the configured journey start through the current local date. It reports,
per data type, scope, endpoint, requests, pages, records, earliest/latest dates,
uniqueness, duplicates, source distribution, days present/missing, journey
coverage, sanitized shape, and chunking. Missing records remain missing.

Nutrition days are `complete`, `partial`, `no data`, or `unknown`. The audit
uses the requested A–F history classification and never treats no record as
zero intake. It redacts food names and identifiers.

Total calories is the source of truth for estimated total daily expenditure.
Active energy is a subset. Exercise-session calories, active energy, and total
calories are never added together. Exercise categories are strength, cardio,
walking, other, or unknown based on the explicit exercise type—not heart rate.

Withings remains the source of truth for weight and body composition. The audit
queries `WeightProgressDatabase` read-only, chooses the existing reconciled
measurement for each measured day, leaves days without a weigh-in absent, and
computes a clearly labeled seven-calendar-day rolling trend from real
measurements.

## Report roadmap after Gate 4

Only fields proven by the live audit should appear:

- Daily Summary: intake, nutrients, activity, expenditure estimates, sleep,
  measured weight, and food-log completeness.
- Weekly Weight-Loss Report: averages/totals, explicit exercise categories,
  sleep, seven-day weight trend change, body-composition trends, estimated
  balance, and completeness score.
- Association Report: same-day and 1/3/7-day lag views, seven-day rolling
  averages, Pearson and Spearman results with sample size, and suppression when
  fewer than 14 complete overlapping days are available. Language must say
  “associated with,” “tended to occur alongside,” “insufficient data,” or “no
  clear relationship detected,” never causation.
- Journey Summary: configured baseline, current result, trend rates,
  body-composition changes, average intake/activity, consistency, and strongest
  adequately sampled associations.

Energy and balance are estimates. Weight displays in pounds; user-facing food
and exercise energy uses `Calories`; internal Google Health fields may retain
`kcal`; macronutrients/fiber use grams; sodium uses milligrams; and summaries use
the local calendar date. These are tracking reports, not diagnosis.
## Production data flow, storage, and operation

The intended source flow is:

`MyNetDiary -> Fitbit -> Google Health -> HomePulse`

Fitbit supplies activity and sleep through Google Health. Nutrition can travel
through the same flow, but HomePulse reports only the source identity returned
by Google Health. `FITBIT_WEB_API` identifies the legacy Fitbit path; it does not
by itself prove that MyNetDiary originated a nutrition record. Withings remains
the source of truth for weight and body composition.

HomePulse stores production summaries in `data/health_insights.db`, independent
of `modules/database.py`, with two privacy-minimal tables:

- `health_insight_days` stores normalized daily totals, completeness flags,
  source labels, measured Withings values, and import/refresh timestamps.
- `health_insights_sync_state` stores the last bounded range, outcome, safe error
  summary, and last successful refresh time.

Credentials, OAuth responses, food names, raw health records, and granular sleep
stages are not stored in this database. Upserts run in an immediate transaction,
preserve prior non-null values when a source is temporarily unavailable, retain
the original import timestamp, and are idempotent.

The rolling refresh covers the most recent seven local calendar days and relies
on the Google client for pagination, endpoint-specific chunking, token refresh,
and bounded retries. When authorization is valid, HomePulse schedules this
refresh daily at 05:15 local time through its existing in-process scheduler.

To refresh from the dashboard, open `/health-insights` and select **Refresh
Data**. From PowerShell, the same running-app operation can be requested with:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/health-insights/refresh"
```

The safe status endpoint is available at
`http://127.0.0.1:8080/api/health-insights/status`. A read-only command-line audit
for a bounded range can be run from `<HomePulse repository root>` with:

```powershell
.\.venv\Scripts\python.exe .\scripts\google_health_audit.py audit --from-date YYYY-MM-DD --through-date YYYY-MM-DD
```

The dashboard requires at least 14 complete, non-current days where nutrition,
activity, and weight overlap before displaying relationship output. Below that
threshold it reports insufficient data. Results describe association only and
must not claim causation.

OAuth credentials, tokens, audit reports, temporary health files, databases,
and database backups are local runtime artifacts protected by `.gitignore`.
They must not be committed.