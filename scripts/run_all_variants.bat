@echo off
REM Run all experiment variants on full-range-2017-2024 sequentially.
REM Run this from the crypto-grid-bot directory:
REM   cd crypto-grid-bot
REM   scripts\run_all_variants.bat
REM Each variant takes ~1 hour. Total: ~10 hours.

echo === full-range-2017-2024: all variants ===
echo Started: %DATE% %TIME%

echo.
echo [V0] Running baseline...
python scripts/run_nopool.py full-range-2017-2024
echo [V0] Done: %TIME%

echo.
echo [A] Running variant-a...
python scripts/run_nopool.py full-range-2017-2024 --variant-a
echo [A] Done: %TIME%

echo.
echo [B] Running variant-b...
python scripts/run_nopool.py full-range-2017-2024 --variant-b
echo [B] Done: %TIME%

echo.
echo [C] Running variant-c...
python scripts/run_nopool.py full-range-2017-2024 --variant-c
echo [C] Done: %TIME%

echo.
echo [E] Running variant-e...
python scripts/run_nopool.py full-range-2017-2024 --variant-e
echo [E] Done: %TIME%

echo.
echo [F] Running variant-f...
python scripts/run_nopool.py full-range-2017-2024 --variant-f
echo [F] Done: %TIME%

echo.
echo [G] Running variant-g...
python scripts/run_nopool.py full-range-2017-2024 --variant-g
echo [G] Done: %TIME%

echo.
echo [H] Running variant-h...
python scripts/run_nopool.py full-range-2017-2024 --variant-h
echo [H] Done: %TIME%

echo.
echo [C+G] Running variant-cg...
python scripts/run_nopool.py full-range-2017-2024 --variant-cg
echo [C+G] Done: %TIME%

echo.
echo [C+H] Running variant-ch...
python scripts/run_nopool.py full-range-2017-2024 --variant-ch
echo [C+H] Done: %TIME%

echo.
echo === All variants complete: %DATE% %TIME% ===
echo Results in: data\backtests\full-range-2017-2024\
