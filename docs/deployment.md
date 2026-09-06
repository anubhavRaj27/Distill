# Deployment

**MVP scope.** Two services on Railway: this application and a Postgres. Nothing else, no
object storage, no worker, no staging. Enough for a reviewer to open a link and use the
product. Explicitly not a production architecture; where a shortcut is taken it is named in
section 7.

Decisions D86 and D87. The `Dockerfile`, `railway.json`, `docker-entrypoint.sh` and
`Makefile` in the repository root are what execute this.

---

## 1. The shape

```
  browser ──▶ distill (Docker)  ──▶ Postgres
              API + interface        rows AND blobs
              one replica            same Railway project
```

**One container.** The API process serves the built interface itself, so there is one
origin, no CORS to configure and one service to keep awake. Requests to `/api/v1/...` are
the API; everything else is the single-page application (`server/app/web.py`).

**One database, holding everything.** Rows and file bytes both. Blobs live in a `blobs`
table rather than on disk because a container's disk does not survive a redeploy: a local
store would empty itself, and the source viewer, which is the product's whole trust
argument, would break silently while the table kept showing values.

**One replica, always.** The document queue and the event bus are both in-process
(decisions D9 and D14). Two replicas means two queues and a browser attached to the wrong
one. Railway defaults to one; leave it there.

---

## 2. Before you start

Two things from you, and the second one is the only thing I cannot do:

1. **A Gemini API key.** The one already in `server/.env` is fine.
2. **A Railway account with this repository connected**, which you have.

Cost, briefly, because Railway has no permanent free tier: a new account gets a one-time $5
credit valid for 30 days, then the Free plan grants $1 of credit a month, and Hobby is $5 a
month. This application is one small container and one small Postgres, so the trial credit
covers a demo period comfortably. Watch the project's usage page rather than assuming.

---

## 3. Deploying, click by click

### Step 1. Push what is in the working tree

Everything below expects `Dockerfile`, `railway.json` and `docker-entrypoint.sh` to be on
`main`.

```bash
make preflight
git add -A && git commit -m "Deployment: Dockerfile, Railway config, blobs in Postgres"
git push
```

### Step 2. Create the project and the database FIRST

In Railway: **New Project**, then **Deploy PostgreSQL**. Do the database before the
application, so that the variable you are about to reference already exists.

### Step 3. Add this repository as a service

In the same project: **New** then **GitHub Repo**, and pick `anubhavRaj27/Distill`.

Railway reads `railway.json`, sees `"builder": "DOCKERFILE"`, and builds the image from the
repository root. There is nothing to configure about the build.

### Step 4. Two variables on the application service

Under the service's **Variables** tab:

| Variable         | Value                        |
| ---------------- | ---------------------------- |
| `DATABASE_URL`   | `${{Postgres.DATABASE_URL}}` |
| `GEMINI_API_KEY` | your key                     |

`${{Postgres.DATABASE_URL}}` is Railway's reference syntax, typed exactly like that. It
resolves to the database service's own connection string, so nothing is copied by hand and
it keeps working if the database is ever rebuilt. If your Postgres service has a different
name, use that name in place of `Postgres`.

The URL Railway hands over is `postgresql://...`, which is the wrong dialect for this
application's driver. It is rewritten on the way in (`app/config.py`), so paste it as it
comes: that rewrite exists specifically so this step cannot be got wrong.

The image already sets `ENVIRONMENT=production`, `LOG_JSON=true`,
`STORAGE_BACKEND=postgres`, `CLIENT_DIST_DIR`, `SAMPLES_DIR` and `LLM_PROVIDER=gemini`.
That last one means a deployment with no key **refuses to start** and says why, which is
deliberate: the alternative is a container that boots and quietly serves recorded fixtures,
looking exactly like a working product until someone asks it something new.

### Step 5. Give it a domain

**Settings**, then **Networking**, then **Generate Domain**. Railway injects `PORT` and the
container listens on it.

### Step 6. Watch the first deploy

The first build is the slow one: a cold `npm ci`, a cold set of Python wheels, and
`apt-get install tesseract-ocr`. Expect several minutes.

In the deploy log, in order, you should see the build finish, then
`distill: database not ready` zero or more times, then Alembic running migrations, then
uvicorn starting. The retry is there because Railway's private network comes up a moment
after the container does, so the very first connection is the one most likely to fail for
reasons that have nothing to do with this application.

### Step 7. Read the health check before touching the interface

