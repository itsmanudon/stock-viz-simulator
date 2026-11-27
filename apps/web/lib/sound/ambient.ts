/**
 * Background music for the marketing pages (owner, 27 Nov 2026).
 *
 * A slow ambient pad, synthesised with Web Audio like every other sound, so
 * there is no track to download or license. It plays only while interface
 * sound is on, on the public pages (`components/sound/ambient-music.tsx`
 * mounts it), starts with a slow fade and stops when the tab is hidden.
 *
 * - Four chords, nine seconds each, from A minor / C major: the same key as
 *   the interface sounds, and each chord is handed to the engine so a tap
 *   plays one of its tones (`setHarmony`).
 * - Under the chords, a quiet root; over them, a few sparse bell notes.
 * - Mood follows the market: the hero sets the share of tracked symbols that
 *   closed up (`setAmbientMood`). Fewer up and the progression leans on the
 *   minor chords and the filter closes; more up and it opens on C major and
 *   brightens. While the terrain section is on screen it overrides the mood
 *   with the session in view, so scrolling through time moves the music.
 */

import { setHarmony, soundContext } from "@/lib/sound/engine";

const CHORD_SECONDS = 9;
const LEVEL = 0.16;
const FADE_IN = 4;
const FADE_OUT = 1.2;

type Chord = { name: string; bass: number; voices: number[] };

/** MIDI note number to frequency (A4 = 69 = 440 Hz). */
const hz = (note: number) => 440 * 2 ** ((note - 69) / 12);

const AM9: Chord = { name: "Am9", bass: 45, voices: [60, 64, 67, 71] };
const DM9: Chord = { name: "Dm9", bass: 38, voices: [53, 57, 60, 64] };
const FMAJ9: Chord = { name: "Fmaj9", bass: 41, voices: [57, 60, 64, 67] };
const EM7: Chord = { name: "Em7", bass: 40, voices: [55, 59, 62, 67] };
const CMAJ9: Chord = { name: "Cmaj9", bass: 48, voices: [52, 55, 59, 62] };
const G6: Chord = { name: "G6", bass: 43, voices: [59, 62, 64, 67] };

export const PROGRESSIONS = {
  low: [AM9, DM9, FMAJ9, EM7],
  even: [AM9, FMAJ9, CMAJ9, G6],
  high: [CMAJ9, G6, AM9, FMAJ9],
} as const;

export type Mood = keyof typeof PROGRESSIONS;

function valid(share: number | null | undefined): share is number {
  return typeof share === "number" && !Number.isNaN(share);
}

/** Which progression a breadth share (0 to 1, the share of symbols up) plays. */
export function moodFor(share: number | null | undefined): Mood {
  if (!valid(share)) return "even";
  if (share < 0.42) return "low";
  if (share > 0.58) return "high";
  return "even";
}

/** Low-pass cutoff in Hz: closed and warm when few are up, open when most are. */
export function brightnessFor(share: number | null | undefined): number {
  if (!valid(share)) return 1500;
  return Math.round(700 + Math.min(1, Math.max(0, share)) * 2200);
}

/** Bell notes per chord: fewer when the market is down. */
const BELLS: Record<Mood, number> = { low: 1, even: 2, high: 3 };

let baseShare: number | null = null;
let overrideShare: number | null = null;
let impulse: AudioBuffer | null = null;

type Running = {
  ac: AudioContext;
  bus: GainNode;
  filter: BiquadFilterNode;
  nodes: AudioNode[];
  lfo: OscillatorNode;
  timer: ReturnType<typeof setInterval>;
  nextAt: number;
  step: number;
};

let running: Running | null = null;

function currentShare() {
  return overrideShare ?? baseShare;
}

function applyMood() {
  if (!running) return;
  running.filter.frequency.setTargetAtTime(
    brightnessFor(currentShare()),
    running.ac.currentTime,
    0.8,
  );
}

/** The page's mood: the latest session's breadth, or null for neutral. */
export function setAmbientMood(share: number | null) {
  baseShare = valid(share) ? share : null;
  applyMood();
}

/** A temporary mood (the terrain's session in view); null hands back to the page's. */
export function setAmbientMoodOverride(share: number | null) {
  overrideShare = valid(share) ? share : null;
  applyMood();
}

/** A soft, decaying stereo noise tail, made once: the room the pad plays in. */
function room(ac: AudioContext): AudioBuffer {
  if (impulse && impulse.sampleRate === ac.sampleRate) return impulse;
  const length = Math.floor(ac.sampleRate * 3.5);
  const buffer = ac.createBuffer(2, length, ac.sampleRate);
  for (let channel = 0; channel < 2; channel++) {
    const data = buffer.getChannelData(channel);
    for (let i = 0; i < length; i++) {
      data[i] = (Math.random() * 2 - 1) * (1 - i / length) ** 3;
    }
  }
  impulse = buffer;
  return buffer;
}

