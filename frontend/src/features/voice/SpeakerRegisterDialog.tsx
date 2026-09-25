import { useEffect, useRef, useState } from "react";
import {
  registerSpeaker,
  getTtsJob,
  TTS_ACTIVE_STATUSES,
  type TtsJobRecord,
} from "./api";

const RECOMMENDED_MIN = 5;
const RECOMMENDED_MAX = 15;
const HARD_MIN = 2;
const HARD_MAX = 30;

export function SpeakerRegisterDialog({
  projectId,
  onClose,
  onRegistered,
}: {
  projectId: string;
  onClose: () => void;
  onRegistered: () => void;
}) {
  const [name, setName] = useState("");
  const [refText, setRefText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<TtsJobRecord | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (!job || !TTS_ACTIVE_STATUSES.includes(job.status)) return;
    pollRef.current = window.setInterval(async () => {
      try {
        const next = await getTtsJob(job.id);
        setJob(next);
        if (!TTS_ACTIVE_STATUSES.includes(next.status)) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          if (next.status === "succeeded") onRegistered();
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    }, 1500);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [job, onRegistered]);

  const onPickFile = (picked: File | null) => {
    setFile(picked);
    setDuration(null);
    if (!picked) return;
    const url = URL.createObjectURL(picked);
    const probe = new Audio();
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      const d = Number.isFinite(probe.duration) ? probe.duration : null;
      setDuration(d);
      URL.revokeObjectURL(url);
    };
    probe.onerror = () => URL.revokeObjectURL(url);
    probe.src = url;
  };

  const durationBlocked =
    duration !== null && (duration < HARD_MIN || duration > HARD_MAX);
  const durationWarn =
    duration !== null &&
    !durationBlocked &&
    (duration < RECOMMENDED_MIN || duration > RECOMMENDED_MAX);

  const canSubmit =
    !busy &&
    name.trim().length > 0 &&
    refText.trim().length > 0 &&
    file !== null &&
    !durationBlocked;

  const onSubmit = async () => {
    if (!canSubmit || !file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("project_id", projectId);
      form.append("name", name.trim());
      form.append("ref_text", refText.trim());
      form.append("reference_audio", file, file.name);
      const result = await registerSpeaker(form);
      setJob(result.job);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  const failed = job !== null && job.status !== "succeeded" && !TTS_ACTIVE_STATUSES.includes(job.status);
  const working = job !== null && TTS_ACTIVE_STATUSES.includes(job.status);

  return (
    <div
      className="folder-modal voice-register-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="voice-register-title"
      onClick={busy && !working ? onClose : undefined}
    >
      <div
        className="folder-modal-panel voice-register-panel"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="folder-modal-head">
          <div>
            <span className="mobile-eyebrow">Voice Cloning</span>
            <h2 className="folder-modal-title" id="voice-register-title">
              New speaker from reference
            </h2>
          </div>
          <button
            type="button"
            className="btn secondary sm"
            onClick={onClose}
            disabled={working}
          >
            Close
          </button>
        </div>

        {error ? <div className="banner error">{error}</div> : null}
        {failed ? (
          <div className="banner error">
            Registration failed: {job?.error || job?.status}
          </div>
        ) : null}

        {working ? (
          <div className="banner ok voice-register-progress">
            Extracting voice features… this takes a moment while the TTS model
            loads. Keep this dialog open.
          </div>
        ) : (
          <div className="import-form">
            <label className="field field-span-2">
              <span>Speaker name</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. 隆昌女孩 · 相思"
                disabled={busy}
              />
            </label>
            <label className="field field-span-2">
              <span>Reference audio (5–15s recommended)</span>
              <input
                type="file"
                accept="audio/*,.wav,.mp3,.flac,.m4a,.ogg"
                disabled={busy}
                onChange={(e) => {
                  const picked = e.target.files?.[0] || null;
                  e.target.value = "";
                  onPickFile(picked);
                }}
              />
            </label>
            {duration !== null ? (
              <div
                className={`voice-duration-hint ${
                  durationBlocked ? "bad" : durationWarn ? "warn" : "ok"
                }`}
              >
                {duration.toFixed(1)}s
                {durationBlocked
                  ? " — outside the 2–30s limit; pick a shorter/longer clip"
                  : durationWarn
                    ? " — usable, but 5–15s clones best"
                    : " — good length"}
              </div>
            ) : null}
            <label className="field field-span-2">
              <span>Transcript (ref_text) — required</span>
              <textarea
                rows={3}
                value={refText}
                onChange={(e) => setRefText(e.target.value)}
                placeholder="Type EXACTLY what is spoken in the reference audio…"
                disabled={busy}
              />
            </label>
            <p className="field-hint">
              The transcript is saved together with the voice features. It must
              match the audio content — after registration you never type it
              again, and any text you generate later keeps this same accent.
            </p>
            <div className="voice-register-actions">
              <button
                type="button"
                className="btn primary"
                onClick={() => void onSubmit()}
                disabled={!canSubmit}
              >
                Register voice
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
