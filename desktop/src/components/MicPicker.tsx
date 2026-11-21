import { useEffect, useRef, useState } from "react";

import { useMenuFit } from "../state/useMenuFit";
import { Icon } from "./Icon";

export interface VoiceInfo {
  deviceId: string | null;
  onSelectDevice: (id: string) => void;
  holdToRecord: boolean;
  onHoldToRecord: (on: boolean) => void;
  onVoiceMode: () => void;
}

// The microphone / input-device picker (contract §4). Enumerates real audio-input
// devices via the MediaDevices API, shows a live level meter while open, and offers
// a "Hold to record" toggle. Device selection is genuine (persisted by the caller);
// full speech-to-text is out of scope and flagged in the UI.
export function MicPicker({ voice, onClose }: { voice: VoiceInfo; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useMenuFit(ref, true); // only mounted while open
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [level, setLevel] = useState(0);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [onClose]);

  // Ask for mic access once (to unlock device labels + drive the level meter), then
  // enumerate. Everything is torn down on close.
  useEffect(() => {
    let stream: MediaStream | null = null;
    let raf = 0;
    let ctx: AudioContext | null = null;
    let cancelled = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setDenied(true);
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) return;
        const list = await navigator.mediaDevices.enumerateDevices();
        setDevices(list.filter((d) => d.kind === "audioinput"));
        // Level meter.
        ctx = new AudioContext();
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        src.connect(analyser);
        const buf = new Uint8Array(analyser.frequencyBinCount);
        const tick = () => {
          analyser.getByteFrequencyData(buf);
          const avg = buf.reduce((a, b) => a + b, 0) / buf.length;
          setLevel(Math.min(1, avg / 90));
          raf = requestAnimationFrame(tick);
        };
        tick();
      } catch {
        setDenied(true);
      }
    }
    void start();
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      void ctx?.close();
    };
  }, []);

  return (
    <div className="mic-pop" ref={ref} role="dialog" aria-label="Microphone">
      <div className="mic-meter" aria-hidden="true">
        {Array.from({ length: 14 }).map((_, i) => (
          <span key={i} className="mic-bar" style={{ opacity: level * 14 > i ? 1 : 0.2 }} />
        ))}
      </div>
      {denied && <div className="mic-denied">Microphone unavailable or permission denied.</div>}
      {devices.map((d, i) => {
        const label = d.label || `Microphone ${i + 1}`;
        const selected = voice.deviceId ? d.deviceId === voice.deviceId : d.deviceId === "default" || i === 0;
        return (
          <button key={d.deviceId || i} className={`mic-row ${selected ? "sel" : ""}`}
                  onClick={() => voice.onSelectDevice(d.deviceId)}>
            <span className="mic-row-label">{label}</span>
            {selected && <span className="mic-check" aria-hidden="true"><Icon name="check" size={14} /></span>}
          </button>
        );
      })}
      {!denied && devices.length === 0 && <div className="mic-denied">No input devices found.</div>}
      <div className="mic-divider" />
      <div className="mic-hold">
        <span className="mic-row-label">Hold to record</span>
        <button
          className={`mp-switch ${voice.holdToRecord ? "on" : ""}`}
          role="switch"
          aria-checked={voice.holdToRecord}
          aria-label="Hold to record"
          onClick={() => voice.onHoldToRecord(!voice.holdToRecord)}
        >
          <span className="mp-switch-knob" />
        </button>
      </div>
    </div>
  );
}
