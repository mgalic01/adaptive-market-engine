$variants = @(
    @{ flag = "";            log = "data\run-v0.log"  },
    @{ flag = "--variant-a"; log = "data\run-a.log"   },
    @{ flag = "--variant-b"; log = "data\run-b.log"   },
    @{ flag = "--variant-c"; log = "data\run-c.log"   },
    @{ flag = "--variant-e"; log = "data\run-e.log"   },
    @{ flag = "--variant-f"; log = "data\run-f.log"   },
    @{ flag = "--variant-g"; log = "data\run-g.log"   },
    @{ flag = "--variant-h"; log = "data\run-h.log"   },
    @{ flag = "--variant-cg"; log = "data\run-cg.log" },
    @{ flag = "--variant-ch"; log = "data\run-ch.log" }
)

$spec = $args[0]
if (-not $spec) { $spec = "full-range-2017-2024" }

foreach ($v in $variants) {
    $label = if ($v.flag) { $v.flag } else { "V0" }
    Write-Host "$(Get-Date -Format 'HH:mm:ss') Starting $label ..." -ForegroundColor Cyan
    if ($v.flag) {
        python scripts/run_nopool.py $spec $v.flag 2>&1 | Tee-Object -FilePath $v.log
    } else {
        python scripts/run_nopool.py $spec 2>&1 | Tee-Object -FilePath $v.log
    }
    Write-Host "$(Get-Date -Format 'HH:mm:ss') Done $label" -ForegroundColor Green
}
Write-Host "All variants complete." -ForegroundColor Yellow
