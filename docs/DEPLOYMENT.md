# Deployment

The app is one Streamlit process (`app.py`) with no database server and no background workers.
Anything that can run Python 3.11+ or a container can host it.

## Before you go public

1. **Set `APP_PASSWORD`.** Without it, anyone with the link can use your Gemini quota.
2. **Use Gemini.** `LLM_PROVIDER=gemini` plus `LLM_API_KEY`. Ollama only works on the same
   machine (`localhost:11434`), so it is not an option on hosted platforms.
3. **Put the key in the platform's secret store**, never in the repository. `.env` is
   gitignored; keep it that way.
4. **Cap spend** on the Gemini key in Google AI Studio or Cloud Console.
5. **Keep limits at their defaults** unless you have a reason. Uploads are 25 MB
   (`AIDA_MAX_UPLOAD_BYTES`, mirrored by `server.maxUploadSize` in `.streamlit/config.toml`).
   Change both together.

## Option A: Streamlit Community Cloud (quickest)

1. Push the repository to GitHub (`main` branch, CI green).
2. In Streamlit Community Cloud choose **Create app**, select the repository, branch `main` and
   main file `app.py`. Under Advanced settings pick Python 3.12.
3. Under **Secrets** paste:

   ```toml
   LLM_PROVIDER = "gemini"
   LLM_API_KEY = "your-key"
   APP_PASSWORD = "a-long-shared-password"
   ```

   Top-level secrets are exposed as environment variables, which is where the app reads them.
4. Deploy. The platform installs from the root `requirements.txt`, which is an editable install
   of this project (`-e .[app,gemini]`). The editable form is required because the app reads
   `data/sample/` relative to the source tree.

## Option B: Hugging Face Spaces

Create a Space with the Docker SDK and push this repository to it. A Space reads its settings
from YAML at the top of the `README.md` in the Space repository, so add this block there (and
only there; the GitHub README does not need it):

```yaml
---
title: AI Data Analyst Agent
sdk: docker
app_port: 8501
---
```

Then add `LLM_PROVIDER`, `LLM_API_KEY` and `APP_PASSWORD` as Space secrets.

## Option C: Docker (Render, Fly.io, Cloud Run, your own server)

```bash
docker build -t ai-data-analyst .
docker run --rm -p 8501:8501 \
  -e LLM_PROVIDER=gemini \
  -e LLM_API_KEY=your-key \
  -e APP_PASSWORD=a-long-shared-password \
  ai-data-analyst
```

Open http://localhost:8501. The image runs as a non-root user, installs only the `app` and
`gemini` extras, and includes a health check against `/_stcore/health`. Most hosts set `PORT`
for you; the container honours it. Use the platform's secret manager rather than `-e` flags in
production.

## What was verified, and what was not

Verified: a clean install of `.[app,gemini]` (no dev or Ollama packages) renders the app with no
errors, and the full test suite, `ruff` and `mypy` pass. The password gate has its own tests.

Not verified: a live Gemini call, an actual build of the Docker image, and a real hosted
deployment. Do a smoke test after the first deploy: open the URL, sign in, load the sample
dataset in Auto-EDA, then ask the SQL Analyst one question on the sample database.

## Operating notes

- **State is per session and in memory.** Restarting the app clears sessions and uploads.
- **Uploaded SQLite files** are written to the server's temp directory and replaced when the
  same session uploads another file. A long-running container can accumulate them; restart
  periodically or mount the temp directory on tmpfs.
- **Scaling:** Streamlit holds each session in the process, so run a single instance (or use
  sticky sessions) rather than load-balancing across several.
- **Logs** should not contain SQL text, cell values or keys. Report any that do.
