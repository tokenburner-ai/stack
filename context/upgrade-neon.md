# Upgrade to Neon — Tokenburner Context

This context is loaded by `tokenburner upgrade neon`. It guides you through migrating from SQLite-on-S3 to Neon Postgres.

> **Status: Not yet implemented.** This is a planned feature. The migration will involve:
>
> 1. Create a Neon project + database
> 2. Run migrations against Neon (same SQL files, Postgres mode)
> 3. Export data from SQLite snapshot and import to Neon
> 4. Update Lambda environment variables (DATABASE_URL → Neon connection string)
> 5. Redeploy — db.py auto-detects Postgres mode from DATABASE_URL
> 6. Verify data integrity
> 7. Remove S3_DB_BUCKET env var (no longer needed)
>
> Neon's serverless Postgres is a natural upgrade path from SQLite-on-S3:
> - Same Postgres SQL (no translation needed)
> - Serverless — scales to zero, no idle cost beyond free tier
> - Connection pooling built-in (important for Lambda cold starts)
> - Branching (like our db_branch.py but built into the database)
>
> Estimated cost: $0/mo on Neon free tier (0.5 GB storage, 190 compute hours/mo)
