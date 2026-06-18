$ErrorActionPreference = "Stop"

Write-Host "1. Creating task..."
$createRes = Invoke-RestMethod -Uri "http://localhost:8000/tasks" -Method Post -Body '{"id": "task_100", "title": "Test History Feature"}' -ContentType "application/json"

Write-Host "2. Updating status..."
$updateStatus = Invoke-RestMethod -Uri "http://localhost:8000/tasks/task_100/state" -Method Patch -Body '{"state": "in_progress"}' -ContentType "application/json"

Write-Host "3. Adding history update..."
$addHistory = Invoke-RestMethod -Uri "http://localhost:8000/tasks/task_100/history" -Method Post -Body '{"message": "Started working on the API tests.", "actor": "Arnav"}' -ContentType "application/json"

Write-Host "4. Fetching task to verify history..."
$task = Invoke-RestMethod -Uri "http://localhost:8000/tasks/task_100" -Method Get
$task | ConvertTo-Json -Depth 5
