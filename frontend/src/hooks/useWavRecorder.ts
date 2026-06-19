"use client";

/**
 * useWavRecorder — records a single microphone sample and returns it as a
 * 16 kHz mono 16-bit PCM WAV Blob (PROJ-43 voice enrollment).
 *
 * MediaRecorder only emits WebM/Opus in browsers, which the gateway's
 * torchaudio.load() cannot reliably decode. We therefore capture raw PCM via
 * the Web Audio API, downsample to 16 kHz, and encode a WAV container in the
 * browser so the upload matches the gateway's ECAPA-TDNN expectations.
 *
 * Usage:
 *   const { isRecording, start, stop, cancel } = useWavRecorder();
 *   await start();                 // begin capturing
 *   const blob = await stop();     // finalise → WAV Blob (or null if too short)
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useAudioPermission } from "./useAudioPermission";

const TARGET_SAMPLE_RATE = 16000;
const PROCESSOR_BUFFER_SIZE = 4096;

function flattenChunks(chunks: Float32Array[], length: number): Float32Array {
  const out = new Float32Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

/** Linear-interpolation downsample from `inRate` to TARGET_SAMPLE_RATE. */
function downsample(input: Float32Array, inRate: number): Float32Array {
  if (inRate === TARGET_SAMPLE_RATE) return input;
  const ratio = inRate / TARGET_SAMPLE_RATE;
  const outLength = Math.floor(input.length / ratio);
  const out = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const pos = i * ratio;
    const idx = Math.floor(pos);
    const frac = pos - idx;
    const a = input[idx] ?? 0;
    const b = input[idx + 1] ?? a;
    out[i] = a + (b - a) * frac;
  }
  return out;
}

/** Encode mono Float32 PCM as a 16-bit WAV Blob. */
function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };

  const dataSize = samples.length * 2;
  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // audio format = PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }

  return new Blob([view], { type: "audio/wav" });
}

interface UseWavRecorderResult {
  isRecording: boolean;
  permissionDenied: boolean;
  /** Begin capturing. Returns false if the mic could not be acquired. */
  start: () => Promise<boolean>;
  /** Stop and return the recorded WAV, or null if nothing usable was captured. */
  stop: () => Promise<Blob | null>;
  /** Abort the current recording without producing a Blob. */
  cancel: () => void;
}

export function useWavRecorder(): UseWavRecorderResult {
  const { permissionDenied, requestStream } = useAudioPermission();
  const [isRecording, setIsRecording] = useState(false);

  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const chunksRef = useRef<Float32Array[]>([]);
  const lengthRef = useRef<number>(0);

  const teardown = useCallback(() => {
    if (processorRef.current) {
      try {
        processorRef.current.disconnect();
      } catch {
        /* ignore */
      }
      processorRef.current.onaudioprocess = null;
      processorRef.current = null;
    }
    if (sourceRef.current) {
      try {
        sourceRef.current.disconnect();
      } catch {
        /* ignore */
      }
      sourceRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (ctxRef.current) {
      const ctx = ctxRef.current;
      ctxRef.current = null;
      ctx.close().catch(() => {});
    }
  }, []);

  // Release resources if the component unmounts mid-recording.
  useEffect(() => teardown, [teardown]);

  const start = useCallback(async (): Promise<boolean> => {
    const stream = await requestStream();
    if (!stream) return false;

    let ctx: AudioContext;
    try {
      ctx = new AudioContext();
    } catch {
      stream.getTracks().forEach((t) => t.stop());
      return false;
    }

    chunksRef.current = [];
    lengthRef.current = 0;
    streamRef.current = stream;
    ctxRef.current = ctx;

    const source = ctx.createMediaStreamSource(stream);
    const processor = ctx.createScriptProcessor(PROCESSOR_BUFFER_SIZE, 1, 1);
    sourceRef.current = source;
    processorRef.current = processor;

    processor.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      // Copy — the underlying buffer is reused by the audio thread.
      const copy = new Float32Array(input.length);
      copy.set(input);
      chunksRef.current.push(copy);
      lengthRef.current += copy.length;
    };

    source.connect(processor);
    // ScriptProcessor only fires while connected to the destination. Route
    // through a muted gain node so the mic is never audible.
    const muted = ctx.createGain();
    muted.gain.value = 0;
    processor.connect(muted);
    muted.connect(ctx.destination);

    await ctx.resume().catch(() => {});
    setIsRecording(true);
    return true;
  }, [requestStream]);

  const stop = useCallback(async (): Promise<Blob | null> => {
    const ctx = ctxRef.current;
    const inRate = ctx?.sampleRate ?? TARGET_SAMPLE_RATE;
    const pcm = flattenChunks(chunksRef.current, lengthRef.current);
    chunksRef.current = [];
    lengthRef.current = 0;
    teardown();
    setIsRecording(false);

    // Require a minimal amount of audio so empty taps don't reach the gateway.
    if (pcm.length < inRate * 0.5) return null;

    const downsampled = downsample(pcm, inRate);
    return encodeWav(downsampled, TARGET_SAMPLE_RATE);
  }, [teardown]);

  const cancel = useCallback(() => {
    chunksRef.current = [];
    lengthRef.current = 0;
    teardown();
    setIsRecording(false);
  }, [teardown]);

  return { isRecording, permissionDenied, start, stop, cancel };
}
