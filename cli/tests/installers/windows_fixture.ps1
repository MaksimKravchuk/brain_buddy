param([Parameter(Mandatory=$true)][string]$Binary)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$root = Join-Path $env:LOCALAPPDATA ('bb-installer-fixture-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
try {
    $installer = Join-Path $PSScriptRoot '..\..\install.ps1'
    $source = [IO.File]::ReadAllText($installer)
    $tokens = $null; $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw 'Installer has PowerShell parse errors' }
    $download = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Download-ReleaseFile'},$true)
    if (!$download) { throw 'Expected dedicated download function' }
    # Offline fixture copy replaces transport and enables diagnostics for synthetic
    # inputs only. Every installer integrity and destination check still executes.
    $replacement = 'function Download-ReleaseFile([string]$Name,[long]$Limit) { Copy-Item -LiteralPath (Join-Path $env:BB_INSTALL_FIXTURE $Name) -Destination (Join-Path $stage $Name) }'
    $fixtureSource = $source.Substring(0,$download.Extent.StartOffset) + $replacement + $source.Substring($download.Extent.EndOffset)
    $fixtureSource = $fixtureSource.Replace("[Console]::Error.WriteLine('bb install failed; the previous executable is preserved. Check the version, network, integrity and destination permissions.')", "[Console]::Error.WriteLine('Synthetic installer diagnostic: ' + `$_.Exception.Message)")
    $fixtureScript = Join-Path $root 'fixture-install.ps1'; [IO.File]::WriteAllText($fixtureScript,$fixtureSource)
    foreach ($scenario in @('success','new','locked','corrupt','unsafe','duplicate','unsupported')) {
        $folder = Join-Path $root $scenario; New-Item -ItemType Directory -Path $folder | Out-Null
        $downloadDir = Join-Path $folder 'download'; New-Item -ItemType Directory -Path $downloadDir | Out-Null
        $destination = Join-Path $folder 'bin'; New-Item -ItemType Directory -Path $destination | Out-Null
        # An elevated runner defaults new folders to Administrators ownership.
        # Provision the user-owned destination the installer contract requires.
        $fixtureAcl = Get-Acl -LiteralPath $destination
        $fixtureAcl.SetOwner([Security.Principal.WindowsIdentity]::GetCurrent().User)
        Set-Acl -LiteralPath $destination -AclObject $fixtureAcl
        $previous = Join-Path $destination 'bb.exe'; [IO.File]::WriteAllText($previous,'previous-binary-sentinel')
        if ($scenario -eq 'new') { [IO.File]::Delete($previous) }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archiveName = 'bb-0.1.0-x86_64-pc-windows-msvc.zip'; $archivePath = Join-Path $downloadDir $archiveName
        $archive = [IO.Compression.ZipFile]::Open($archivePath,[IO.Compression.ZipArchiveMode]::Create)
        try { [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$Binary,$(if ($scenario -eq 'unsafe') {'../bb.exe'} else {'bb.exe'})) | Out-Null } finally { $archive.Dispose() }
        $hasher = [Security.Cryptography.SHA256]::Create()
        $hashStream = [IO.File]::OpenRead($archivePath)
        try { $digest = [BitConverter]::ToString($hasher.ComputeHash($hashStream)).Replace('-','').ToLowerInvariant() }
        finally { $hashStream.Dispose(); $hasher.Dispose() }
        if ($scenario -eq 'corrupt') { $digest = '0' * 64 }
        $lines = @('x86_64-unknown-linux-gnu','aarch64-unknown-linux-gnu','x86_64-apple-darwin','aarch64-apple-darwin','x86_64-pc-windows-msvc') | ForEach-Object { $digest + '  bb-0.1.0-' + $_ + $(if ($_ -eq 'x86_64-pc-windows-msvc') {'.zip'} else {'.tar.gz'}) }
        if ($scenario -eq 'duplicate') { $lines += $lines[0] }
        [IO.File]::WriteAllLines((Join-Path $downloadDir 'SHA256SUMS'),$lines)
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = 'powershell.exe'; $info.UseShellExecute = $false
        $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
        $info.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $fixtureScript + '" -Version 0.1.0 -InstallDir "' + $destination + '"'
        $info.EnvironmentVariables['BB_INSTALL_FIXTURE'] = $downloadDir
        if ($scenario -eq 'unsupported') { $info.EnvironmentVariables['PROCESSOR_ARCHITECTURE']='ARM64'; $info.EnvironmentVariables['PROCESSOR_ARCHITEW6432']='ARM64' }
        $locked = $null
        try {
            if ($scenario -eq 'locked') { $locked = [IO.File]::Open($previous,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read) }
            $process = [Diagnostics.Process]::Start($info)
            $output = $process.StandardOutput.ReadToEnd(); $diagnostic = $process.StandardError.ReadToEnd(); $process.WaitForExit()
        } finally { if ($locked) { $locked.Dispose() } }
        if ($scenario -in @('success','new')) {
            if ($process.ExitCode -ne 0) { throw "Success fixture failed: $diagnostic" }
            if ((& $previous --version) -cne 'bb 0.1.0') { throw 'Installed version mismatch' }
        } else {
            if ($process.ExitCode -eq 0 -or [IO.File]::ReadAllText($previous) -cne 'previous-binary-sentinel') { throw "Previous binary was not preserved: $scenario" }
        }
        if (@(Get-ChildItem -LiteralPath $destination -Force).Count -ne 1) { throw 'Staging files were not cleaned' }
    }
    Write-Output '7 installer fixtures passed'
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
