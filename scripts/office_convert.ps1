param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][ValidateSet('docx', 'xlsx')][string]$Target
)

$ErrorActionPreference = 'Stop'
$inputFull = [System.IO.Path]::GetFullPath($InputPath)
$outputFull = [System.IO.Path]::GetFullPath($OutputPath)

function Stop-OwnedOfficeProcesses([int[]]$OfficeProcessIds) {
    foreach ($officeProcessId in $OfficeProcessIds) {
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if ($null -eq (Get-Process -Id $officeProcessId -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 100
        }
        Stop-Process -Id $officeProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-ComWithRetry([scriptblock]$Action) {
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        try {
            return & $Action
        }
        catch [System.Runtime.InteropServices.COMException] {
            if ($_.Exception.HResult -ne -2147418111 -or $attempt -eq 9) { throw }
            Start-Sleep -Milliseconds 300
        }
    }
}

if ($Target -eq 'docx') {
    $application = $null
    $document = $null
    $beforeProcessIds = @(Get-Process WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $officeProcessIds = @()
    try {
        $application = New-Object -ComObject Word.Application
        Start-Sleep -Milliseconds 750
        $officeProcessIds = @(
            Get-Process WINWORD -ErrorAction SilentlyContinue |
                Where-Object { $_.Id -notin $beforeProcessIds } |
                Select-Object -ExpandProperty Id
        )
        [void](Invoke-ComWithRetry {
            $application.Visible = $false
            $application.DisplayAlerts = 0
            $application.AutomationSecurity = 3
        })
        $document = Invoke-ComWithRetry { $application.Documents.Open($inputFull, $false, $true) }
        $wordFormat = 16
        [void](Invoke-ComWithRetry { $document.SaveAs([ref]$outputFull, [ref]$wordFormat) })
    }
    finally {
        if ($null -ne $document) {
            try { [void](Invoke-ComWithRetry { $document.Close($false) }) } catch {}
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
        }
        if ($null -ne $application) {
            try { [void](Invoke-ComWithRetry { $application.Quit() }) } catch {}
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
        Stop-OwnedOfficeProcesses $officeProcessIds
    }
}
else {
    $application = $null
    $workbook = $null
    $beforeProcessIds = @(Get-Process EXCEL -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $officeProcessIds = @()
    try {
        $application = New-Object -ComObject Excel.Application
        Start-Sleep -Milliseconds 750
        $officeProcessIds = @(
            Get-Process EXCEL -ErrorAction SilentlyContinue |
                Where-Object { $_.Id -notin $beforeProcessIds } |
                Select-Object -ExpandProperty Id
        )
        [void](Invoke-ComWithRetry {
            $application.Visible = $false
            $application.DisplayAlerts = $false
            $application.AutomationSecurity = 3
        })
        $workbook = Invoke-ComWithRetry { $application.Workbooks.Open($inputFull, 0, $true) }
        [void](Invoke-ComWithRetry { $workbook.SaveAs($outputFull, 51) })
    }
    finally {
        if ($null -ne $workbook) {
            try { [void](Invoke-ComWithRetry { $workbook.Close($false) }) } catch {}
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($workbook)
        }
        if ($null -ne $application) {
            try { [void](Invoke-ComWithRetry { $application.Quit() }) } catch {}
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
        Stop-OwnedOfficeProcesses $officeProcessIds
    }
}

if (-not (Test-Path -LiteralPath $outputFull)) {
    throw "Office conversion did not create output: $outputFull"
}