function voice(r: Running, freq: number, t: number, peak: number, kinds: OscillatorType[]) {
  const { ac, bus } = r;
  const env = ac.createGain();
  const end = t + CHORD_SECONDS;
  env.gain.setValueAtTime(0, t);
  env.gain.linearRampToValueAtTime(peak, t + 2.5);
  env.gain.setValueAtTime(peak, end);
  env.gain.setTargetAtTime(0, end, 1.1);
  env.connect(bus);
  kinds.forEach((type, i) => {
    const osc = ac.createOscillator();
    osc.type = type;
    osc.frequency.value = freq;
    osc.detune.value = i === 0 ? -5 : 6;
    osc.connect(env);
    osc.start(t);
    osc.stop(end + 5);
  });
}

function bell(r: Running, freq: number, t: number) {
  const { ac, bus } = r;
  const env = ac.createGain();
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(0.035, t + 0.02);
  env.gain.exponentialRampToValueAtTime(0.0001, t + 3);
  env.connect(bus);
  const osc = ac.createOscillator();
  osc.type = "sine";
  osc.frequency.value = freq;
  osc.connect(env);
  osc.start(t);
  osc.stop(t + 3.1);
}

function playChord(r: Running, chord: Chord, mood: Mood, t: number) {
  for (const note of chord.voices) voice(r, hz(note), t, 0.05, ["triangle", "sine"]);
  voice(r, hz(chord.bass), t, 0.07, ["sine"]);
  for (let i = 0; i < BELLS[mood]; i++) {
    const note = chord.voices[Math.floor(Math.random() * chord.voices.length)] + 12;
    bell(r, hz(note), t + 1 + Math.random() * (CHORD_SECONDS - 2));
  }
  // Taps follow the chord from the moment it sounds.
  const delay = Math.max(0, (t - r.ac.currentTime) * 1000);
  setTimeout(() => {
    if (running === r) setHarmony(chord.voices.map(hz));
  }, delay);
}

function schedule(r: Running) {
  while (r.nextAt < r.ac.currentTime + 1.5) {
    const mood = moodFor(currentShare());
    const progression = PROGRESSIONS[mood];
    playChord(r, progression[r.step % progression.length], mood, r.nextAt);
    r.nextAt += CHORD_SECONDS;
    r.step += 1;
  }
}

/** Starts the music with a slow fade. Returns false where Web Audio is missing. */
export function startAmbient(): boolean {
  if (running) return true;
  const ac = soundContext();
  if (!ac) return false;
  const now = ac.currentTime;

  const bus = ac.createGain();
  bus.gain.setValueAtTime(0, now);
  bus.gain.linearRampToValueAtTime(LEVEL, now + FADE_IN);

  const filter = ac.createBiquadFilter();
  filter.type = "lowpass";
  filter.Q.value = 0.4;
  filter.frequency.value = brightnessFor(currentShare());

  // A very slow sweep keeps the pad breathing.
  const lfo = ac.createOscillator();
  lfo.frequency.value = 0.05;
  const depth = ac.createGain();
  depth.gain.value = 250;
  lfo.connect(depth).connect(filter.frequency);
  lfo.start(now);

  const reverb = ac.createConvolver();
  reverb.buffer = room(ac);
  const wet = ac.createGain();
  wet.gain.value = 0.55;
  const dry = ac.createGain();
  dry.gain.value = 0.7;

  bus.connect(filter);
  filter.connect(dry).connect(ac.destination);
  filter.connect(reverb).connect(wet).connect(ac.destination);

  const r: Running = {
    ac,
    bus,
    filter,
    lfo,
    nodes: [bus, filter, depth, reverb, wet, dry],
    timer: setInterval(() => schedule(r), 500),
    nextAt: now + 0.1,
    step: 0,
  };
  running = r;
  schedule(r);
  return true;
}

/** Fades the music out and releases it. Safe to call when nothing plays. */
export function stopAmbient() {
  const r = running;
  if (!r) return;
  running = null;
  clearInterval(r.timer);
  setHarmony(null);
  const now = r.ac.currentTime;
  r.bus.gain.cancelScheduledValues(now);
  r.bus.gain.setValueAtTime(r.bus.gain.value, now);
  r.bus.gain.linearRampToValueAtTime(0, now + FADE_OUT);
  setTimeout(
    () => {
      r.lfo.stop();
      for (const node of r.nodes) node.disconnect();
    },
    FADE_OUT * 1000 + 200,
  );
}

export function ambientPlaying() {
  return running !== null;
}
