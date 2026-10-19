# Deploying Bloodline

Bloodline runs on three free tiers:

| Part | Service | What runs there |
|---|---|---|
| Database | Neon (Postgres 16 + pgvector), Singapore | All data |
| Backend | Render free web service, Singapore | The Docker image from GHCR |
| Frontend | Vercel Hobby | The built React app (static files) |

After the setup below, deploying is automatic:

- **Backend:** every push to `main` runs CI. When CI passes,
  [`deploy.yml`](../.github/workflows/deploy.yml) does the following:
  1. builds the image and pushes it to `ghcr.io/abhinow0909/bloodline-api` (tagged with the
     commit and `latest`);
  2. migrates and seeds the Neon database **with that image**;
  3. calls Render's deploy hook with the image's exact digest;
  4. waits until `GET /health` reports the new commit.

  If the migration fails, nothing is deployed and the running version keeps serving.
- **Frontend:** Vercel builds and publishes `frontend/` on every push to `main`, through its
  own Git integration. It does not wait for CI or for the backend deploy.

Secrets and where they live:

| Secret | Render | GitHub `production` environment | Your machine |
|---|---|---|---|
| `DATABASE_URL` (Neon) | yes | yes (migrations) | only when creating a user |
| `JWT_SECRET` | yes (production's own) | no (the workflow uses a throwaway one) | no |
| `GROQ_API_KEY` | yes | no | `.env` for development |
| Render deploy hook URL | (Render shows it) | yes | no |

Never paste any of these into a file in the repository, an issue or a log.

---

## First-time setup

Follow these steps in order. Each service needs something from the one before it.

### 1. Neon: the database

1. Sign in at <https://console.neon.tech> and click **New project**:
   - **Name:** `bloodline`
   - **Postgres version:** **16** (the same as development and CI)
   - **Region:** **AWS Asia Pacific (Singapore)**, next to the Render service
2. When the project is ready, click **Connect**:
   - The project's default branch (`production` in new projects; older ones call it
     `main`); database `neondb` (the default is fine); the owner role.
   - **Turn off "Connection pooling".** Bloodline uses the direct connection, both for
     migrations (which need it) and for the app (a family-scale app needs only a few
     connections, well under the free plan's limit).
3. Copy the connection string. It looks like
   `postgresql://neondb_owner:<password>@ep-…-….ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require`.
   Change the scheme so SQLAlchemy uses psycopg 3. Only the beginning changes:

   ```
   postgresql+psycopg://neondb_owner:<password>@ep-…/neondb?sslmode=require&channel_binding=require
   ```

   This is the **`DATABASE_URL`** used below. Keep it in your password manager.

Nothing needs to be created in the database by hand. The first deploy runs the migrations,
which also enable the `vector` extension, and loads the dictionary of lab tests.

Free plan limits: 1 GB of storage per project, 100 compute-hours a month, and the database
sleeps after 5 minutes idle (it wakes in about a second). Point-in-time restore covers 6 hours.

### 2. GitHub: the `production` environment

In the repository, open **Settings → Environments → New environment** and name it
**`production`**.

1. Under **Deployment branches and tags**, choose **Selected branches and tags**, then add
   `main`. Only `main` can then deploy, even when the workflow is started by hand.
2. Under **Environment secrets**, add **`DATABASE_URL`**: the Neon URL from step 1, in its
   `postgresql+psycopg://` form.
3. Leave `RENDER_DEPLOY_HOOK_URL` and `API_URL` for step 5.

Optional: **Required reviewers** makes every deploy wait for your approval in the Actions
tab.

### 3. First deploy: build the image and migrate

Push to `main`, or open **Actions → Deploy → Run workflow** (branch `main`). Without the
Render settings, the run does the following:

- builds and pushes the image;
- migrates and seeds Neon;
- shows a notice that nothing was deployed. That is expected at this stage.

Then make the image public, so Render can pull it without a token:

1. On your GitHub profile, open **Packages → bloodline-api → Package settings**.
2. Under **Danger Zone → Change visibility**, choose **Public**.

The image holds only code and the embedding model, never data or secrets.

### 4. Render: the backend

1. At <https://dashboard.render.com>, click **New → Web Service → Existing Image**.
2. **Image URL:** `ghcr.io/abhinow0909/bloodline-api:latest`. No credential is needed
   because the image is public. Click **Connect**.
3. Set the service:
   - **Name:** for example `bloodline-api`. The service's address becomes
     `https://<name>.onrender.com`; Render adds a suffix if the name is taken.
   - **Region:** **Singapore**
   - **Instance type:** **Free**
4. Under **Environment Variables**, add:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the Neon URL (`postgresql+psycopg://…`) |
   | `JWT_SECRET` | a new value from `openssl rand -hex 32`, only for production |
   | `GROQ_API_KEY` | your Groq key |
   | `CORS_ORIGINS` | the Vercel address from step 6 (for now, `https://example.invalid`) |

   Leave everything else at its default:
   - `MAX_UPLOAD_MB` stays at 10, which the frontend's own check also uses. Change both or
     neither.
   - Do not set the `EMBEDDING_*` variables: the model is built into the image and works
     offline.
   - `PORT` is set by Render, and the image listens on it.
5. Click **Deploy**. The first start takes a minute or two. Then open
   `https://<name>.onrender.com/health`. It should return
   `{"status":"ok","database":"ok","version":"<commit>"}`.
6. In the service's **Settings**, do two things:
   - Set **Health Check Path** to `/health`. Render then switches traffic to a new version only
     once it answers, and keeps the old one if it never does.
   - Copy the **Deploy Hook** URL. It contains a secret key.

Free plan notes:
- The service sleeps after 15 minutes without traffic and takes about a minute to wake. The
  sign-in page wakes it as soon as it opens, and says so if signing in is slow.
- There are 750 free instance-hours a month, enough for one service.
- Memory is 512 MB. Bloodline uses about 85 MB idle and about 330 MB once report search has
  loaded the model.

### 5. GitHub: connect the deploy to Render

In **Settings → Environments → production**:

1. Add the secret **`RENDER_DEPLOY_HOOK_URL`**: the deploy hook from step 4.6.
2. Under **Environment variables**, add **`API_URL`** = `https://<name>.onrender.com`, with no
   trailing slash.

### 6. Vercel: the frontend

1. At <https://vercel.com/new>, import the `AbhiNow0909/Bloodline` repository.
2. Configure the project:
   - **Root Directory:** `frontend`
   - **Framework Preset:** Vite (detected). Leave the build command (`npm run build`) and
     the output directory (`dist`) as they are.
   - **Environment Variables:** `VITE_API_BASE_URL` = `https://<name>.onrender.com`, for
     **Production and Preview**.

     The build fails on purpose if this variable is missing or not `https://`. Otherwise the
     app would be built to call `localhost`. The address is also written into the page's
     Content-Security-Policy, so the browser lets the page talk to that API and nothing else.
3. Click **Deploy** and note the address, for example `https://bloodline-xyz.vercel.app`.
4. Back in Render, set **`CORS_ORIGINS`** to that address, with no trailing slash. Save; Render
   redeploys with the new value.

`frontend/vercel.json` does three things:
- sends every app path to `index.html`, so links and reloads work;
- caches the built assets for a year (their file names change with their content);
- adds security headers: no framing, `nosniff`, no referrer, and no camera, microphone or
  location.

Preview deployments (other branches) build, but cannot sign in: only the production address
is in `CORS_ORIGINS`. That is by design.

### 7. Create the first account

There is no sign-up. Create accounts from your machine with the production image, against
Neon:

```bash
read -rsp "Neon DATABASE_URL: " DATABASE_URL && export DATABASE_URL && echo
docker run --rm -it -e DATABASE_URL -e JWT_SECRET="$(openssl rand -hex 32)" \
  ghcr.io/abhinow0909/bloodline-api:latest \
  python -m app.cli.create_user --email you@example.com --name "Your Name"
unset DATABASE_URL
```

The command prompts for the password twice. `JWT_SECRET` is only there because the settings
require one; creating a user does not use it. `read -s` keeps the database password out of
your shell history.

### 8. Check the whole path

1. Run **Actions → Deploy → Run workflow** once more. It should finish with
   "`https://<name>.onrender.com is running <commit>`".
2. Open the Vercel address and sign in, ideally after the backend has slept for 15 minutes,
   to see the slow-start message. Then create a family and a member, and upload the synthetic
   report `backend/tests/fixtures/synthetic_thyrocare_report.pdf`. It is read, reviewed,
   saved and charted.
3. Delete that test family afterwards.

---

## Everyday operations

- **Deploying:** push to `main`. Watch **Actions → CI**, then **Actions → Deploy**. The
  frontend appears in Vercel's dashboard. **Run workflow** on Deploy redeploys the current
  `main` without waiting for CI. Use it for a commit that has already passed CI.
- **Which version is live:** `GET https://<name>.onrender.com/health` → `"version"` is the
  commit.
- **Logs:** Render dashboard → the service → **Logs**. The app logs report ids and error
  types, never report text or names.
- **Rolling back the backend:** pick an earlier deploy in Render's **Events**/**Deploys** and
  roll back. Alternatively, call the hook with an earlier image:
  `curl -fsS -G "$RENDER_DEPLOY_HOOK_URL" --data-urlencode "imgURL=ghcr.io/abhinow0909/bloodline-api:<commit>"`.

  Migrations are **not** undone by a rollback. Bloodline's migrations only add to the schema
  so far, so an older image keeps working. If one ever removes something, write the rollback
  plan before deploying it.
- **Rolling back the frontend:** Vercel → **Deployments** → an earlier one → **Instant
  Rollback**.
- **Changing a secret:**
  - **Render:** edit the environment variable; Render redeploys.
  - **GitHub:** edit the environment secret.
  - **`JWT_SECRET`:** changing it signs everyone out.
- **Re-indexing report text** (only needed after changing chunking or the embedding model):
  run `python -m app.cli.rag reindex --all` from your machine with the production image,
  like `create_user` above. Render's free plan has no shell.
- **Groq limits:** the free tier allows `gpt-oss-20b` about 200,000 tokens a day. A long
  health checkup uses a large share of that. A report that fails for the daily limit can be
  retried later from its page.

## Deploy checklist

There is no staging environment on these free tiers. CI's Docker job stands in for one: it
migrates an empty database with the built image and drives the API end to end. So most
checks happen before the push.

**Before pushing to `main`:**

- [ ] CI is green for the change: backend, frontend and the Docker image job.
- [ ] If the change adds a migration:
  - it only adds to the schema, and drops or renames nothing the running version still
    uses;
  - CI ran `alembic upgrade head` and `alembic check` on it.

  Note the time: Neon can restore the database to any moment in the last 6 hours.
- [ ] Any new environment variable is set first: in Render for the backend, in Vercel for a
  `VITE_*` one.
- [ ] If the frontend now loads something from a new origin (a font, an image, another API),
  update `frontend/csp.ts`. Otherwise the browser blocks it.

**After the Deploy workflow finishes:**

- [ ] The workflow's last step says `/health` reports the new commit.
- [ ] On the Vercel address: sign in, open a member's results and one test's chart, and open a
  saved report.
- [ ] The browser console shows no "Content Security Policy" errors.
- [ ] Render's logs show no errors for those requests.

**Roll back** (see above) if, after a deploy:

- `/health` is not `ok`, or signing in fails;
- uploading a report or saving a review fails for a report that worked before;
- every page says it can't reach the server while `/health` is fine (`CORS_ORIGINS` or
  `VITE_API_BASE_URL`).

