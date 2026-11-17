$ErrorActionPreference = "Stop"
python -m compileall -q .
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
python -m unittest -v test_migration_staging test_postgres_ai_service
if ($LASTEXITCODE -ne 0) { throw "Tests failed; do not deploy" }
Write-Host "Offline checks passed. Live Neon and Flask tests are STILL required."
