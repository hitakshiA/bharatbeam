# BharatBeam Demo Script — 90 Seconds

Pre-recording: Open these 4 tabs in Chrome, in order:
1. https://bharatbeam.vercel.app (video paused at 0:00)
2. https://github.com/hitakshiA/bharatbeam
3. https://www.business-standard.com/india-news/india-road-accidents-deaths-injuries-report-road-highway-ministry-nitin-gadkari-125082801527_1.html
4. https://www.ti.com/product/TPS92662-Q1 (TI product page for LED matrix manager)

Screen Studio settings: 1920x1080, 60 FPS, cursor highlight ON

---
## [0:00-0:08] HOOK

On screen: Dashboard loaded, video paused at 0:00. Beam segments all green (full beam). Hold for 2 seconds before speaking.

> "This is BharatBeam — a 12-segment adaptive driving beam system designed for Indian roads. Everything you're about to see is running on real nighttime dashcam footage from Bangalore. The beam controller responds to confirmed vehicle detections in under 50 milliseconds."

Click play on the video.

---
## [0:08-0:30] LIVE BEAM RESPONSE

Video is playing. An oncoming vehicle approaches around 0:05-0:08. Watch the beam bars respond.

> "Watch the beam segment visualizer on the right. Each bar represents one LED segment in the headlamp array, controlled by a TI TPS92662-Q1 matrix manager."

Point cursor at the beam segment bars as they dim (turn red/orange) when a vehicle is detected.

> "There — oncoming headlight detected. Segments 6 and 7 dim to 8% PWM. That's the glare corridor. But look at the other 10 segments — they stay at full brightness. The road, the shoulders, the pedestrian on the left — all still illuminated."

Point at the road illumination top-down view.

> "This is the fundamental difference from a binary dipper. A dipper kills your entire forward view. BharatBeam creates a surgical shadow corridor around one vehicle while maintaining 83% road illumination."

---
## [0:30-0:50] MODE COMPARISON

Click "High beam only" mode tab.

> "Now watch what happens without ADB."

Point at the beam bars — all go to 100% green.

> "High beam only. Every segment at full power. The driver ahead of you is blinded. 73% of Indian drivers do exactly this — ArriveSafe measured it across 3,200 vehicles on Punjab highways."

Click "Low beam only" mode tab.

> "And the alternative."

Point at the beam bars — all drop to 12%.

> "Low beam. You can't see anything beyond 40 meters. IIT Delhi's TRIP Centre found that crude auto-dippers that switch to low beam actually increase pedestrian deaths — you stop blinding the oncoming driver but you also stop seeing the cyclist on the shoulder."

Click back to "BharatBeam ADB" mode.

> "BharatBeam solves both. Selective dimming. The oncoming driver doesn't get blinded. The cyclist stays illuminated."

---
## [0:50-1:10] ARCHITECTURE AND COST

Point at the architecture strip at the top.

> "Here's the system architecture. The ADAS camera is already on the vehicle — Nexon, XUV700, Creta, Seltos all have one. The ADAS ECU generates an object list. We add one component."

Point at "Controller: NXP S32K312" in the strip.

> "The BharatBeam controller. An NXP S32K312 — automotive-grade Cortex-M7 with CAN FD and SPI. Three dollars fifty. It receives vehicle detections over CAN, computes beam patterns, and drives the TPS92662-Q1 LED matrix manager."

Point at the System Specification panel.

> "Total add-on BOM: twelve to eighteen dollars. Zero incremental sensor cost. The camera is already there. European ADB costs thirty-four hundred to sixty-six hundred dollars. We're two orders of magnitude cheaper."

---
## [1:10-1:25] INDIAN TRAFFIC INTELLIGENCE

Seek the video to around 2:55 where urban traffic has multiple detections. Let it play.

> "Now here's what European ADB cannot do."

Point at the detection boxes appearing on vehicles.

> "Indian traffic has 24 object categories — auto-rickshaws, bullock carts, cycle rickshaws, stray cattle. All absent from European training sets. BharatBeam is trained on IDD, DriveIndia, and DATS 2022 — Indian datasets from IIT Hyderabad and Pune."

Point at the CAN FD bus monitor as messages scroll.

> "Every detection generates a CAN FD message — object type, position, estimated distance. The beam controller processes the full object list in under 50 milliseconds."

---
## [1:25-1:35] CLOSE

Seek back to a moment with clear beam dimming visible (around 0:33). Let the dashboard run.

> "BharatBeam. Twelve-segment adaptive driving beam for Indian roads. Twelve to eighteen dollars add-on BOM. AIS-199 compliant. Plugs into Varroc's existing LED headlamp modules. Ready for the 4 million cars India produces every year."

Let the dashboard animate with beam bars responding for 3 seconds. End recording.

---
## Tips
- The money shots are mode switching (0:30-0:50) — the visual contrast between all-green, all-red, and selective dimming is immediately compelling
- When an oncoming vehicle is detected, the beam bars turning red while others stay green IS the demo — make sure you're pointing at it
- Scrub the video to moments with bright oncoming headlights (0:30, 1:02, 2:23) for maximum visual impact
- The CAN FD monitor scrolling with live messages proves this isn't a pre-baked animation
- End on the live dashboard with beam bars actively responding — last frame should be motion, not static
- Don't rush the mode comparison — the "what if we don't have this" argument sells the product
