# Host the HomeCare demo

GitHub stores the code, runs the tests and hosts the static project showcase at **https://BoredDuffa.github.io/homecare-demo/**. The interactive app needs a Python service because GitHub Pages cannot run the OR-Tools backend. Keep UI and backend together on one host; no CORS or separate API configuration is needed.

## Render

[Deploy the interactive app on Render](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FBoredDuffa%2Fhomecare-demo)

1. Open the link and sign in or create your own Render account.
2. Review the Blueprint from this repository. It defines one Docker web service, **free** plan, Frankfurt region, one solver worker and `/api/health` health checks.
3. Confirm the service configuration and deploy. Open the service URL Render assigns after its first successful build. The repository does not contain account credentials or a pre-created Render service.
4. Demonstrate the four preloaded scenarios. Upload the supplied Excel framework, or export a verified roster.

The explicit `plan: free` prevents the Blueprint from silently selecting a paid default. Review the plan in the provider's UI before confirming. Free services can sleep after 15 minutes without traffic; the first request may take time to wake them. CPU is limited, so timings from the local 200-visit benchmark do not predict free-host timings. No database or paid Eircode provider is required. [Render free-service limits](https://render.com/docs/free), [Blueprint reference](https://render.com/docs/blueprint-spec).

Do not launch ten-hour stress workers on the free web service. Run those locally. Runtime caches and simulation checkpoints are ephemeral on this host, and the deployed Stress tests screen starts empty. Published historical results are in `reports/`.

## Another Docker-capable host

```bash
docker build -t homecare-demo .
docker run --rm -p 8765:10000 homecare-demo
```

Open **http://127.0.0.1:8765**. Configure your host to build the root Dockerfile, accept its assigned `PORT`, and route HTTPS to that port. The container listens on `0.0.0.0`, runs as a non-root user and starts one Uvicorn process. It serves both the browser UI and API.

`HOMECARE_SOLVER_WORKERS` accepts 1–4, defaulting to one in the Docker image. Use one for modest hosting. Simultaneous solve requests receive an explicit busy response rather than starting multiple solvers. Excel uses `openpyxl`; no private Node runtime is needed.

GitHub Actions runs the tests, builds the container and checks the packaged UI, solver, workbook import and workbook result export. That is a packaging check, not proof of a completed Render deployment.

## Demo data and services

Use fictional data. Drafts are stored in each visitor's browser, but solving/import/export sends those inputs to the Python server. There is no login, shared database or access-controlled care-record system. Public-place lookup has incomplete Eircode coverage. Explicit lookup and road-refresh actions contact the configured public providers; map tiles load from OpenStreetMap. Full private-address coverage and production care workflows need separate implementation and provider agreements.

[GitHub Pages server-side limitations](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site).
