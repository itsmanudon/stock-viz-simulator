/**
 * PRISM sound engine: every interface sound is synthesised with the Web Audio
 * API at the moment it plays. There are no audio files to download, nothing
 * plays until the person turns sound on, and the AudioContext is only created
 * from inside a user gesture (browsers refuse to start one otherwise).
 *
 * The palette is deliberately small and soft: short sine/triangle blips tuned
 * to one pentatonic scale (so any two sounds played together still agree),
 * a filtered-noise "air" for page changes, and a three-note rise for a fill.
 * Master gain is low; a sound that would play more than once in 40 ms is
 * dropped, so a fast run of hovers never turns into a buzz.
 *
 * While the marketing pages' background music plays (`lib/sound/ambient.ts`)
 * it hands its current chord to `setHarmony`, and a tap then plays the next
 * tone of that chord instead of a fixed A, so clicks join the music.
 */

export type SoundName =
  | "hover"
  | "tap"
  | "toggleOn"
  | "toggleOff"
  | "navigate"
  | "success"
  | "fill"
  | "error"
  | "open"
  | "close"
  | "tick";

/** A-minor pentatonic, A3 up: every interval in it is consonant. */
const SCALE = [220, 261.63, 293.66, 329.63, 392, 440, 523.25, 587.33, 659.25, 783.99, 880];

let ctx: AudioContext | null = null;
let master: GainNode | null = null;
let noiseBuffer: AudioBuffer | null = null;
const lastPlayed = new Map<SoundName, number>();
let harmony: number[] | null = null;
let harmonyStep = 0;

/** The shared AudioContext, created (and resumed) on first use. */
export function soundContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!ctx) {
    const Ctor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    ctx = new Ctor({ latencyHint: "interactive" });
    master = ctx.createGain();
    master.gain.value = 0.22;
    // A gentle low-pass on the whole bus keeps every sound rounded.
    const tone = ctx.createBiquadFilter();
    tone.type = "lowpass";
    tone.frequency.value = 6500;
    master.connect(tone).connect(ctx.destination);
  }
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

function noise(ac: AudioContext): AudioBuffer {
  if (noiseBuffer) return noiseBuffer;
  const buffer = ac.createBuffer(1, ac.sampleRate * 0.6, ac.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  noiseBuffer = buffer;
  return buffer;
}

type Blip = {
  freq: number;
  at?: number;
  dur?: number;
  gain?: number;
  type?: OscillatorType;
  glideTo?: number;
};

function blip(
  ac: AudioContext,
  { freq, at = 0, dur = 0.09, gain = 0.5, type = "sine", glideTo }: Blip,
) {
  if (!master) return;
  const t = ac.currentTime + at;
  const osc = ac.createOscillator();
  const env = ac.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t);
  if (glideTo) osc.frequency.exponentialRampToValueAtTime(glideTo, t + dur);
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(gain, t + 0.006);
  env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(env).connect(master);
  osc.start(t);
  osc.stop(t + dur + 0.02);
}

function air(ac: AudioContext, { dur = 0.32, from = 400, to = 2400, gain = 0.18 } = {}) {
  if (!master) return;
  const t = ac.currentTime;
  const src = ac.createBufferSource();
  src.buffer = noise(ac);
  const band = ac.createBiquadFilter();
  band.type = "bandpass";
  band.Q.value = 1.4;
  band.frequency.setValueAtTime(from, t);
  band.frequency.exponentialRampToValueAtTime(to, t + dur);
  const env = ac.createGain();
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(gain, t + dur * 0.35);
  env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(band).connect(env).connect(master);
  src.start(t);
  src.stop(t + dur + 0.02);
}

const PATCHES: Record<SoundName, (ac: AudioContext) => void> = {
  hover: (ac) => blip(ac, { freq: SCALE[8], dur: 0.035, gain: 0.07 }),
  tick: (ac) => blip(ac, { freq: SCALE[10], dur: 0.025, gain: 0.05, type: "triangle" }),
  tap: (ac) => {
    const freq = tapNote();
    blip(ac, { freq, dur: 0.06, gain: 0.32, type: "triangle" });
    blip(ac, { freq: freq * 1.5, dur: 0.04, gain: 0.08, at: 0.01 });
  },
  toggleOn: (ac) => {
    blip(ac, { freq: SCALE[4], dur: 0.07, gain: 0.3 });
    blip(ac, { freq: SCALE[7], dur: 0.1, gain: 0.3, at: 0.06 });
  },
  toggleOff: (ac) => {
    blip(ac, { freq: SCALE[7], dur: 0.07, gain: 0.25 });
    blip(ac, { freq: SCALE[4], dur: 0.1, gain: 0.25, at: 0.06 });
  },
  navigate: (ac) => air(ac, { dur: 0.28, from: 500, to: 2600, gain: 0.12 }),
  open: (ac) => {
    air(ac, { dur: 0.18, from: 800, to: 3200, gain: 0.08 });
    blip(ac, { freq: SCALE[5], dur: 0.08, gain: 0.18, glideTo: SCALE[7] });
  },
  close: (ac) => {
    air(ac, { dur: 0.16, from: 2800, to: 700, gain: 0.07 });
    blip(ac, { freq: SCALE[7], dur: 0.08, gain: 0.15, glideTo: SCALE[5] });
  },
  success: (ac) => {
    [SCALE[5], SCALE[7], SCALE[9]].forEach((freq, i) => {
      blip(ac, { freq, at: i * 0.07, dur: 0.22, gain: 0.28 });
    });
  },
  // An order filling: a bright rising arpeggio with a soft shimmer on top.
  fill: (ac) => {
    [SCALE[3], SCALE[5], SCALE[7], SCALE[10]].forEach((freq, i) => {
      blip(ac, { freq, at: i * 0.06, dur: 0.28, gain: 0.26, type: i === 3 ? "sine" : "triangle" });
    });
    air(ac, { dur: 0.5, from: 3000, to: 7000, gain: 0.05 });
  },
  error: (ac) => {
    blip(ac, { freq: 196, dur: 0.12, gain: 0.3, type: "triangle", glideTo: 150 });
    blip(ac, { freq: 185, dur: 0.16, gain: 0.25, type: "triangle", at: 0.1, glideTo: 140 });
  },
};

/**
 * The chord the music is on, as frequencies, or null when no music plays.
 * Taps then walk up its tones in the 350-900 Hz band.
 */
export function setHarmony(freqs: number[] | null) {
  if (!freqs) {
    harmony = null;
    return;
  }
  const band: number[] = [];
  for (const f of freqs) {
    for (const octave of [1, 2, 4]) {
      const v = f * octave;
      if (v >= 350 && v <= 900 && !band.some((b) => Math.abs(b - v) < 1)) band.push(v);
    }
  }
  harmony = band.length ? band.sort((a, b) => a - b) : null;
}

/** The note a tap plays: C5, or the next chord tone while music plays. */
export function tapNote(): number {
  if (!harmony) return SCALE[6];
  harmonyStep = (harmonyStep + 1) % harmony.length;
  return harmony[harmonyStep];
}

/** Plays a sound. Safe to call anywhere; it does nothing on the server. */
export function playSound(name: SoundName) {
  const ac = soundContext();
  if (!ac) return;
  const now = performance.now();
  if (now - (lastPlayed.get(name) ?? 0) < 40) return;
  lastPlayed.set(name, now);
  PATCHES[name](ac);
}

/** Unlocks audio from inside a gesture, so the first real sound is not lost. */
export function primeSound() {
  soundContext();
}
