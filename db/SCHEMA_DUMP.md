# Generating db/schema.rb

The app expects `db/schema.rb` to exist so that fresh databases (e.g. in Docker) load the schema instead of running all migrations. To generate or update it:

**With Docker (recommended):**

```bash
./script/dump_schema.sh
```

On Windows (PowerShell):

```powershell
.\script\dump_schema.ps1
```

Then commit `db/schema.rb`. The script starts `db` and `redis`, runs schema migrations in the test container (which mounts the repo), and dumps the schema to `db/schema.rb`.

**One-command startup (PowerShell, from repo root):**

Start Docker Desktop, then:

```powershell
.\script\start-docker.ps1
```

This starts db and redis, generates `db/schema.rb` if missing, builds and starts web and worker, and waits for `http://localhost:3214/health` to return 200.

**Manual verify (after generating and committing schema.rb):**

```bash
docker compose down -v
docker compose up -d
docker compose logs -f web
```

The web container should pass the healthcheck once the database is prepared.