```bash
curl https://<your-app>.up.railway.app/healthz
```

It answers separately for the database, the store and the model, so a wrong URL and a
missing key look different rather than both looking like "it is broken". Expect
`"storage":{"ok":true,"detail":"postgres"}` and `llm` reporting `provider=gemini`.

---

## 4. If the first deploy fails

The four failures worth naming, and what each one looks like.

| What you see                                                   | What it is                                                                                          |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Build fails at `npm ci`                                        | `client/package-lock.json` out of step with `package.json`. Run `npm install` locally and commit it.  |
| `LLM_PROVIDER is 'gemini' but GEMINI_API_KEY is not set`       | Exactly what it says. The container is refusing to start rather than pretending.                     |
| `distill: migrations failed after 10 attempts`                 | `DATABASE_URL` is wrong or the database service is not running. Check the reference in step 4.        |
| Health check times out, no application log                     | The container is not listening on `PORT`. Nothing should override `PORT` in the service variables.    |

Railway keeps the previous deployment serving until a new one passes its health check, so a
failed deploy does not take the site down after the first success.

---

## 5. The smoke test

The demo script from `docs/requirements.md` section 8, against the deployed URL. Five
minutes, and it exercises everything that can only break in production:

1. Open the link. The interface loads, which proves the static mount.
2. "Try with sample documents". Ten documents appear, which proves `samples/` is in the
   image.
3. Watch them reach ready. That is the queue, the model key and the blob store.
4. Ask "total amount by vendor" and click a citation. The source document opens with the
   passage highlighted: bytes came back out of Postgres, in a byte range.
5. Open the Data screen. The table and the dashboard panels are there.

Then reload on `/w/{id}/data` directly. A 404 here means the single-page fallback is not
working, and it is the one failure this shape introduces that local development never shows.

---

## 6. Afterwards

- **Deploys are automatic.** Every push to `main` rebuilds. There is no staging environment
  and no review step, which is the right trade for one person shipping a demo and the wrong
  one for anything else.
- **Logs** are on the service's Deployments tab. They are JSON, one object per line, with
  `request_id`, `workspace_id` and `document_id` on the lines that have them.
- **Keep replicas at 1.** Scaling this service horizontally does not make it faster, it
  makes live progress and streaming answers disappear for whoever lands on the wrong
  replica.

---

## 7. What this costs you

Named rather than discovered later.

- **A small container.** Ten documents will process, and not quickly. If it is unusable,
  raise the service's resources before suspecting the code.
- **Memory.** Rendering a page at 144 DPI and running OCR over it are the heaviest things
  here. If the container is killed for memory, set `WORKER_CONCURRENCY=1` and then
  `PAGE_RENDER_DPI=110` in the service variables, in that order.
- **Page images live in the database.** Fine for a demo corpus and a few uploads, and not
  where a real workload's files go. The `Storage` protocol is the seam where that changes.
- **The Gemini free tier is the real quota.** Extraction and chat both use
  `gemini-3.5-flash-lite` because the non-lite models allow 20 requests a day. A demo that
  stops working is more likely quota than a bug, and `/healthz` will still say the model is
  configured, because it is.
- **Anyone with a workspace link has full access to it** (decision D8). Unchanged by
  deploying, and worth restating before a URL is shared.
- **No backups and no rollback** beyond redeploying a previous commit, which Railway can do
  from the Deployments tab.

---

## 8. Running the production shape locally

Two ways, and the first needs no Docker:

```bash
make serve        # builds the client, then serves it from the API on :8000
```

That is the real single-origin configuration: no Vite, no proxy, the same code path the
container runs. It uses your local database and local file storage unless you set
`STORAGE_BACKEND=postgres`.

With Docker available:

```bash
make docker-build
make docker-run   # reads server/.env, so put DATABASE_URL and GEMINI_API_KEY there
```

---

## 9. Other platforms, if Railway does not work out

Surveyed September 6, 2026. Same image, same two variables.

| Platform         | Free?                                                        | Note                                                                     |
| ---------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Koyeb            | Yes: one service, 512 MB, no card.                            | The original choice here, and unavailable to us. Does not sleep.          |
| Render           | Yes, but sleeps after 15 minutes and wakes in about a minute. | Works. Use an external Postgres: Render's own free database expires after 30 days. |
| Fly.io           | No, since October 2024.                                       | Roughly $2 to $5 a month.                                                |
| Google Cloud Run | Yes, permanently.                                             | Throttles the processor between requests, which stalls the document queue. |
