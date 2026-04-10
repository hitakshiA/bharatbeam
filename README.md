# BharatBeam — India's First Affordable Adaptive Driving Beam

> Varroc Eureka 3.0 Challenge | Problem Statement 6: Automotive lighting optimization for poor road infrastructure and high glare conditions in India

India's roads kill 473 people every day. Nearly half those deaths happen at night, when 74% of drivers blast high beams at oncoming traffic because the alternative is driving blind on unlit roads. European ADB systems solve this with million-pixel headlamps costing $3,400-$6,600 per vehicle — representing 23-83% of an Indian car's price. They also fail on Indian roads where bullock carts, auto-rickshaws, and stray cattle share unmarked lanes.

BharatBeam is a **12-segment adaptive driving beam controller** that plugs into Varroc's existing LED headlamp modules at a **$12-18 add-on BOM cost**, leveraging the ADAS camera already deployed on 15+ Indian vehicle models.

## Live Demo

**[bharatbeam.vercel.app](https://bharatbeam.vercel.app)** — Real-time simulation running on actual Indian nighttime dashcam footage.

## How It Works

```
ADAS Camera (already on vehicle)
    ↓ GMSL/FPD-Link III coax
ADAS ECU (existing Mobileye/Continental)
    ↓ CAN FD: object type, position, distance
BharatBeam Controller (NXP S32K312, $3-4.50)
    ↓ SPI bus
TPS92662-Q1 Matrix LED Manager (12 channels)
    ↓ PWM dimming per segment
Varroc LED Headlamp Module (existing multi-segment array)
```

The system operates in two simultaneous modes:

**Mode 1 — Adaptive Glare Management:** The ADAS ECU detects oncoming and preceding vehicles. Object data is transmitted to the BharatBeam controller over CAN FD. The controller maps each detected vehicle to specific LED segments and dims only the 1-3 segments that would project light into the detected vehicle's driver zone. Remaining segments maintain full high-beam intensity, keeping the road, shoulders, and obstacles fully illuminated.

**Mode 2 — Road Hazard Highlighting:** The same camera feed is analyzed for road surface anomalies using classical shadow-based computer vision. Detected potholes, pedestrians, stray animals, and road barriers trigger selective beam highlighting — the segment illuminating that zone increases intensity briefly to draw driver attention. This directly addresses the PS6 scope requirement for identifying poor road conditions earlier.

## Why Not European ADB?

| | Current Indian (Auto HBA) | European ADB (Mercedes DIGITAL LIGHT) | BharatBeam |
|---|---|---|---|
| Beam segments | 1 (on/off) | 1,300,000 pixels | 12-24 segments |
| Response | Binary switch | Continuous | Continuous per-segment |
| Cost premium | $0 | $3,400-6,600 | $12-18 |
| Indian object recognition | No | No (trained on EU data) | Yes (IDD/DriveIndia datasets) |
| Hazard highlighting | No | Limited | Pothole + animal + pedestrian |
| Regulatory | AIS-010 | Not approved in India | AIS-199 compliant |

European ADB cameras are trained to detect 5-8 Western traffic object types. Indian roads have 24+ categories including bullock carts, cycle rickshaws, e-rickshaws, hand carts, and free-roaming cattle — all absent from European training sets. Indian roads lack lane markings entirely. European ADB's lane-light features cannot function.

## The Numbers That Matter

- **172,890** road fatalities in India in 2023. 48.5% at night.
- **73.8%** of drivers use high beams on highways (ArriveSafe study, 3,200 vehicles)
- **IIT Delhi TRIP Centre finding:** crude auto-dippers that simply switch to low beam INCREASE pedestrian deaths by reducing illumination of unlit road users
- **AIS-199** (India's UN R149 adoption) approved April 2024 — ADB legalization expected mid-2026
- **$12-18** add-on BOM using existing ADAS camera. Zero incremental sensor cost.
- **24-pixel matrix arrays** already in Indian production. Supply chain ready.

## Component Selection

| Component | Part | Justification | Unit Cost |
|---|---|---|---|
| Headlamp Controller | NXP S32K312 | Automotive Cortex-M7, CAN FD, SPI, ASIL B | $3-4.50 |
| LED Matrix Manager | TI TPS92662-Q1 | 12-ch individually addressable PWM, cascade to 24+, AEC-Q100 | $3-5 |
| LED Current Source | Infineon TLD5541-1QV | >90% efficiency DC-DC, automotive qualified | $3-5 |
| Connectors/passives | Various | FAKRA coax, Molex sealed connector | $2-3 |
| **Total add-on BOM** | | | **$12-18** |

Camera sensor ($4-7) is NOT counted — it's already on the vehicle for ADAS.

## Simulation

This repository contains a simulation that demonstrates BharatBeam's behavior on real Indian nighttime dashcam footage:

### Processing Pipeline (`process_video.py`)

Processes raw dashcam video frame-by-frame:
1. **Object detection** — identifies vehicles, pedestrians, cyclists, animals
2. **Brightness blob detection** — catches headlight sources via intensity thresholding with compactness and peak brightness filtering
3. **Temporal persistence** — only detections present for 0.4+ seconds are confirmed (filters transient reflections, lens flare, road glow)
4. **12-segment beam controller** — maps detections to beam segments, computes PWM dimming with smooth transitions
5. **Simulated CAN FD messages** — generates realistic message traffic
6. **Full JSON logging** — per-frame data for frontend playback

### Frontend Dashboard (`frontend/`)

Next.js application that plays the processed video synchronized with:
- **12-segment beam visualizer** — shows PWM state per segment in real-time
- **Road illumination pattern** — top-down view of beam cones
- **System metrics** — vehicles detected, segments dimmed, glare reduction, road illumination, latency
- **CAN FD bus monitor** — live message scroll
- **Mode comparison** — toggle between BharatBeam ADB, dumb high beam, and low beam only

### Running Locally

```bash
# 1. Process video (requires Python 3.10+, ~2 min for 5-min footage)
pip install opencv-python ultralytics
python process_video.py --input your_dashcam.mp4 --output output/ --every 2

# 2. Copy outputs to frontend
cp output/segments_timeline.json frontend/public/data/
cp output/processed_video.mp4 frontend/public/data/  # re-encode with ffmpeg for browser

# 3. Run frontend
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

## Business Potential

- India produces ~4 million passenger vehicles and ~25 million two-wheelers annually
- Automotive lighting market: ~$2.5B, growing 15%+ CAGR
- At $12-18 BOM, BharatBeam headlamps sell at $60-90 retail — **$40-60 gross margin per unit**
- Immediate addressable: ~500K-800K ADAS-equipped units/year (Nexon, XUV700, Creta, Seltos, Honda Amaze)
- Strategic value: moves Varroc from commodity headlamp supplier to intelligent lighting solutions provider

## Regulatory Context

- **AIS-010**: Current headlamp standard. Max 350cd at B50L glare point, min 10,100cd at 75R.
- **AIS-199**: India's adoption of UN R149. Approved April 2024, ADB legalization expected mid-2026.
- **AIS-008 Rev.3**: Mandates auto headlamp levelling for LED >2,000 lumens. Permits AFLS as optional.
- BharatBeam is designed for AIS-199 compliance, with fallback to enhanced auto HBA under AIS-010.

## Team

Varroc Eureka 3.0 Challenge — Problem Statement 6

## License

MIT
