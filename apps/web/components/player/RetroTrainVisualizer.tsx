"use client";

import type { VisualFrame } from "./visualFeatures";

import { useEffect, useRef } from "react";
import { PlaybackPreferences, readPlaybackPreferences } from "./playbackPreferences";
import styles from "./RetroTrainVisualizer.module.css";

/*
 * Midnight Metro. A 16-bit side-on view of a Tokyo subway carriage drawn into a
 * low-resolution pixel buffer and upscaled with nearest-neighbour sampling.
 *
 * Everything reacts to the track on purpose:
 *   ceiling tubes    -> 9 clusters x 3 tubes, one per band, quantised to 6 levels
 *   light pools      -> additive pools under lit tubes lift seats, floor, passengers
 *   window scenery   -> parallax skyline, neon, platforms; speed follows play + bass
 *   carriage         -> rail judder on bass onsets, slow lateral sway while moving
 *   listener         -> head nod on onsets, torso arc sway on mids, headphone glow on treble
 *   neon + signage   -> album palette, brightness follows mids, flicker on treble attack
 */

type Color = [number, number, number];
type Reactivity = { bass: number; mid: number; treble: number; level: number; onset: boolean; bassAttack: number; midAttack: number; trebleAttack: number; timestamp?: number };
type Palette = { accent: Color; background: Color; waves: [Color, Color, Color] };
type PaletteEvent = { active: boolean; palette: Palette | null };
type Rider = { x: number; kind: "seated" | "standing"; variant: number; pose: "phone" | "asleep" | "idle" | "book"; phase: number };

const HEIGHT = 216;
const FLOOR = 178, SEAT_TOP = 152, SEAT_BACK = 132, SILL = 120, WINDOW_TOP = 64, CEILING = 46;
const DEFAULT_PALETTE: Palette = { accent: [.56, .9, .86], background: [.02, .03, .06], waves: [[.42, .82, .78], [.86, .5, .62], [.96, .78, .42]] };
// Clockwise JR Yamanote Line. The display advances one stop per passing platform,
// then returns from Shinagawa to Osaki as the real loop does.
const STATIONS = [
  "大崎 Osaki", "五反田 Gotanda", "目黒 Meguro", "恵比寿 Ebisu", "渋谷 Shibuya", "原宿 Harajuku", "代々木 Yoyogi", "新宿 Shinjuku", "新大久保 Shin-Okubo", "高田馬場 Takadanobaba", "目白 Mejiro", "池袋 Ikebukuro", "大塚 Otsuka", "巣鴨 Sugamo", "駒込 Komagome", "田端 Tabata", "西日暮里 Nishi-Nippori", "日暮里 Nippori", "鶯谷 Uguisudani", "上野 Ueno", "御徒町 Okachimachi", "秋葉原 Akihabara", "神田 Kanda", "東京 Tokyo", "有楽町 Yurakucho", "新橋 Shimbashi", "浜松町 Hamamatsucho", "田町 Tamachi", "高輪ゲートウェイ Takanawa Gateway", "品川 Shinagawa",
];

const css = (c: Color, a = 1) => `rgba(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)},${a})`;
const seeded = (n: number) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const punch = (color: Color): Color => {
  const high = Math.max(...color), low = Math.min(...color), midpoint = (high + low) / 2;
  return color.map(value => clamp((midpoint + (value - midpoint) * 1.5 - .5) * 1.14 + .5, .04, .96)) as Color;
};
const quantize = (energy: number) => energy < .05 ? 0 : Math.min(1, Math.ceil(clamp(energy) * 5) / 5);

type Ctx = CanvasRenderingContext2D;
const px = (ctx: Ctx, x: number, y: number, w: number, h: number, fill: string) => { ctx.fillStyle = fill; ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); };
const glow = (ctx: Ctx, x: number, y: number, rx: number, ry: number, color: Color, alpha: number) => {
  if (alpha <= .002) return;
  ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.translate(x, y); ctx.scale(1, ry / rx);
  const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, rx);
  gradient.addColorStop(0, css(color, alpha)); gradient.addColorStop(1, css(color, 0));
  ctx.fillStyle = gradient; ctx.fillRect(-rx, -rx, rx * 2, rx * 2); ctx.restore();
};

// --- Sprites -----------------------------------------------------------------

const SKIN = ["#c9a089", "#b58b76", "#d8b3a0", "#a67c68"];
const COATS = ["#22242e", "#2a2630", "#1e2530", "#2c2a2a", "#242c2c"];
const HAIR = ["#141117", "#1d1a1f", "#2a2022", "#101014"];

