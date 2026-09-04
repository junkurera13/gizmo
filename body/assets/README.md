# Offline body assets

`export_bundle.py` converts the current source drawings into a local boot/home
bundle for one explicit panel profile. The output is intended for device flash or
other body-local storage, so cold boot does not wait for Wi-Fi or the brain.

```bash
.venv/bin/python body/assets/export_bundle.py \
  --width 320 --height 240 \
  --output data/body-assets/320x240
```

The dimensions are provisional input, not a selected Gizmo screen. Re-run the
exporter for the actual panel. It deduplicates the current boot sequence into
content-addressed baseline JPEG files, including the baked 1.25-second drop and
unchanged blink sequence. The bundle also carries the 24 kHz mono PCM16 chime, a
composited home base, small heart assets, a clock glyph atlas, hashes, timing, and
a manifest. Time, battery and their resources are scoped to home only.

The reference loader verifies every hash and dimension and can exercise the full
offline timing without a brain connection:

```bash
.venv/bin/python body/reference/offline_assets.py \
  data/body-assets/320x240 --realtime
```

This bundle establishes delivery and bounded encoded storage. The selected board
still needs a JPEG decoder, display driver, audio output, dynamic clock/battery
rendering, and measured memory/timing. Source drawings remain in `glass/` and are
never rewritten by the exporter.
