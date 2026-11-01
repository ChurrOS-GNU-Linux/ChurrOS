# Memory and zram

ChurrOS uses `zram-generator` to provide compressed swap. This adds headroom during memory pressure; it does not by itself reduce the desktop's resident memory. Every edition packages `zram-generator` alongside the shared `archiso/airootfs/etc/systemd/zram-generator.conf` configuration.

## Inspect a Live session or installation

After login, run:

```sh
free -h
swapon --show
zramctl
ps -eo pid,comm,rss --sort=-rss | head -20
systemd-cgtop --batch --iterations=1 --depth=3
```

`MemAvailable` is more useful than adding free memory and caches. RSS is resident memory per process and can count shared pages more than once, so do not treat its sum as exclusive physical use. `zramctl`'s `DATA`, `COMPR`, and `TOTAL` help distinguish compressed data from physical memory occupied.

## Repeatable QEMU profile

`tests/vm/boot_smoke.py` starts the ISO with 4096 MiB by default, waits for the system and Live session, then records `/proc/meminfo`, active swap, zram statistics, and the 20 processes with the highest RSS in `report.json`. The report includes edition and VM memory. The smoke test also checks that `/dev/zram0` is active.

To test a different capacity, pass `--memory MIB`, for example `--memory 2048`. Compare Niri and XFCE with the same architecture, ISO/base, VM memory, firmware, QEMU acceleration, and post-login state. Keep the `server` profile separate because it has no desktop. ISO workflows upload boot reports as artifacts; static tests alone do not produce measurements.

QEMU profiles allow comparisons under the same virtual environment; they do not predict exact physical-hardware usage or justify removing services. Do not disable the compositor, portal, Polkit, session manager, networking, or startup apps based on their names: collect before/after data and test related functions first. Issue #288 tracks potential desktop optimizations that require real comparison.

## Baseline captured in CI (2026-11-01)

The Niri and XFCE ISO workflows on commit `608670ddc8c16c0e2a1b6aac7981c7c194fd59df` both completed UEFI and BIOS QEMU boots with KVM/virgl and 4096 MiB assigned. In the UEFI profiles, Niri reported 3122.0 MiB `MemAvailable` and 217.6 MiB `AnonPages`; XFCE reported 2989.1 MiB `MemAvailable` and 335.3 MiB `AnonPages`. Both reported active `/dev/zram0` with zero swap used. BIOS profiles were similar. The Niri snapshot was collected after the normal smoke-test login while its welcome window was open; XFCE was captured at the same post-login stage.

These are indicative CI snapshots, not a controlled benchmark: the ISO builds use rolling package repositories and the QEMU reports do not predict physical hardware. `AnonPages` is a system-wide memory category, not a sum of process RSS. No service or user-facing feature was removed based on this single comparison; it does not provide enough before/after evidence to justify such a tradeoff. The workflows and their downloadable reports are [XFCE run 41335132856](https://github.com/ChurrOS-GNU-Linux/ChurrOS/actions/runs/41335132856) and [Niri run 41335132755](https://github.com/ChurrOS-GNU-Linux/ChurrOS/actions/runs/41335132755).