function drawSeated(ctx: Ctx, rider: Rider, time: number, shear: number, listener: Palette | null, headTilt = 0) {
  const { x, variant, pose } = rider;
  const breathe = Math.round(Math.sin(time * 1.3 + rider.phase) * .5 + .5);
  const skin = listener ? "#e3b7a4" : SKIN[variant % SKIN.length];
  const coat = listener ? "#2f2540" : COATS[variant % COATS.length];
  const hair = listener ? "#1a1420" : HAIR[variant % HAIR.length];
  const trousers = listener ? "#1c1a26" : "#15161c";
  const asleepDrop = pose === "asleep" ? Math.round(2 + Math.sin(time * .35 + rider.phase) * 1.5) : 0;
  const headX = x + Math.round(shear * 2 + headTilt), shoulderX = x + Math.round(shear);
  // Shoes, shins, lap.
  px(ctx, x - 8, FLOOR - 3, 6, 3, "#0b0c11"); px(ctx, x + 2, FLOOR - 3, 6, 3, "#0b0c11");
  px(ctx, x - 8, SEAT_TOP + 4, 6, FLOOR - 7 - SEAT_TOP, trousers); px(ctx, x + 2, SEAT_TOP + 4, 6, FLOOR - 7 - SEAT_TOP, trousers);
  px(ctx, x - 9, SEAT_TOP - 1, 18, 6, trousers);
  // Torso, arms, hands.
  const torsoTop = SEAT_TOP - 20 - breathe;
  px(ctx, shoulderX - 8, torsoTop, 16, 20 + breathe, coat);
  px(ctx, shoulderX - 11, torsoTop + 2, 4, 14, coat); px(ctx, shoulderX + 7, torsoTop + 2, 4, 14, coat);
  px(ctx, x - 6, SEAT_TOP - 4, 4, 3, skin); px(ctx, x + 2, SEAT_TOP - 4, 4, 3, skin);
  if (listener) px(ctx, shoulderX - 1, torsoTop + 2, 2, 12, "#463a5c");
  // Head.
  const headTop = torsoTop - 14 + asleepDrop;
  px(ctx, headX - 2, torsoTop - 2, 4, 2 + Math.max(0, -asleepDrop), skin);
  px(ctx, headX - 5, headTop, 10, 12, skin);
  px(ctx, headX - 6, headTop - 1, 12, 5, hair); px(ctx, headX - 6, headTop + 3, 2, 6, hair); px(ctx, headX + 4, headTop + 3, 2, 5, hair);
  if (listener || variant % 3 === 1) { px(ctx, headX - 7, headTop + 3, 2, 14, hair); px(ctx, headX + 5, headTop + 3, 2, 14, hair); }
  if (!listener && variant % 4 === 2) { px(ctx, headX - 6, headTop - 4, 12, 4, "#2b2f3a"); px(ctx, headX - 7, headTop, 14, 1, "#2b2f3a"); } // beanie
  if (pose === "asleep") { px(ctx, headX - 3, headTop + 6, 2, 1, "#4a3334"); px(ctx, headX + 1, headTop + 6, 2, 1, "#4a3334"); }
  else { px(ctx, headX - 3, headTop + 6, 2, 2, "#1a1216"); px(ctx, headX + 1, headTop + 6, 2, 2, "#1a1216"); }
  if (!listener && variant % 5 === 3) px(ctx, headX - 4, headTop + 8, 8, 4, "#dfe4ea"); // surgical mask
  else px(ctx, headX - 1, headTop + 10, 2, 1, "#6d4448");
  // Props.
  if (pose === "phone") {
    px(ctx, x - 3, SEAT_TOP - 8, 6, 5, "#0d0f16"); px(ctx, x - 2, SEAT_TOP - 7, 4, 3, "#8fb4d8");
    glow(ctx, x, SEAT_TOP - 8, 12, 9, [.45, .62, .85], .12 + Math.sin(time * 9 + rider.phase) * .02);
  } else if (pose === "book") { px(ctx, x - 6, SEAT_TOP - 9, 12, 6, "#c7c1ad"); px(ctx, x - 1, SEAT_TOP - 9, 1, 6, "#8b8570"); }
  if (listener) {
    const accent = listener.accent;
    px(ctx, headX - 6, headTop, 12, 1, "#3a3f4c"); px(ctx, headX - 7, headTop + 1, 1, 3, "#3a3f4c"); px(ctx, headX + 6, headTop + 1, 1, 3, "#3a3f4c");
    px(ctx, headX - 9, headTop + 4, 3, 7, "#22252e"); px(ctx, headX + 6, headTop + 4, 3, 7, "#22252e");
    px(ctx, headX - 9, headTop + 6, 3, 3, css(accent)); px(ctx, headX + 6, headTop + 6, 3, 3, css(accent));
  }
}

