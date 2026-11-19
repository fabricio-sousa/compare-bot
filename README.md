# Console Compare

A Python script that scans your Windows PC and shows how it stacks up against the two most powerful consoles you can buy today: the **Xbox Series X** and the **PlayStation 5 Pro**.

It tells you, in plain English, whether your PC is ahead, on par with or behind each console. It also tells you what to expect in new games and what's holding your PC back.

## Features

- **Hardware scan.** Detects your processor, graphics card, graphics memory (VRAM), system RAM, drives, display and Windows version.
- **Real boost clock.** Windows normally reports only a processor's base clock. The script briefly loads one core and reads the actual boosted speed, so your processor isn't underrated.
- **Side-by-side spec table.** Compares processor, graphics, memory, storage, ray tracing and upscaling (DLSS / FSR / XeSS vs. the PS5 Pro's PSSR).
- **Performance bars and verdicts.** Rates graphics and processor as *Ahead*, *On par* or *Behind*, with a ratio for each console.
- **Plain-English summary.** Covers likely resolution and settings, processor bottlenecks, low graphics memory, low RAM and slow drives.
- **Upgrade suggestions.** If your graphics card is below PS5 Pro level, lists current-generation cards that match or beat it.
- **No dependencies.** Uses only the Python standard library and PowerShell, which comes with Windows.

## Requirements

- Windows 10 or 11
- Python 3.8 or newer ([python.org](https://www.python.org/downloads/))
- PowerShell (built into Windows)

Admin rights are not needed.

## Usage

Open Command Prompt or PowerShell in the folder that holds `console_compare.py`, then run:

```
python console_compare.py
```

The scan takes about 5–10 seconds.

### Options

| Option | What it does |
|---|---|
| `--save report.txt` | Also save the report to a text file |
| `--json` | Print the results as JSON instead of the report |
| `--gpu "RTX 3070"` | Set your graphics card by hand if it isn't recognized |
| `--no-boost` | Skip the 2-second processor boost-clock check |
| `--no-color` | Turn off colored output |
| `--demo` | Show the report with sample PC data (works on any OS) |

### Examples

```
python console_compare.py --save my_pc_report.txt
python console_compare.py --gpu "RX 6700 XT"
python console_compare.py --json > results.json
```

## Sample output

```
  ESTIMATED PERFORMANCE (longer bar = faster)
  Graphics
    Your PC        #######################.......     125
    Xbox Series X  #####################.........     118
    PS5 Pro        ###########################...     150
  Processor
    Your PC        ###########################...    39.0
    Xbox Series X  ########################......    35.0
    PS5 Pro        ##########################....    36.8

  HEAD TO HEAD
  vs Xbox Series X  Graphics: On par (1.06x)   Processor: On par (1.11x)
  vs PS5 Pro        Graphics: Behind (0.83x)   Processor: On par (1.06x)

  WHAT THIS MEANS
  * Your PC is console-class: roughly Xbox Series X level, a bit under the PS5 Pro.
    Console-like settings at 1440p, or 4K with upscaling, are a good target.
  * 8 GB of graphics memory is fine for 1080p-1440p, but some new games at
    console-level textures want 10-12 GB+ (consoles share ~13.5 GB).
  * Current-gen cards at or above PS5 Pro level include: RX 9060 XT, RTX 5060 Ti, RTX 5070.
```

*(Sample: Ryzen 5 5600X, RTX 3060 Ti 8 GB, 32 GB DDR4, NVMe SSD.)*

## Console specs used

| | Xbox Series X | PS5 Pro |
|---|---|---|
| Processor | AMD Zen 2, 8 cores / 16 threads @ 3.66 GHz | AMD Zen 2, 8 cores / 16 threads @ 3.5–3.85 GHz |
| Graphics | AMD RDNA 2, 52 CUs, 12.15 TFLOPS | AMD RDNA, 60 CUs, ~16.7 TFLOPS* |
| Memory | 16 GB GDDR6 shared (~13.5 GB for games) | 16 GB GDDR6 @ 576 GB/s + 2 GB DDR5 for the OS |
| Storage | 1 TB NVMe, 2.4 GB/s raw | 2 TB NVMe, 5.5 GB/s raw |
| Upscaling | FSR (software) | PSSR (AI upscaling) |
| Roughly equal PC graphics card | RX 6700 / RTX 2070 Super | RX 7700 XT / RTX 3070 |

\* Sony's advertised 33.5 TFLOPS counts dual-issue FP32. ~16.7 TFLOPS is the like-for-like figure.

The Xbox Series X25 Limited Edition uses the same chip as the Series X, so the results apply to it too. Microsoft's next Xbox (Project Helix) hasn't launched yet.

## How the scores work

**Graphics index.** A built-in table rates over 100 desktop, laptop and integrated graphics chips on one scale, where **RTX 3060 12 GB = 100**. The scores are based on typical gaming (rasterization) performance. Laptop graphics chips are scaled down by 25% because they run at much lower power.

**Processor score.** Calculated as:

```
(physical cores + 0.3 × extra threads) × clock speed (GHz) × architecture factor
```

The architecture factor accounts for how much work each generation does per clock, with Zen 2 = 1.00. For example, Zen 3 is 1.18, Zen 4 is 1.30 and Intel 12th–14th gen is 1.25. The script works out the generation from the processor's model name. The consoles' Zen 2 chips get a 0.92 factor because they have much less cache than desktop Zen 2.

**Verdicts.** Compared with each console:
- **Ahead:** 15% or more faster
- **On par:** between 10% slower and 15% faster
- **Behind:** more than 10% slower

## Accuracy and limitations

- **These are estimates, not benchmarks.** Real results vary by game, settings and drivers. Console games are also tuned to fixed hardware, so a PC usually needs a bit more power to match a console's results.
- **Drive speed is inferred from the drive type**, not tested. The estimates are NVMe ≈ 3.5 GB/s, SATA SSD ≈ 0.55 GB/s and hard drive ≈ 0.15 GB/s.
- **Very new or unusual graphics cards** may show as unknown. Use `--gpu "<model>"` to set yours by hand.
- **The boost-clock check** reads a Windows performance counter by its English name. On non-English Windows it may fail and fall back to the base clock. The report says so when that happens.
- **Graphics memory** is read from `nvidia-smi` (NVIDIA cards) or the display driver's registry entry, because the standard Windows value tops out at 4 GB.

## Updating the data

All the numbers are near the top of `console_compare.py`, so they're easy to change:

- `CONSOLES`: console specs and performance index
- `GPU_INDEX`: graphics card performance scores (add new cards here)
- `CURRENT_GPUS`: cards eligible for upgrade suggestions
- `IPC`: processor architecture factors

## License

Free to use and modify for personal use.
