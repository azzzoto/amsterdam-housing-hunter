# Northflank deployment

The GitHub Actions workflow updates an existing Northflank deployment service to the immutable GHCR image built for each push to `main`. The Northflank service owns the production process and restarts it independently of GitHub Actions.

## One-time setup

1. In Northflank, create a project and a **deployment service** configured for one replica. SQLite is single-writer, so do not scale this service horizontally.
2. Configure it to pull the private image `ghcr.io/azzzoto/amsterdam-housing-hunter`. Create a GitHub Container Registry credential with package read access in Northflank and save its credential ID. Do not put that token in the repository.
3. Attach a persistent volume mounted at `/app/data`. Attach a second persistent volume at `/app/backups` if automated backup files should also persist through deployments. Keep the database volume mounted at exactly `/app/data`.
4. Set the application's runtime variables from `.env.example` in Northflank's secret/environment settings. At minimum configure the Telegram bot token, admin Telegram ID, and contact email in `USER_AGENT`. Do not put production values in Git.
5. Add a **CMD liveness check** with command `python -m app.main --healthcheck`; allow at least 30 seconds of initial startup delay, then check approximately once per minute. Northflank restarts unhealthy containers when this probe is configured.
6. In the GitHub repository, set variable `DEPLOY_TARGET` to `northflank`, and add:

   - Secret `NORTHFLANK_API_TOKEN`: a Northflank API token with permission to update and inspect the selected project service.
   - Variable `NORTHFLANK_PROJECT_ID`: project ID.
   - Variable `NORTHFLANK_SERVICE_ID`: deployment service ID.
   - Variable `NORTHFLANK_CREDENTIALS_ID`: saved GHCR registry credential ID from step 2.

7. Push a commit to `main`. The workflow runs tests, builds/publishes a multi-architecture image to GHCR, changes the service image, and polls until Northflank reports the requested image deployed. Northflank must show a healthy container using the configured CMD probe.

Northflank's API deployment update does not create the service or its volume. Create those once in the Northflank console and keep one replica. Check the Northflank estimate and account plan before leaving the service running; available free allowances, persistent disk charges, and account requirements can change.

## Roll back

From the GitHub repository's **Actions → Test, publish, and deploy → Run workflow**, choose `northflank` and enter the previous full immutable image tag, such as `sha-<40-character-commit-sha>`. The current workflow commits and publishes first, then deploys the selected prior image. Alternatively, choose the prior successful deployment in the Northflank console. The persistent volume is not changed by an image rollback.