function drawStanding(ctx: Ctx, rider: Rider, time: number, lean: number) {
  const { x, variant } = rider;
  const skin = SKIN[variant % SKIN.length], coat = COATS[(variant + 2) % COATS.length], hair = HAIR[(variant + 1) % HAIR.length];
  const bob = Math.round(Math.sin(time * 1.1 + rider.phase) * .5 + .5);
  const top = FLOOR - 62 - bob, hx = x + Math.round(lean * 2), sx = x + Math.round(lean);
  px(ctx, x - 7, FLOOR - 3, 6, 3, "#0b0c11"); px(ctx, x + 1, FLOOR - 3, 6, 3, "#0b0c11");
  px(ctx, x - 7, top + 32, 6, FLOOR - 3 - top - 32, "#15161c"); px(ctx, x + 1, top + 32, 6, FLOOR - 3 - top - 32, "#15161c");
  px(ctx, sx - 8, top + 12, 16, 22, coat); px(ctx, sx - 11, top + 14, 4, 16, coat); px(ctx, sx + 7, top + 14, 4, 16, coat);
  px(ctx, sx - 11, top + 30, 3, 3, skin); px(ctx, sx + 8, top + 30, 3, 3, skin);
  px(ctx, hx - 2, top + 10, 4, 3, skin); px(ctx, hx - 5, top, 10, 11, skin);
  px(ctx, hx - 6, top - 1, 12, 5, hair); px(ctx, hx - 6, top + 3, 2, 5, hair); px(ctx, hx + 4, top + 3, 2, 4, hair);
  px(ctx, hx - 3, top + 6, 2, 2, "#1a1216"); px(ctx, hx + 1, top + 6, 2, 2, "#1a1216");
  if (variant % 2) { px(ctx, sx + 9, top + 30, 8, 12, "#2c2622"); px(ctx, sx + 11, top + 27, 4, 3, "#2c2622"); }
}

// --- Component ---------------------------------------------------------------