**If a migration damaged data:**

1. Stop deploys: disable the Deploy workflow under **Actions**.
2. In the Neon console, open **Backup & Restore** and restore the default branch to a moment
   before the deploy. This is only possible within 6 hours.
3. Redeploy the previous image with the hook.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Deploy fails at "Check the deploy settings" | `DATABASE_URL` missing from the `production` environment |
| Deploy fails at "Migrate" | Neon URL wrong (scheme must be `postgresql+psycopg://`), or a migration error (see the log) |
| Deploy hook returns 400 or 404 | The image URL in Render isn't `ghcr.io/abhinow0909/bloodline-api:…` |
| Deploy hook returns 401 | The hook was regenerated in Render; update `RENDER_DEPLOY_HOOK_URL` |
| "did not report \<commit\> within 15 minutes" | Render failed to start the image: see Render's deploy log (often a missing environment variable) |
| Render cannot pull the image | The GHCR package is still private (step 3) |
| The app says it can't reach the server | `VITE_API_BASE_URL` wrong, or the Vercel address not in `CORS_ORIGINS` (exact, no trailing path) |
| Sign-in takes a minute | The free service was asleep; expected after 15 idle minutes |
| Vercel build fails with "VITE_API_BASE_URL must be set" | Add it in Vercel → Settings → Environment Variables, then redeploy |
