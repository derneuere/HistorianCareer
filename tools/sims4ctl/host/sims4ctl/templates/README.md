# Recipe B button templates

This directory holds the calibrated button-template PNG crops referenced by
`../automation_config.json` (`targets.*.template`). It ships empty: every
template is captured **live** with

```
sims4ctl calibrate --out window.png --crop continue 600 380 760 430
```

(coordinates are client-local pixels read off the captured `window.png`).

Until a template exists here, target resolution falls back to the `norm`
(normalized client-fraction) coordinates in the config, which must also be
calibrated. See `../../../docs/RECIPE_B.md` -> "Calibration".

Template matching is resolution/UI-scale sensitive, so pin the game to a fixed
windowed resolution + `uiscale=100` (in `Options.ini`, game closed) before
capturing, and re-capture if you change either.