export default function RetroTrainVisualizer() {
  const mountRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = mountRef.current;
    if (!canvas || window.matchMedia("(max-width:1199px), (max-height:719px)").matches || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;

    let preferences = readPlaybackPreferences();
    let enabled = preferences.wavesEnabled && preferences.backdropPreset === "retrotrain";
    let playing = false;
    let palette: Palette = DEFAULT_PALETTE;
    let frame = 0, lastFrame = 0, width = 384;
    let travel = 0, speed = 0, sway = 0, judder = 0, nod = 0, torsoArc = 0, lean = 0, clock = 0;
    let stationIndex = 0, lastPlatform = -1, shownStation = 0, displayScroll = 0;
    // The listener drifts between ways of moving to the music, like a person does.
    let mood: "arc" | "bounce" | "still" | "groove" = "arc", moodUntil = 8, bounce = 0, headTilt = 0, beatPhase = 0;
    const target: Reactivity = { bass: 0, mid: 0, treble: 0, level: 0, onset: false, bassAttack: 0, midAttack: 0, trebleAttack: 0 };
    const smooth = { bass: 0, mid: 0, treble: 0, level: 0 };
    let onsetPulse = 0, trebleFlash = 0, bpm = 0;
    let vocalActivation: number | null = null;
    const tubeLevels = new Float32Array(27);

    // Nine tube clusters; each holds one bass, one mid, one treble tube in a seeded order.
    const clusters = Array.from({ length: 9 }, (_, group) => ({
      order: [0, 1, 2].sort((a, b) => seeded(group * 7 + a) - seeded(group * 7 + b)),
      offset: (seeded(group + 1) - .5) * .12,
    }));

    const riders: Rider[] = [
      { x: -.4, kind: "seated", variant: 0, pose: "phone", phase: 0 },
      { x: -.31, kind: "seated", variant: 1, pose: "asleep", phase: 1.7 },
      { x: -.21, kind: "seated", variant: 2, pose: "idle", phase: 3.1 },
      { x: -.11, kind: "seated", variant: 3, pose: "book", phase: 4.2 },
      { x: .13, kind: "seated", variant: 4, pose: "asleep", phase: .8 },
      { x: .23, kind: "seated", variant: 1, pose: "phone", phase: 2.4 },
      { x: .34, kind: "seated", variant: 2, pose: "idle", phase: 5.5 },
      { x: -.46, kind: "standing", variant: 3, pose: "idle", phase: 1.1 },
      { x: .45, kind: "standing", variant: 0, pose: "phone", phase: 2.9 },
    ];
    const LISTENER_X = .015;

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      width = clamp(Math.round(HEIGHT * bounds.width / Math.max(1, bounds.height)), 300, 700);
      canvas.width = width; canvas.height = HEIGHT; ctx.imageSmoothingEnabled = false;
    };
    const receivePreferences = (event: Event) => { preferences = (event as CustomEvent<PlaybackPreferences>).detail; enabled = preferences.wavesEnabled && preferences.backdropPreset === "retrotrain"; canvas.classList.toggle(styles.active, enabled); };
    const receiveAudio = (event: Event) => {
      const detail = (event as CustomEvent<VisualFrame>).detail;
      Object.assign(target, detail);
      playing = detail.active;
      bpm = detail.bpm ?? 0;
      vocalActivation = detail.enrichment?.vocalActivation ?? null;
      if (!detail.active) {
        Object.assign(smooth, { bass: 0, mid: 0, treble: 0, level: 0 });
        onsetPulse = trebleFlash = speed = judder = nod = torsoArc = lean = bounce = headTilt = 0;
        tubeLevels.fill(0); beatPhase = 100;
        return;
      }
      if (detail.beat) onsetPulse = 1;
      trebleFlash = Math.max(trebleFlash, detail.trebleAttack * 4);
    };
    const receiveState = (event: Event) => { playing = Boolean((event as CustomEvent<boolean>).detail); if (!playing) speed = 0; };
    const receivePalette = (event: Event) => {
      const detail = (event as CustomEvent<PaletteEvent>).detail;
      if (!detail.palette) return; // Null arrives on pause; keep the last track's colours.
      const accent = punch(detail.palette.accent.map(value => clamp(value / 255, .08, 1)) as Color);
      palette = { ...detail.palette, accent, waves: detail.palette.waves.map(punch) as Palette["waves"] };
    };

    // --- Exterior ---------------------------------------------------------------
    const drawExterior = (bands: number[]) => {
      const w = width, h = SILL - WINDOW_TOP;
      ctx.save(); ctx.beginPath(); ctx.rect(0, WINDOW_TOP, w, h); ctx.clip();
      const sky = ctx.createLinearGradient(0, WINDOW_TOP, 0, SILL);
      sky.addColorStop(0, "#03040b"); sky.addColorStop(.7, "#080a17"); sky.addColorStop(1, "#0d0c18");
      ctx.fillStyle = sky; ctx.fillRect(0, WINDOW_TOP, w, h);
      for (let i = 0; i < 26; i++) { const sx = (seeded(i * 3) * 900 - travel * .02) % 900; if (sx >= 0 && sx < w) px(ctx, sx, WINDOW_TOP + 2 + seeded(i * 5) * 22, 1, 1, `rgba(200,210,255,${.25 + seeded(i) * .4})`); }

      // Far skyline: parallax .12, period 1200.
      const far = 1200, farX = -(travel * .12) % far;
      for (let pass = -1; pass <= Math.ceil(w / far) + 1; pass++) for (let b = 0; b < 40; b++) {
        const bw = 6 + Math.floor(seeded(b * 2) * 16), bh = 10 + Math.floor(seeded(b * 2 + 1) * 34);
        const bx = farX + pass * far + b * 30 + seeded(b * 9) * 12;
        if (bx + bw < 0 || bx > w) continue;
        px(ctx, bx, SILL - 12 - bh, bw, bh + 12, "#0a0d19");
        for (let f = 0; f < bh / 6; f++) if (seeded(b * 31 + f) > .6) px(ctx, bx + 2 + Math.floor(seeded(b + f * 7) * (bw - 3)), SILL - 10 - bh + f * 6, 1, 1, seeded(f * b) > .5 ? "#c58e4d" : "#5689b8");
        if (b === 17) { // A tower with a blinking aviation light.
          px(ctx, bx + bw / 2 - 1, SILL - 60 - bh, 2, 48, "#0d1020"); px(ctx, bx + bw / 2 - 3, SILL - 24 - bh, 6, 12, "#0d1020");
          if (Math.floor(clock * 1.2) % 2 === 0) { px(ctx, bx + bw / 2 - 1, SILL - 61 - bh, 2, 2, "#ff4d5a"); glow(ctx, bx + bw / 2, SILL - 60 - bh, 6, 6, [1, .3, .35], .35); }
        }
      }

      // Mid buildings with neon signage in the album palette: parallax .38, period 760.
      const mid = 760, midX = -(travel * .38) % mid;
      for (let pass = -1; pass <= Math.ceil(w / mid) + 1; pass++) for (let b = 0; b < 16; b++) {
        const bw = 18 + Math.floor(seeded(b * 4 + 100) * 30), bh = 18 + Math.floor(seeded(b * 4 + 101) * 42);
        const bx = midX + pass * mid + b * 47 + seeded(b * 6 + 100) * 20;
        if (bx + bw < 0 || bx > w) continue;
        px(ctx, bx, SILL - bh, bw, bh, b % 2 ? "#0f1220" : "#121325");
        px(ctx, bx, SILL - bh, bw, 1, "#1c2036");
        for (let f = 1; f < bh / 7; f++) for (let c = 0; c < bw / 8; c++) if (seeded(b * 53 + f * 11 + c) > .55) px(ctx, bx + 3 + c * 8, SILL - bh + f * 7, 3, 2, seeded(b + f + c) > .35 ? "#3a3c46" : "#e6d6a8");
        if (seeded(b * 77 + 100) > .45) {
          const band = b % 3, color = palette.waves[band];
          const brightness = clamp(.35 + smooth.mid * .55 + (band === 2 ? trebleFlash * .6 : 0) - (seeded(b + Math.floor(clock * 7)) > .96 ? .3 : 0));
          const sw = 5, sh = 14 + Math.floor(seeded(b * 8) * 14), sxx = bx + 3 + Math.floor(seeded(b * 9) * (bw - 9)), syy = SILL - bh + 4;
          px(ctx, sxx - 1, syy - 1, sw + 2, sh + 2, "#05060c"); px(ctx, sxx, syy, sw, sh, css(color, .25 + brightness * .75));
          for (let g = 0; g < sh / 4 - 1; g++) px(ctx, sxx + 1, syy + 2 + g * 4, 3, 2, css(color, brightness * .82));
          glow(ctx, sxx + sw / 2, syy + sh / 2, 14, sh, color, brightness * .28);
        }
      }

      // Far-side station. The roof, columns and people all terminate at one
      // platform floor. The entire layer moves as one object.
      const platformPeriod = 2600, platformLength = 520, platformPos = travel % platformPeriod, platformIndex = Math.floor(travel / platformPeriod);
      if (platformIndex !== lastPlatform) { lastPlatform = platformIndex; stationIndex = (stationIndex + 1) % STATIONS.length; }
      const platformX = w - platformPos;
      if (platformX < w && platformX + platformLength > 0) {
        const platformTop = SILL - 18, roofTop = WINDOW_TOP + 5;
        px(ctx, platformX, roofTop, platformLength, 7, "#22252e");
        px(ctx, platformX, platformTop, platformLength, 18, "#20232b");
        px(ctx, platformX, platformTop, platformLength, 2, "#e3b83f");
        px(ctx, platformX, platformTop + 4, platformLength, 2, "#111319");
        const stationBays = Math.floor((platformLength - 44) / 64) + 1;
        for (let i = 0; i < stationBays; i++) {
          const columnX = platformX + 22 + i * 64;
          px(ctx, columnX, roofTop + 7, 3, platformTop - roofTop - 7, "#343741");
          px(ctx, columnX - 18, roofTop + 3, 36, 3, css(palette.waves[i % 3], .85));
          glow(ctx, columnX, roofTop + 7, 30, 25, palette.waves[i % 3], .14);
          if (seeded(i * 4 + platformIndex) > .5) {
            const personX = columnX + 24;
            px(ctx, personX, platformTop - 22, 8, 22, "#11131a");
            px(ctx, personX + 2, platformTop - 28, 4, 6, "#171921");
          }
        }
        const signX = platformX + platformLength / 2 - 34;
        px(ctx, signX, roofTop + 14, 68, 13, "#090b10"); px(ctx, signX, roofTop + 14, 68, 2, css(palette.waves[1]));
        ctx.font = "7px monospace"; ctx.fillStyle = "#e8ecf2"; ctx.textBaseline = "top"; ctx.fillText(STATIONS[stationIndex].split(" ")[0], signX + 7, roofTop + 18);
      }

      // Near track is a persistent foreground layer, including through stations.
      const nearX = -travel * 1.4 % 16;
      px(ctx, 0, SILL - 13, w, 3, "#090a0e");
      for (let sleeper = -20; sleeper < w + 20; sleeper += 16) px(ctx, sleeper + nearX, SILL - 12, 11, 6, "#171920");
      px(ctx, 0, SILL - 14, w, 2, "#555861"); px(ctx, 0, SILL - 6, w, 2, "#3d4048");

      // Opposing train is never toggled by station visibility. It enters and exits
      // continuously on the near track, naturally occluding the platform behind it.
      const trainPeriod = 5200, trainLength = 900;
      const opposingX = w - ((travel * 2.6 + 3400) % trainPeriod);
      if (opposingX < w && opposingX + trainLength > 0) for (let car = 0; car < 5; car++) {
        const cx = opposingX + car * 180;
        px(ctx, cx, SILL - 47, 176, 33, "#161a24"); px(ctx, cx, SILL - 47, 176, 1, css(palette.waves[2], .8));
        px(ctx, cx + 5, SILL - 14, 166, 2, "#0b0d12");
        for (const wheel of [26, 138]) { px(ctx, cx + wheel, SILL - 15, 8, 3, "#07080d"); px(ctx, cx + wheel + 2, SILL - 16, 4, 1, "#61646b"); }
        for (let wnd = 0; wnd < 7; wnd++) px(ctx, cx + 8 + wnd * 24, SILL - 43, 18, 12, wnd % 3 === 0 ? css(palette.waves[2], .72) : "#b8813f");
        glow(ctx, cx + 88, SILL - 37, 100, 18, palette.waves[2], .09);
      }
      // Rain streaks, angled by speed.
      for (let r = 0; r < 34; r++) {
        const rx = ((seeded(r * 3 + 400) * w) + travel * 1.4) % w, ry = WINDOW_TOP + (seeded(r * 5 + 400) * h + clock * (60 + speed * 40) * (0.6 + seeded(r))) % h;
        px(ctx, rx, ry, 1 + Math.round(speed * 3), 1, `rgba(190,205,230,${.05 + seeded(r) * .1})`);
      }
      // Glass: subtle vertical sheen and reflected tube light.
      for (let i = 0; i < 3; i++) if (bands[i] > 0) px(ctx, 0, WINDOW_TOP + 3 + i * 2, w, 1, css(palette.waves[i], bands[i] * .06));
      ctx.restore();
    };

    // --- Interior ----------------------------------------------------------------
    const drawInterior = () => {
      const w = width;
      // Ceiling and upper panel.
      px(ctx, 0, 0, w, CEILING, "#0c0d13"); px(ctx, 0, CEILING, w, WINDOW_TOP - CEILING, "#13141b"); px(ctx, 0, CEILING, w, 1, "#1e2029");
      // Window frame: thin rails and dividers only. Nothing covers the glass.
      px(ctx, 0, WINDOW_TOP - 2, w, 2, "#2a2d37"); px(ctx, 0, SILL, w, 2, "#2a2d37");
      const doorW = Math.round(w * .09);
      for (const x of [doorW + 2, Math.round(w * .5) - 1, w - doorW - 4]) px(ctx, x, WINDOW_TOP - 2, 2, SILL - WINDOW_TOP + 4, "#2a2d37");
      // Wall, seat back, cushion, kick panel, floor.
      px(ctx, 0, SILL + 2, w, SEAT_BACK - SILL - 2, "#1a1b23");
      px(ctx, doorW, SEAT_BACK, w - doorW * 2, SEAT_TOP - SEAT_BACK, "#1d2a44"); px(ctx, doorW, SEAT_BACK, w - doorW * 2, 1, "#2b3d5e");
      px(ctx, doorW, SEAT_TOP, w - doorW * 2, 8, "#22325a"); px(ctx, doorW, SEAT_TOP, w - doorW * 2, 1, "#33487a");
      px(ctx, doorW, SEAT_TOP + 8, w - doorW * 2, FLOOR - SEAT_TOP - 8, "#141721");
      for (let s = doorW + 20; s < w - doorW; s += 20) px(ctx, s, SEAT_BACK, 1, SEAT_TOP - SEAT_BACK + 8, "#162238");
      const floor = ctx.createLinearGradient(0, FLOOR, 0, HEIGHT); floor.addColorStop(0, "#171922"); floor.addColorStop(1, "#0a0b10");
      ctx.fillStyle = floor; ctx.fillRect(0, FLOOR, w, HEIGHT - FLOOR); px(ctx, 0, FLOOR, w, 1, "#252836");
      // Doors at each end: glass, rubber seam, green lamp.
      for (const [dx, dir] of [[0, 1], [w - doorW, -1]] as const) {
        px(ctx, dx, WINDOW_TOP - 2, doorW, FLOOR - WINDOW_TOP + 2, "#1b1d26"); px(ctx, dx + (dir > 0 ? doorW - 2 : 0), WINDOW_TOP - 2, 2, FLOOR - WINDOW_TOP + 2, "#3a3d48");
        px(ctx, dx + 6, WINDOW_TOP + 4, doorW - 12, 44, "#05060c"); px(ctx, dx + 7, WINDOW_TOP + 5, doorW - 14, 42, "#0b0e1c");
        px(ctx, dx + doorW / 2 - 1, WINDOW_TOP + 4, 2, 44, "#2b2e3a");
        const lamp = lastPlatform >= 0 && (travel % 2600) < 700 ? "#5be07a" : "#153a22"; px(ctx, dx + doorW / 2 - 2, CEILING + 6, 4, 2, lamp);
        px(ctx, dx + 4, SEAT_TOP - 4, doorW - 8, 3, "#f2c14e");
      }
      // Scrolling LED destination display above the centre window.
      ctx.font = "7px monospace"; ctx.textBaseline = "top";
      const cx = Math.round(w * .5), dw = 96;
      px(ctx, cx - dw / 2, CEILING + 4, dw, 9, "#05060a"); px(ctx, cx - dw / 2, CEILING + 4, dw, 1, "#22242e");
      ctx.save(); ctx.beginPath(); ctx.rect(cx - dw / 2 + 2, CEILING + 5, dw - 4, 7); ctx.clip();
      const text = `次は ${STATIONS[shownStation]}    Next ${STATIONS[shownStation].split(" ")[1]}    `;
      const textWidth = ctx.measureText(text).width;
      if (displayScroll >= textWidth) { displayScroll -= textWidth; shownStation = stationIndex; } // swap only at the seam
      const scroll = displayScroll;
      ctx.fillStyle = css(palette.accent, .95); ctx.fillText(text, cx - dw / 2 + 2 - scroll, CEILING + 5); ctx.fillText(text, cx - dw / 2 + 2 - scroll + textWidth, CEILING + 5);
      ctx.restore();
      // Priority-seat pictogram card on the wall.
      px(ctx, doorW + 6, SILL + 4, 10, 6, "#e94f6a"); px(ctx, doorW + 8, SILL + 5, 6, 4, "#ffffff");
    };

    const drawTubes = () => {
      const w = width, span = w / 9;
      for (let group = 0; group < 9; group++) {
        const center = span * (group + .5 + clusters[group].offset);
        // One recessed fixture per cluster holding three short tubes.
        px(ctx, Math.round(center) - 21, 30, 42, 12, "#111218"); px(ctx, Math.round(center) - 20, 31, 40, 10, "#181a22");
        for (let slot = 0; slot < 3; slot++) {
          const band = clusters[group].order[slot], level = tubeLevels[group * 3 + slot], color = palette.waves[band];
          const tx = Math.round(center + (slot - 1) * 13) - 5, ty = 34;
          if (level <= 0) { px(ctx, tx, ty, 10, 3, "#22242c"); continue; }
          px(ctx, tx, ty, 10, 3, css([color[0] * .5 + .5 * level, color[1] * .5 + .5 * level, color[2] * .5 + .5 * level]));
          px(ctx, tx + 1, ty + 3, 8, 1, css(color, .6 * level));
          glow(ctx, tx + 5, ty + 2, 11 + level * 6, 9, color, level * .5);
          // Pool of light cast down onto seats, passengers and floor.
          glow(ctx, tx + 4, SEAT_TOP - 20, 30 + level * 12, 70, color, level * .085);
          px(ctx, tx - 6 - level * 6, FLOOR + 2, 20 + level * 12, 6, css(color, level * .06)); // floor sheen
        }
      }
    };

    const drawRiders = (time: number) => {
      const listenerX = Math.round(width * .5 + LISTENER_X * width);
      for (const rider of riders) {
        const x = Math.round(width * .5 + rider.x * width);
        if (rider.kind === "seated") drawSeated(ctx, { ...rider, x }, time, 0, null);
        else drawStanding(ctx, { ...rider, x }, time, lean);
      }
      // The listener sits centre stage: torso arc on mids, head nod on onsets, headphones glow on treble.
      const lift = Math.round(nod * 2 - bounce);
      ctx.save(); ctx.translate(0, lift);
      drawSeated(ctx, { x: listenerX, kind: "seated", variant: 0, pose: "idle", phase: 0 }, time, torsoArc, palette, headTilt);
      ctx.restore();
      const headY = SEAT_TOP - 20 - 14 + 7 + lift, headX = listenerX + Math.round(torsoArc * 2 + headTilt);
      const trebleGlow = clamp(smooth.treble * preferences.trebleReactivity * 1.6);
      glow(ctx, headX - 8, headY, 9, 9, palette.accent, .12 + trebleGlow * .5); glow(ctx, headX + 8, headY, 9, 9, palette.accent, .12 + trebleGlow * .5);
    };

    const animate = (now: number) => {
      frame = requestAnimationFrame(animate);
      if (!enabled) return;
      const interval = preferences.waveFrameRate === "uncapped" ? 0 : 1000 / Number(preferences.waveFrameRate);
      if (now - lastFrame < interval) return;
      const delta = Math.min(.05, (now - lastFrame) / 1000 || .016); lastFrame = now;
      const rate = preferences.animationSpeed === "slow" ? .65 : preferences.animationSpeed === "fast" ? 1.45 : 1;
      clock += delta * rate; displayScroll += delta * rate * 22;

      for (const key of ["bass", "mid", "treble", "level"] as const) smooth[key] += (target[key] - smooth[key]) * .35;
      onsetPulse = Math.max(0, onsetPulse - delta * 5); trebleFlash = Math.max(0, trebleFlash - delta * 6);
      const bands = [
        quantize(smooth.bass * preferences.bassReactivity * 1.7 + target.bassAttack * preferences.bassReactivity * 3),
        quantize(smooth.mid * preferences.vocalReactivity * 1.9 + target.midAttack * preferences.vocalReactivity * 3),
        quantize(smooth.treble * preferences.trebleReactivity * 2.4 + target.trebleAttack * preferences.trebleReactivity * 4),
      ];

      // Each fixture acts like a temperamental fluorescent tube: a band opens its
      // own gate, then individual tubes snap on and off at attack-driven rates.
      // This is deliberately discontinuous, like old carriage lights flickering.
      for (let group = 0; group < 9; group++) for (let slot = 0; slot < 3; slot++) {
        const index = group * 3 + slot;
        const band = clusters[group].order[slot];
        const energy = [smooth.bass * preferences.bassReactivity, smooth.mid * preferences.vocalReactivity, smooth.treble * preferences.trebleReactivity][band];
        const attack = [target.bassAttack * preferences.bassReactivity, target.midAttack * preferences.vocalReactivity, target.trebleAttack * preferences.trebleReactivity][band];
        const stepped = quantize(energy * 2.25 + attack * 4.5);
        // Hold a stable six-step level during sustained music. Brief irregular
        // dropouts happen only on sharp attacks, not on every rendered frame.
        const flicker = clamp(attack * 7 + onsetPulse * .25);
        const pulseRate = 11 + attack * 55 + seeded(index + 91) * 7;
        const phase = Math.sin(clock * pulseRate + index * 4.91);
        const gate = flicker < .18 || phase > .18 - flicker * .5;
        tubeLevels[index] = playing && stepped > 0 && gate ? stepped : 0;
      }

      // Train physics. Play accelerates over ~1.5 s; pause halts scenery instantly.
      const previousSpeed = speed;
      if (playing) speed += (1 - speed) * Math.min(1, delta * 1.4); else speed = 0;
      const accel = (speed - previousSpeed) / Math.max(delta, .001);
      lean += ((-accel * .9 + Math.sin(clock * .9) * speed * .35) - lean) * .18;
      // Keep slow tracks gliding, then let high-BPM tracks gather pace sharply.
      // This exponential curve matches the perceived speed change better than a linear BPM ratio.
      const tempoProgress = clamp((bpm - 70) / 110);
      const tempoScale = .42 + Math.pow(tempoProgress, 2.35) * 1.45;
      if (playing) travel += delta * rate * speed * tempoScale * (110 + smooth.bass * 190);
      sway += ((playing ? Math.sin(clock * 1.7) * .9 * speed : 0) - sway) * .08;
      judder += ((playing ? (onsetPulse > .6 ? 1 : 0) * clamp(smooth.bass * preferences.bassReactivity * 2) : 0) - judder) * .5;
      if (clock > moodUntil) {
        const moods = ["arc", "bounce", "still", "groove"] as const;
        mood = moods[Math.floor(Math.random() * moods.length)];
        moodUntil = clock + 6 + Math.random() * 10;
      }
      // Model activity is optional and uncalibrated; unknown is not vocal presence.
      const vocal = clamp((vocalActivation ?? 0) * smooth.level * preferences.vocalReactivity), bassEnergy = clamp(smooth.bass * preferences.bassReactivity);
      if (onsetPulse > .95) beatPhase = 0; beatPhase += delta * 3.2;
      const beat = Math.exp(-beatPhase * 2.2); // decaying pulse from the last onset
      let nodTarget = 0, arcTarget = 0, tiltTarget = 0, bounceTarget = 0;
      if (playing && mood !== "still") {
        if (mood === "arc") { arcTarget = Math.sin(clock * 1.6) * (.6 + vocal * 1.4); tiltTarget = Math.sin(clock * 1.6 + .6) * .8; }
        if (mood === "bounce") { bounceTarget = beat * (1.2 + bassEnergy * 2.4); nodTarget = beat * .6; }
        if (mood === "groove") { arcTarget = Math.sin(clock * 2.4) * (.4 + vocal); bounceTarget = beat * (.8 + bassEnergy * 1.6); tiltTarget = Math.sin(clock * 4.8) * (.3 + vocal * .8); }
      } else if (playing) { nodTarget = onsetPulse * .35 * bassEnergy; }
      nod += (nodTarget - nod) * .3;
      bounce += (bounceTarget - bounce) * .35;
      torsoArc += (arcTarget - torsoArc) * (mood === "groove" ? .2 : .1);
      headTilt += (tiltTarget - headTilt) * .2;

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = "#03040a"; ctx.fillRect(0, 0, width, HEIGHT);
      ctx.translate(Math.round(sway), Math.round(judder));
      drawExterior(bands);
      drawInterior();
      drawRiders(clock);
      // Unlit carriage: sink the interior further so the window carries the frame.
      const lit = Math.max(bands[0], bands[1], bands[2]);
      ctx.fillStyle = `rgba(2,3,8,${(1 - lit) * .3})`; ctx.fillRect(-2, SILL + 2, width + 4, HEIGHT - SILL);
      ctx.fillRect(-2, 0, width + 4, WINDOW_TOP - 2);
      drawTubes();
      // Ambient lift with overall level so loud passages feel brighter without washing out.
      ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.fillStyle = css(palette.waves[0], clamp(smooth.level * .035)); ctx.fillRect(-2, 0, width + 4, HEIGHT); ctx.restore();
      // Vignette.
      const vignette = ctx.createRadialGradient(width / 2, HEIGHT * .5, HEIGHT * .3, width / 2, HEIGHT * .5, width * .7);
      vignette.addColorStop(0, "rgba(0,0,0,0)"); vignette.addColorStop(1, "rgba(0,0,0,.55)"); ctx.fillStyle = vignette; ctx.fillRect(-2, -2, width + 4, HEIGHT + 4);
    };

    canvas.classList.toggle(styles.active, enabled); resize();
    window.addEventListener("resize", resize); window.addEventListener("echora:playback-preferences", receivePreferences); window.addEventListener("echora:visual-frame", receiveAudio); window.addEventListener("echora:playback-state", receiveState); window.addEventListener("echora:track-palette", receivePalette);
    frame = requestAnimationFrame(animate);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("resize", resize); window.removeEventListener("echora:playback-preferences", receivePreferences); window.removeEventListener("echora:visual-frame", receiveAudio); window.removeEventListener("echora:playback-state", receiveState); window.removeEventListener("echora:track-palette", receivePalette); };
  }, []);

  return <canvas ref={mountRef} className={styles.scene} aria-hidden="true" />;
}
