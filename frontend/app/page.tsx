"use client";

import { useEffect, useRef, useState, useCallback } from "react";

/* ═══════════════════════════════════════════
   TYPES
   ═══════════════════════════════════════════ */

interface TimelineFrame {
  t: number;
  pwm: number[];
  reasons: string[];
  nv: number;
  nh: number;
  gr: number;
  ri: number;
  lat: number;
  sd: number;
}

interface TimelineData {
  fps: number;
  num_segments: number;
  total_frames: number;
  duration_s: number;
  timeline: TimelineFrame[];
}

/* ═══════════════════════════════════════════
   BEAM SEGMENT VISUALIZER — full height bars
   ═══════════════════════════════════════════ */

function BeamVisualizer({ segments, reasons }: { segments: number[]; reasons: string[] }) {
  return (
    <div className="flex gap-1 h-full items-end px-1 pb-1">
      {segments.map((pwm, i) => {
        const reason = reasons[i];
        const height = `${Math.max(8, pwm * 100)}%`;

        // Bright, clearly visible colors
        let bg: string;
        if (reason === "hazard_highlight") {
          bg = "#f59e0b"; // bright amber
        } else if (reason === "dim_oncoming") {
          bg = pwm < 0.15 ? "#dc2626" : "#f97316"; // red or orange
        } else if (reason === "dim_preceding") {
          bg = "#3b82f6"; // blue
        } else {
          bg = "#d4a030"; // warm gold — clearly visible on dark bg
        }

        return (
          <div key={i} className="flex-1 flex flex-col items-center gap-1.5">
            <div
              className="w-full rounded relative overflow-hidden"
              style={{ height: "100%", background: "#1a1510", border: "1px solid #2a2318" }}
            >
              <div
                className="absolute bottom-0 w-full rounded transition-all"
                style={{
                  height,
                  background: bg,
                  transitionDuration: "120ms",
                  transitionTimingFunction: "cubic-bezier(0.25, 1, 0.5, 1)",
                  boxShadow: `0 0 8px ${bg}44`,
                }}
              />
            </div>
            <span className="text-[11px] font-semibold tabular-nums" style={{ color: "#b8a080" }}>
              {(pwm * 100).toFixed(0)}
            </span>
            <span className="text-[10px] font-medium" style={{ color: "#6b5c4a" }}>
              S{i + 1}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════════════════════
   ROAD ILLUMINATION TOP-DOWN VIEW
   ═══════════════════════════════════════════ */

function RoadView({ segments, reasons }: { segments: number[]; reasons: string[] }) {
  return (
    <svg viewBox="0 0 400 220" className="w-full h-full">
      {/* Road surface */}
      <rect x="40" y="15" width="320" height="170" rx="3" fill="oklch(12% 0.01 60)" stroke="oklch(20% 0.01 60)" strokeWidth="0.5" />

      {/* Lane dashes */}
      {[30, 55, 80, 105, 130, 155].map((y) => (
        <line key={y} x1="200" y1={y} x2="200" y2={y + 14} stroke="oklch(25% 0.01 60)" strokeWidth="1.5" strokeDasharray="5 8" />
      ))}

      {/* Vehicle at bottom */}
      <rect x="182" y="160" width="36" height="20" rx="3" fill="oklch(22% 0.01 60)" stroke="oklch(35% 0.01 60)" strokeWidth="0.5" />

      {/* Beam cones */}
      {segments.map((pwm, i) => {
        const segW = 320 / 12;
        const x1 = 40 + i * segW;
        const x2 = x1 + segW;
        const reason = reasons[i];

        let fill: string;
        if (reason === "dim_oncoming") {
          fill = `oklch(35% 0.06 25 / ${(1 - pwm) * 0.45})`;
        } else if (reason === "hazard_highlight") {
          fill = "oklch(70% 0.15 60 / 0.4)";
        } else if (reason === "dim_preceding") {
          fill = `oklch(45% 0.06 240 / ${(1 - pwm) * 0.25})`;
        } else {
          fill = `oklch(65% 0.1 70 / ${pwm * 0.25})`;
        }

        const carL = 182 + (i / 12) * 36;
        const carR = 182 + ((i + 1) / 12) * 36;

        return (
          <polygon
            key={i}
            points={`${x1},15 ${x2},15 ${carR},160 ${carL},160`}
            fill={fill}
          />
        );
      })}

      <text x="200" y="10" textAnchor="middle" fill="oklch(35% 0.01 60)" fontSize="7" fontFamily="var(--font-instrument), sans-serif">80m+</text>
      <text x="200" y="210" textAnchor="middle" fill="oklch(35% 0.01 60)" fontSize="7" fontFamily="var(--font-instrument), sans-serif">Vehicle</text>
    </svg>
  );
}

/* ═══════════════════════════════════════════
   CAN BUS MONITOR
   ═══════════════════════════════════════════ */

function CANMonitor({ frame, frameIndex }: { frame: TimelineFrame | null; frameIndex: number }) {
  const logRef = useRef<HTMLDivElement>(null);

  const messages = frame
    ? frame.pwm
        .map((pwm, i) => {
          if (frame.reasons[i] === "dim_oncoming") {
            return { id: "0x1A0", type: "ONCOMING", seg: i, pwm: (pwm * 100).toFixed(0), color: "#ef4444" };
          } else if (frame.reasons[i] === "dim_preceding") {
            return { id: "0x1A1", type: "PRECEDING", seg: i, pwm: (pwm * 100).toFixed(0), color: "#60a5fa" };
          } else if (frame.reasons[i] === "hazard_highlight") {
            return { id: "0x1A2", type: "HAZARD", seg: i, pwm: (pwm * 100).toFixed(0), color: "#f59e0b" };
          }
          return null;
        })
        .filter(Boolean)
    : [];

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [frameIndex]);

  return (
    <div ref={logRef} className="text-xs leading-5 h-full overflow-y-auto">
      {messages.length === 0 && (
        <div style={{ color: "#6b5c4a" }}>All segments full beam — no CAN traffic</div>
      )}
      {messages.map((msg, i) => (
        <div key={i} className="flex gap-2 tabular-nums">
          <span style={{ color: "#6b5c4a" }}>{frame!.t.toFixed(3)}</span>
          <span style={{ color: "#8a7a65" }}>{msg!.id}</span>
          <span style={{ color: msg!.color }}>{msg!.type}</span>
          <span style={{ color: "#8a7a65" }}>S{msg!.seg + 1}</span>
          <span style={{ color: "#c4b498" }}>{msg!.pwm}%</span>
        </div>
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════════
   METRICS GRID
   ═══════════════════════════════════════════ */

function Metrics({ frame, mode }: { frame: TimelineFrame | null; mode: string }) {
  if (!frame) return null;

  const items = [
    { label: "Vehicles", val: String(frame.nv), active: frame.nv > 0 },
    { label: "Hazards", val: String(frame.nh), active: frame.nh > 0, warn: frame.nh > 0 },
    { label: "Dimmed", val: mode === "bharatbeam" ? `${frame.sd}/12` : mode === "high_beam" ? "0/12" : "12/12", active: frame.sd > 0 },
    { label: "Glare blocked", val: mode === "bharatbeam" ? `${frame.gr.toFixed(0)}%` : "0%", active: frame.gr > 0 },
    { label: "Road illuminated", val: mode === "bharatbeam" ? `${frame.ri.toFixed(0)}%` : mode === "high_beam" ? "100%" : "25%", active: true },
    { label: "Latency", val: `${frame.lat.toFixed(1)}ms`, active: true },
  ];

  return (
    <div className="grid grid-cols-3 gap-2">
      {items.map((m) => (
        <div key={m.label} className="py-2.5 px-3" style={{ background: "#141210", borderRadius: "5px", border: "1px solid #2a2318" }}>
          <div className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "#8a7a65" }}>
            {m.label}
          </div>
          <div
            className="text-xl font-bold mt-1 tabular-nums"
            style={{
              color: m.warn ? "#ef4444" : m.active ? "#e8dcc8" : "#5a4f40",
            }}
          >
            {m.val}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════════
   MODE TABS
   ═══════════════════════════════════════════ */

function ModeTabs({ mode, setMode }: { mode: string; setMode: (m: string) => void }) {
  const modes = [
    { id: "bharatbeam", label: "BharatBeam ADB" },
    { id: "high_beam", label: "High beam only" },
    { id: "low_beam", label: "Low beam only" },
  ];

  return (
    <div className="flex p-0.5 gap-0.5" style={{ background: "oklch(12% 0.008 60)", borderRadius: "6px" }}>
      {modes.map((m) => (
        <button
          key={m.id}
          onClick={() => setMode(m.id)}
          className="px-3 py-1.5 text-[11px] font-medium transition-all cursor-pointer"
          style={{
            borderRadius: "4px",
            background: mode === m.id ? "oklch(20% 0.012 60)" : "transparent",
            color: mode === m.id
              ? m.id === "bharatbeam" ? "oklch(75% 0.12 65)" : "var(--text-primary)"
              : "var(--text-muted)",
            fontFamily: "var(--font-instrument), sans-serif",
            transitionDuration: "150ms",
          }}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════════
   PANEL WRAPPER
   ═══════════════════════════════════════════ */

function Panel({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`flex flex-col ${className}`}
      style={{
        background: "oklch(11% 0.008 60)",
        border: "1px solid oklch(18% 0.01 60)",
        borderRadius: "6px",
      }}
    >
      <div
        className="px-3 py-2 flex items-center justify-between shrink-0"
        style={{ borderBottom: "1px solid oklch(16% 0.008 60)" }}
      >
        <span
          className="text-xs uppercase tracking-wider font-semibold"
          style={{ color: "#a89578" }}
        >
          {title}
        </span>
      </div>
      <div className="flex-1 p-3 min-h-0">{children}</div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   ARCHITECTURE STRIP
   ═══════════════════════════════════════════ */

function ArchStrip() {
  const steps = [
    { label: "Camera", sub: "OV2775", wire: "GMSL" },
    { label: "ADAS ECU", sub: "Existing (Mobileye/Continental)", wire: "CAN FD" },
    { label: "Controller", sub: "NXP S32K312", wire: "SPI" },
    { label: "LED Driver", sub: "TPS92662-Q1", wire: "PWM" },
    { label: "Headlamp", sub: "12-seg array", wire: null },
  ];

  return (
    <div className="flex items-center gap-0 px-4 py-2 overflow-x-auto">
      {steps.map((s, i) => (
        <div key={i} className="flex items-center shrink-0">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide" style={{ color: "#d4a030" }}>
              {s.label}
            </div>
            <div className="text-[10px]" style={{ color: "#8a7a65" }}>{s.sub}</div>
          </div>
          {s.wire && (
            <div className="flex items-center mx-2">
              <div className="w-5 h-px" style={{ background: "oklch(22% 0.01 60)" }} />
              <span className="text-[7px] px-1 py-px mx-0.5 uppercase tracking-widest" style={{ color: "var(--text-muted)", background: "oklch(14% 0.008 60)", borderRadius: "2px" }}>
                {s.wire}
              </span>
              <div className="w-5 h-px" style={{ background: "oklch(22% 0.01 60)" }} />
            </div>
          )}
        </div>
      ))}
      <div className="ml-auto shrink-0 text-[10px]" style={{ color: "var(--text-muted)" }}>
        BOM $12–18 &middot; AIS-199
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   MAIN PAGE
   ═══════════════════════════════════════════ */

export default function Home() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [currentFrame, setCurrentFrame] = useState(0);
  const [mode, setMode] = useState("bharatbeam");
  const [isPlaying, setIsPlaying] = useState(false);
  const animRef = useRef<number>(0);

  useEffect(() => {
    fetch("/data/segments_timeline.json")
      .then((r) => r.json())
      .then((data: TimelineData) => setTimeline(data))
      .catch(console.error);
  }, []);

  const sync = useCallback(() => {
    if (!videoRef.current || !timeline) return;
    const idx = Math.min(Math.floor(videoRef.current.currentTime * timeline.fps), timeline.total_frames - 1);
    setCurrentFrame(idx);
    if (!videoRef.current.paused) animRef.current = requestAnimationFrame(sync);
  }, [timeline]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onPlay = () => { setIsPlaying(true); animRef.current = requestAnimationFrame(sync); };
    const onPause = () => { setIsPlaying(false); cancelAnimationFrame(animRef.current); };
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("seeked", sync);
    v.addEventListener("timeupdate", sync);
    return () => {
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("seeked", sync);
      v.removeEventListener("timeupdate", sync);
      cancelAnimationFrame(animRef.current);
    };
  }, [sync]);

  const frame = timeline?.timeline[currentFrame] ?? null;

  const pwm = mode === "bharatbeam"
    ? (frame?.pwm ?? Array(12).fill(1))
    : mode === "high_beam" ? Array(12).fill(1.0) : Array(12).fill(0.12);

  const reasons = mode === "bharatbeam"
    ? (frame?.reasons ?? Array(12).fill("full_beam"))
    : Array(12).fill("full_beam");

  return (
    <div className="h-screen flex flex-col overflow-hidden" style={{ background: "var(--surface-deep)" }}>

      {/* ── HEADER ── */}
      <header
        className="flex items-center justify-between px-5 shrink-0"
        style={{ height: "48px", borderBottom: "1px solid oklch(18% 0.01 60)" }}
      >
        <div className="flex items-center gap-4">
          <span className="text-lg font-bold tracking-tight" style={{ fontFamily: "var(--font-instrument), sans-serif" }}>
            <span style={{ color: "#d4a030" }}>Bharat</span>
            <span style={{ color: "#e8dcc8" }}>Beam</span>
          </span>
          <div className="flex items-center gap-1.5">
            <div
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: isPlaying ? "var(--safe)" : "var(--text-muted)",
                boxShadow: isPlaying ? "0 0 6px oklch(70% 0.14 145 / 0.4)" : "none",
              }}
            />
            <span className="text-[9px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
              {isPlaying ? "Live" : "Paused"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <ModeTabs mode={mode} setMode={setMode} />
        </div>
      </header>

      {/* ── ARCHITECTURE STRIP ── */}
      <div style={{ borderBottom: "1px solid oklch(16% 0.008 60)", background: "oklch(11% 0.006 60)" }}>
        <ArchStrip />
      </div>

      {/* ── MAIN GRID ── */}
      <main className="flex-1 grid grid-cols-12 grid-rows-6 gap-2 p-2 min-h-0">

        {/* Video — 8 cols, 4 rows */}
        <div
          className="col-span-8 row-span-4 relative overflow-hidden"
          style={{
            background: "oklch(6% 0.005 60)",
            border: "1px solid oklch(18% 0.01 60)",
            borderRadius: "6px",
          }}
        >
          <video
            ref={videoRef}
            src="/data/processed_video.mp4"
            className="w-full h-full object-contain"
            controls
            playsInline
            preload="auto"
          />
          <div
            className="absolute top-3 right-3 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider"
            style={{
              background: mode === "bharatbeam" ? "oklch(60% 0.14 55 / 0.85)" : mode === "high_beam" ? "oklch(65% 0.1 85 / 0.85)" : "oklch(35% 0.02 60 / 0.85)",
              color: mode === "bharatbeam" ? "oklch(12% 0.01 60)" : "oklch(92% 0.01 60)",
              borderRadius: "3px",
              backdropFilter: "blur(8px)",
              fontFamily: "var(--font-instrument), sans-serif",
            }}
          >
            {mode === "bharatbeam" ? "ADB Active" : mode === "high_beam" ? "High Beam" : "Low Beam"}
          </div>
        </div>

        {/* Beam Segment Visualizer — 4 cols, 2 rows */}
        <Panel title="TPS92662-Q1 PWM Output" className="col-span-4 row-span-2">
          <BeamVisualizer segments={pwm} reasons={reasons} />
        </Panel>

        {/* Road Top-Down View — 4 cols, 2 rows */}
        <Panel title="Road Illumination Pattern" className="col-span-4 row-span-2">
          <RoadView segments={pwm} reasons={reasons} />
        </Panel>

        {/* Metrics — 5 cols, 2 rows */}
        <Panel title="System Metrics" className="col-span-5 row-span-2">
          <Metrics frame={frame} mode={mode} />
        </Panel>

        {/* CAN Bus Monitor — 3 cols, 2 rows */}
        <Panel title="CAN FD Bus" className="col-span-3 row-span-2">
          <CANMonitor frame={frame} frameIndex={currentFrame} />
        </Panel>

        {/* Technical Details — 4 cols, 2 rows */}
        <Panel title="System Specification" className="col-span-4 row-span-2">
          <div className="text-xs space-y-2.5" style={{ color: "#8a7a65" }}>
            <div className="flex justify-between">
              <span>Detection source</span>
              <span style={{ color: "#e8dcc8" }}>ADAS ECU object list via CAN FD</span>
            </div>
            <div className="flex justify-between">
              <span>Object classes</span>
              <span style={{ color: "#e8dcc8" }}>Car, truck, motorcycle, auto-rickshaw, person, bicycle, animal</span>
            </div>
            <div className="flex justify-between">
              <span>Training data</span>
              <span style={{ color: "#e8dcc8" }}>IDD / DriveIndia / DATS_2022 (Indian traffic)</span>
            </div>
            <div className="flex justify-between">
              <span>Beam segments</span>
              <span style={{ color: "#e8dcc8" }}>12 individually addressable (TPS92662-Q1)</span>
            </div>
            <div className="flex justify-between">
              <span>Controller</span>
              <span style={{ color: "#e8dcc8" }}>NXP S32K312 Cortex-M7 &middot; ASIL B</span>
            </div>
            <div className="flex justify-between">
              <span>Dim strategy</span>
              <span style={{ color: "#e8dcc8" }}>Oncoming: 8% PWM &middot; Preceding: 35%</span>
            </div>
            <div className="flex justify-between">
              <span>Hazard mode</span>
              <span style={{ color: "#e8dcc8" }}>Shadow-based pothole + obstacle highlighting</span>
            </div>
            <div className="flex justify-between">
              <span>Add-on BOM</span>
              <span style={{ color: "#d4a030" }}>$12–18 (zero sensor cost)</span>
            </div>
            <div className="flex justify-between">
              <span>Frame</span>
              <span className="tabular-nums" style={{ color: "#e8dcc8" }}>{currentFrame} / {timeline?.total_frames ?? 0} &middot; {frame?.t.toFixed(2) ?? "0"}s</span>
            </div>
          </div>
        </Panel>
      </main>

      {/* ── FOOTER ── */}
      <footer
        className="flex items-center justify-between px-5 shrink-0"
        style={{ height: "28px", borderTop: "1px solid oklch(16% 0.008 60)", background: "oklch(10% 0.006 60)" }}
      >
        <span className="text-[9px]" style={{ color: "var(--text-muted)", fontFamily: "var(--font-instrument), sans-serif" }}>
          Varroc Eureka 3.0 &middot; Problem Statement 6 &middot; Automotive Lighting Optimization
        </span>
        <span className="text-[9px]" style={{ color: "var(--text-muted)", fontFamily: "var(--font-instrument), sans-serif" }}>
          NXP S32K312 + TPS92662-Q1 &middot; 12-Segment Matrix LED &middot; Existing ADAS camera &middot; $12–18 BOM
        </span>
      </footer>
    </div>
  );
}
