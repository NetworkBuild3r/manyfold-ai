<#
.SYNOPSIS
  For each .zip/.rar/.7z: put it in its own folder, extract only images into that folder
  so Manyfold can show previews (does NOT unpack all STL/model files).

.DESCRIPTION
  Example:
    etsy\Abe3D - Elektra.rar
  becomes:
    etsy\Abe3D - Elektra\
      Abe3D - Elektra.rar     (moved in)
      preview.jpg             (best image)
      images\*.jpg/png/...    (all images from archive)

  Uses 7-Zip (required for .rar). Dry-run unless -Apply.

.EXAMPLE
  .\script\organize-extract-images.ps1
  .\script\organize-extract-images.ps1 -Apply
  .\script\organize-extract-images.ps1 -Path 'W:\3D-Prints-Unorg\etsy' -Apply
#>
[CmdletBinding()]
param(
  [string]$Path = 'W:\3D-Prints-Unorg\etsy',
  [switch]$Apply,
  [switch]$Force,
  [int]$MaxDepth = 3,
  [int]$MinImageBytes = 4KB,
  [int]$MaxImages = 40,
  [string]$SevenZip = '',
  [string]$LogDir = ''
)

$ErrorActionPreference = 'Continue'

$imageExts = @('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
$archiveExts = @('.zip', '.rar', '.7z', '.cbz')
$preferHints = @('preview', 'cover', 'thumb', 'thumbnail', 'product', 'render', 'main', 'photo', 'front', 'hero')

function Write-Info([string]$m) { Write-Host $m }
function Write-Warn2([string]$m) { Write-Host "WARN: $m" -ForegroundColor Yellow }

function Find-SevenZip {
  if ($SevenZip -and (Test-Path -LiteralPath $SevenZip)) { return $SevenZip }
  foreach ($c in @(
      'C:\Program Files\7-Zip\7z.exe',
      'C:\Program Files (x86)\7-Zip\7z.exe',
      (Join-Path $env:LOCALAPPDATA 'Programs\7-Zip\7z.exe')
    )) {
    if (Test-Path -LiteralPath $c) { return $c }
  }
  $cmd = Get-Command 7z.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

function Get-SafeName([string]$name) {
  $n = $name.Trim().TrimEnd('.')
  $n = $n -replace '^\s*-\s+', ''   # leftover " - Foo" / "- Foo"
  $n = $n -replace '[<>:"/\\|?*\x00-\x1F]', ' '
  $n = ($n -replace '\s+', ' ').Trim()
  if ([string]::IsNullOrWhiteSpace($n)) { $n = 'unnamed-model' }
  if ($n.Length -gt 120) { $n = $n.Substring(0, 120).Trim() }
  return $n
}

function Get-LooseArchives {
  param([string]$Root, [int]$Depth)
  $list = New-Object System.Collections.Generic.List[System.IO.FileInfo]
  $q = [System.Collections.Generic.Queue[object]]::new()
  $q.Enqueue([pscustomobject]@{ P = $Root; D = 0 })
  while ($q.Count -gt 0) {
    $c = $q.Dequeue()
    if ($c.D -gt $Depth) { continue }
    $leaf = Split-Path $c.P -Leaf
    if ($leaf -like '.*' -and $c.D -gt 0) { continue }
    if ($leaf -in @('#recycle', '@eaDir', '_from_drive')) { continue }
    try {
      # Only archives sitting directly in this directory (not already nested deeper than needed)
      Get-ChildItem -LiteralPath $c.P -File -ErrorAction SilentlyContinue |
        Where-Object { $archiveExts -contains $_.Extension.ToLowerInvariant() } |
        ForEach-Object { $list.Add($_) | Out-Null }
      if ($c.D -lt $Depth) {
        Get-ChildItem -LiteralPath $c.P -Directory -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -notlike '.*' -and $_.Name -notin @('#recycle', '@eaDir', 'images') } |
          ForEach-Object { $q.Enqueue([pscustomobject]@{ P = $_.FullName; D = $c.D + 1 }) }
      }
    } catch {}
  }
  return $list
}

function Get-ImageScore([string]$entryName, [long]$length) {
  $base = [IO.Path]::GetFileNameWithoutExtension($entryName).ToLowerInvariant()
  $score = [double][Math]::Min($length, 50MB)
  foreach ($h in $preferHints) {
    if ($base -eq $h -or $base.Contains($h)) { $score += 50MB; break }
  }
  if ($base -match 'icon|logo|favicon|sprite') { $score -= 30MB }
  $depth = ($entryName -split '[/\\]').Count
  $score -= $depth * 100KB
  return $score
}

function Invoke-7z {
  param(
    [string]$SevenZipExe,
    [string[]]$ZArgs
  )
  # cmd.exe quoting is reliable for paths with spaces and parentheses.
  $outFile = Join-Path $env:TEMP ("7z-out-" + [guid]::NewGuid().ToString('n') + ".txt")
  $parts = foreach ($a in $ZArgs) {
    if ($null -eq $a) { continue }
    if ($a -match '[\s\(\)&]') { '"{0}"' -f ($a -replace '"', '""') } else { $a }
  }
  $argLine = $parts -join ' '
  $cmdLine = '"{0}" {1} > "{2}" 2>&1' -f $SevenZipExe, $argLine, $outFile
  try {
    cmd.exe /c $cmdLine | Out-Null
    $code = $LASTEXITCODE
    $stdout = if (Test-Path -LiteralPath $outFile) {
      Get-Content -LiteralPath $outFile -Raw -ErrorAction SilentlyContinue
    } else { '' }
    return [pscustomobject]@{ ExitCode = $code; Out = $stdout; Err = '' }
  } finally {
    Remove-Item -LiteralPath $outFile -Force -ErrorAction SilentlyContinue
  }
}

function Get-ArchiveImageEntries {
  param([string]$SevenZipExe, [string]$ArchivePath)

  $r = Invoke-7z -SevenZipExe $SevenZipExe -ZArgs @('l', '-slt', '--', $ArchivePath)
  $out = $r.Out
  if ([string]::IsNullOrWhiteSpace($out)) { $out = $r.Err }

  $entries = New-Object System.Collections.Generic.List[object]
  $curPath = $null
  $curSize = 0L
  foreach ($line in ($out -split "`r?`n")) {
    if ($line -match '^Path = (.+)$') {
      # flush previous
      if ($curPath) {
        $ext = [IO.Path]::GetExtension($curPath).ToLowerInvariant()
        if ($imageExts -contains $ext -and $curSize -ge $MinImageBytes) {
          # skip if path is the archive itself
          if ($curPath -ne $ArchivePath -and $curPath -notmatch '\.(rar|zip|7z)$') {
            $entries.Add([pscustomobject]@{
                Path  = $curPath
                Size  = $curSize
                Score = (Get-ImageScore $curPath $curSize)
                File  = [IO.Path]::GetFileName($curPath)
              }) | Out-Null
          }
        }
      }
      $curPath = $Matches[1].Trim()
      $curSize = 0L
    } elseif ($line -match '^Size = (\d+)$') {
      $curSize = [long]$Matches[1]
    }
  }
  # last entry
  if ($curPath) {
    $ext = [IO.Path]::GetExtension($curPath).ToLowerInvariant()
    if ($imageExts -contains $ext -and $curSize -ge $MinImageBytes) {
      if ($curPath -ne $ArchivePath -and $curPath -notmatch '\.(rar|zip|7z)$') {
        $entries.Add([pscustomobject]@{
            Path  = $curPath
            Size  = $curSize
            Score = (Get-ImageScore $curPath $curSize)
            File  = [IO.Path]::GetFileName($curPath)
          }) | Out-Null
      }
    }
  }
  return @($entries | Sort-Object Score -Descending)
}

function Extract-AllImagesFromArchive {
  param(
    [string]$SevenZipExe,
    [string]$ArchivePath,
    [string]$ImagesDir,
    [string]$ModelDir
  )
  if (-not (Test-Path -LiteralPath $ImagesDir)) {
    New-Item -ItemType Directory -Path $ImagesDir -Force | Out-Null
  }
  $tmp = Join-Path $env:TEMP ("mf-imgs-" + [guid]::NewGuid().ToString('n'))
  New-Item -ItemType Directory -Path $tmp -Force | Out-Null
  try {
    # Flatten-extract only image extensions (recursive inside archive)
    $r = Invoke-7z -SevenZipExe $SevenZipExe -ZArgs @(
      'e', '-y', '-r', "-o$tmp", '--', $ArchivePath,
      '*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif', '*.bmp',
      '*.JPG', '*.JPEG', '*.PNG', '*.WEBP', '*.GIF', '*.BMP'
    )
    if ($r.ExitCode -gt 1) {
      Write-Warn2 "  7z extract images exit $($r.ExitCode)"
    }
    $files = @(Get-ChildItem -LiteralPath $tmp -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $imageExts -contains $_.Extension.ToLowerInvariant() -and $_.Length -ge $MinImageBytes } |
        Sort-Object Length -Descending)
    if ($files.Count -eq 0) { return 0 }

    $count = 0
    foreach ($f in ($files | Select-Object -First $MaxImages)) {
      $dest = Join-Path $ImagesDir $f.Name
      if (Test-Path -LiteralPath $dest) {
        # disambiguate
        $dest = Join-Path $ImagesDir ("{0}-{1}" -f [IO.Path]::GetFileNameWithoutExtension($f.Name), $f.Length) 
        $dest += $f.Extension
      }
      Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
      $count++
    }

    # Best (largest, after sort) as preview.*
    if (-not (Test-HasPreview $ModelDir)) {
      $best = $files[0]
      $ext = $best.Extension.ToLowerInvariant()
      if ($ext -eq '.jpeg') { $ext = '.jpg' }
      $preview = Join-Path $ModelDir ("preview$ext")
      Copy-Item -LiteralPath $best.FullName -Destination $preview -Force
    }
    return $count
  } finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function Test-HasPreview([string]$dir) {
  foreach ($n in @('preview.jpg', 'preview.jpeg', 'preview.png', 'preview.webp', 'cover.jpg', 'cover.png')) {
    if (Test-Path -LiteralPath (Join-Path $dir $n)) { return $true }
  }
  return $false
}

# --- main ---
if (-not (Test-Path -LiteralPath $Path)) { throw "Path not found: $Path" }
$sz = Find-SevenZip
if (-not $sz) { throw "7-Zip required (https://www.7-zip.org/). Not found." }

$mode = if ($Apply) { 'APPLY' } else { 'DRY-RUN (pass -Apply)' }
Write-Info "=== organize-extract-images ($mode) ==="
Write-Info "Path:  $Path"
Write-Info "7-Zip: $sz"
Write-Info "Moves each archive into its own folder + extracts images only (not STLs)."

$archives = @(Get-LooseArchives -Root $Path -Depth $MaxDepth | Sort-Object FullName)
Write-Info "Archives found: $($archives.Count)"

if (-not $LogDir) {
  $LogDir = Join-Path (Split-Path $Path -Parent) '.manyfold-organize-logs'
}
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

$report = New-Object System.Collections.Generic.List[object]
$nOk = 0; $nSkip = 0; $nFail = 0; $nImg = 0
$i = 0

foreach ($arc in $archives) {
  $i++
  $base = Get-SafeName ([IO.Path]::GetFileNameWithoutExtension($arc.Name))
  $parent = $arc.DirectoryName

  # Already inside a folder named for this model?
  $alreadyNested = ($arc.Directory.Name -eq $base)
  $modelDir = if ($alreadyNested) { $parent } else { Join-Path $parent $base }
  $archiveDest = Join-Path $modelDir $arc.Name

  # Skip if preview already present and not Force
  if (-not $Force -and (Test-HasPreview $modelDir)) {
    if (($i % 40) -eq 0 -or $i -le 3) {
      Write-Info "[$i/$($archives.Count)] SKIP preview exists: $base"
    }
    $nSkip++
    $report.Add([pscustomobject]@{ Action = 'skip-preview-exists'; Archive = $arc.FullName; ModelDir = $modelDir }) | Out-Null
    continue
  }

  # Resolve archive path: may already live inside model folder from a prior run
  $arcPathLive = $arc.FullName
  if (-not (Test-Path -LiteralPath $arcPathLive)) {
    $maybe = Join-Path $modelDir $arc.Name
    if (Test-Path -LiteralPath $maybe) { $arcPathLive = $maybe }
  }

  Write-Info "[$i/$($archives.Count)] $base  ($([math]::Round($arc.Length/1MB,1)) MB)"

  if (-not $Apply) {
    $imgs = @()
    try { $imgs = @(Get-ArchiveImageEntries -SevenZipExe $sz -ArchivePath $arc.FullName) } catch {}
    $take = @($imgs | Select-Object -First $MaxImages)
    Write-Info "  WOULD folder: $modelDir"
    if (-not $alreadyNested) { Write-Info "  WOULD move archive into folder" }
    Write-Info "  WOULD extract $($take.Count) image(s)"
    if ($take.Count -gt 0) {
      Write-Info "  best: $($take[0].Path) ($([math]::Round($take[0].Size/1KB)) KB)"
    }
    $nOk++
    $nImg += $take.Count
    $report.Add([pscustomobject]@{
        Action   = 'would-process'
        Archive  = $arc.FullName
        ModelDir = $modelDir
        Images   = $take.Count
        Best     = if ($take.Count) { $take[0].Path } else { $null }
      }) | Out-Null
    continue
  }

  try {
    if (-not (Test-Path -LiteralPath $modelDir)) {
      New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
    }

    # Move archive into its folder
    if (-not $alreadyNested) {
      if (-not (Test-Path -LiteralPath $archiveDest)) {
        Move-Item -LiteralPath $arc.FullName -Destination $archiveDest -Force
      }
      $arcPath = $archiveDest
    } else {
      $arcPath = $arc.FullName
    }

    $imagesDir = Join-Path $modelDir 'images'
    $extracted = Extract-AllImagesFromArchive -SevenZipExe $sz -ArchivePath $arcPath -ImagesDir $imagesDir -ModelDir $modelDir
    if ($extracted -eq 0) {
      Write-Info "  no images in archive"
      $report.Add([pscustomobject]@{ Action = 'no-images'; Archive = $arcPath; ModelDir = $modelDir }) | Out-Null
      $nOk++
      continue
    }

    $hasPrev = Test-HasPreview $modelDir
    Write-Info "  extracted $extracted image(s); preview=$hasPrev"
    $nImg += $extracted
    $nOk++
    $report.Add([pscustomobject]@{
        Action   = 'done'
        Archive  = $arcPath
        ModelDir = $modelDir
        Images   = $extracted
      }) | Out-Null
  } catch {
    Write-Warn2 "  FAIL: $($_.Exception.Message)"
    $nFail++
    $report.Add([pscustomobject]@{ Action = 'error'; Archive = $arc.FullName; Error = $_.Exception.Message }) | Out-Null
  }
}

Write-Info ""
Write-Info "=== Summary ==="
Write-Info "Processed / would: $nOk"
Write-Info "Skipped:           $nSkip"
Write-Info "Failed:            $nFail"
Write-Info "Images extracted:  $nImg"
if (-not $Apply) { Write-Info "Dry-run only. Re-run with -Apply to write." }

$log = Join-Path $LogDir ("organize-extract-images-$(Get-Date -Format yyyyMMdd-HHmmss).json")
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $log -Encoding UTF8
Write-Info "Log: $log"
