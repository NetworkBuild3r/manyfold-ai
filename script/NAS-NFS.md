# Full organized library via NFS (recommended)

Docker Desktop **cannot reliably bind** Windows mapped network drives (`W:`) or
UNC paths. That is why you only saw ~79 models / ~8 pages (the OneDrive folder).

Your Synology already exports NFS:

```text
/volume1/Backups    192.168.11.0/24
```

Docker Desktop’s Linux VM is **not** on `192.168.11.0/24` (it uses 172.x /
192.168.65.x), so NFS returns **permission denied**.

## One-time Synology change

1. Open **DSM → Control Panel → Shared Folder → Backups → NFS Permissions**.
2. Edit the rule (or add one) for `/volume1/Backups`.
3. Set **Hostname or IP** to one of:
   - `*` (easiest for home lab), or
   - `172.16.0.0/12` and `192.168.65.0/24` (covers Docker Desktop / WSL)
4. Privilege: **Read/Write** (or Read-only if you prefer).
5. Enable **Allow connections from non-privileged ports** (important for Docker).
6. Squash: **Map all users to admin** or **No mapping** (either works for scan).
7. Save / apply.

## Then run

From PowerShell in the repo:

```powershell
.\script\use-nas-nfs.ps1
```

That script:

1. Creates a Docker NFS volume for `:/volume1/Backups/3D-Prints`
2. Points compose at it
3. Recreates web/workers
4. Enqueues a full library scan (shallow folder discovery — safe for large trees)

## Verify

```powershell
docker compose exec web ls /libraries/prints
docker compose exec web bundle exec rails runner "puts Model.count"
```

You should see categories (`Anime`, `DC`, `Games`, …) and model count climbing
from ~79 toward thousands.
