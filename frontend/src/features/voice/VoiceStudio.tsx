import { useCallback, useEffect, useState } from "react";
import { useProject } from "../../shared/project/ProjectContext";
import { attachVoiceToShot, getProjectShots } from "../library/api";
import type { Shot } from "../../shared/api/types";
import {
  cancelTtsJob,
  deleteSpeaker,
  generateSpeech,
  getTtsJob,
  listSpeakers,
  saveTtsJob,
  TTS_ACTIVE_STATUSES,
  type SavedVoiceRecord,
  type SpeakerRecord,
  type TtsJobRecord,
} from "./api";
import { SpeakerRegisterDialog } from "./SpeakerRegisterDialog";

function speakerStatusBadge(s: SpeakerRecord) {
  if (s.status === "ready" && s.engine_ready) {
    return <span className="voice-ready">Ready</span>;
  }
  if (s.status === "registering") {
    return <span className="voice-status registering">Registering…</span>;
  }
  return <span className="voice-status failed">Failed</span>;
}

export function VoiceStudio() {
  const { projectId, libraryRevision, notifyLibraryChanged } = useProject();
  const [speakers, setSpeakers] = useState<SpeakerRecord[]>([]);
  const [showRegister, setShowRegister] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [speakerId, setSpeakerId] = useState("");
  const [text, setText] = useState("");
  const [leadSilence, setLeadSilence] = useState("0");
  const [tailSilence, setTailSilence] = useState("0");
  const [speed, setSpeed] = useState(1.0);
  const [seed, setSeed] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [job, setJob] = useState<TtsJobRecord | null>(null);
  const [saved, setSaved] = useState<SavedVoiceRecord | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [assignShot, setAssignShot] = useState("");

  const refreshSpeakers = useCallback(() => {
    if (!projectId) {
      setSpeakers([]);
      return;
    }
    listSpeakers(projectId)
      .then((items) => {
        setSpeakers(items);
        setSpeakerId((current) => {
          if (current && items.some((s) => s.id === current && s.engine_ready)) {
            return current;
          }
          const first = items.find((s) => s.engine_ready);
          return first ? first.id : "";
        });
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [projectId]);

  useEffect(() => {
    refreshSpeakers();
  }, [refreshSpeakers, libraryRevision]);

  useEffect(() => {
    if (!job || !TTS_ACTIVE_STATUSES.includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        setJob(await getTtsJob(job.id));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job]);

  const jobActive = job !== null && TTS_ACTIVE_STATUSES.includes(job.status);
  const jobDone = job !== null && job.status === "succeeded";
  const audioSlot = jobDone ? job.outputs?.audio : undefined;
  const paddedSlot = jobDone ? job.outputs?.audio_padded : undefined;
  const resultUrl = paddedSlot?.url || audioSlot?.url || null;

  const onGenerate = async () => {
    if (!projectId || !speakerId || !text.trim()) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const form = new FormData();
      form.append("project_id", projectId);
      form.append("speaker_id", speakerId);
      form.append("text", text.trim());
      form.append("lead_silence_s", leadSilence || "0");
      form.append("tail_silence_s", tailSilence || "0");
      form.append("speed", String(speed));
      if (seed.trim()) form.append("seed", seed.trim());
      setJob(await generateSpeech(form));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onCancel = async () => {
    if (!job) return;
    try {
      setJob(await cancelTtsJob(job.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const onSave = async () => {
    if (!job || !projectId) return;
    setBusy(true);
    setError(null);
    try {
      const record = await saveTtsJob(job.id, {
        name: `Speech · ${text.trim().slice(0, 16)}`,
        notes: text.trim().slice(0, 400),
        project_id: projectId,
      });
      setSaved(record);
      notifyLibraryChanged();
      getProjectShots(projectId)
        .then(setShots)
        .catch(() => setShots([]));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onAssign = async () => {
    if (!saved || !assignShot) return;
    setBusy(true);
    setError(null);
    try {
      const fileKey = String(saved.meta?.h3_file_key || "audio");
      await attachVoiceToShot(assignShot, {
        asset_id: saved.id,
        file_key: fileKey,
        speaker: String(saved.meta?.speaker_name || ""),
      });
      notifyLibraryChanged();
      setAssignShot("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteSpeaker = async (s: SpeakerRecord) => {
    if (!projectId) return;
    if (!window.confirm(`Delete speaker “${s.name}” and its saved voice files?`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteSpeaker(projectId, s.id);
      refreshSpeakers();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const readySpeakers = speakers.filter((s) => s.engine_ready);
  const savedH3Ready = Boolean(saved?.meta?.h3_ready);

  return (
    <div className="voice-studio">
      {error ? <div className="banner error">{error}</div> : null}

      <section className="section-card voice-studio-section" aria-label="Speakers">
        <div className="section-card-head">
          <h2 className="section-card-title">Speakers</h2>
          <button
            type="button"
            className="btn primary sm"
            disabled={!projectId || busy}
            onClick={() => setShowRegister(true)}
          >
            + New speaker
          </button>
        </div>
        <p className="field-hint">
          Register a 5–15 second dialect sample once. Its voice features and
          transcript are saved together, so every later line keeps the exact
          same accent without re-entering anything.
        </p>
        {speakers.length === 0 ? (
          <div className="empty-state-card">
            <p className="empty-copy">
              No speakers yet. Click “+ New speaker” to register a reference
              audio clip (for example a 隆昌 dialect recitation).
            </p>
          </div>
        ) : (
          <div className="voice-speaker-grid">
            {speakers.map((s) => (
              <article key={s.id} className="library-card voice-card speaker-card">
                <div className="voice-card-open">
                  <div className="voice-card-head">
                    <div>
                      <h3>{s.name}</h3>
                      <div className="muted tiny">
                        {s.duration_s ? `${s.duration_s.toFixed(1)}s ref` : "Speaker"}
                      </div>
                    </div>
                    {speakerStatusBadge(s)}
                  </div>
                  {s.preview_url ? (
                    <audio controls preload="metadata" src={s.preview_url} />
                  ) : null}
                  <p className="notes voice-ref-text" title={s.ref_text}>
                    “{s.ref_text}”
                  </p>
                  <div className="voice-speaker-actions">
                    <button
                      type="button"
                      className="btn secondary sm"
                      disabled={!s.engine_ready}
                      onClick={() => {
                        setSpeakerId(s.id);
                        document
                          .getElementById("voice-generate-text")
                          ?.focus();
                      }}
                    >
                      Use
                    </button>
                    <button
                      type="button"
                      className="btn secondary sm danger"
                      disabled={busy}
                      onClick={() => void onDeleteSpeaker(s)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section
        className="section-card voice-studio-section"
        aria-label="Generate speech"
      >
        <div className="section-card-head">
          <h2 className="section-card-title">Generate speech</h2>
        </div>
        {readySpeakers.length === 0 ? (
          <div className="empty-state-card">
            <p className="empty-copy">
              Register a speaker first — generation uses a saved voice.
            </p>
          </div>
        ) : (
          <>
            <div className="voice-generate-form">
              <label className="field">
                <span>Voice</span>
                <select
                  value={speakerId}
                  onChange={(e) => setSpeakerId(e.target.value)}
                  disabled={jobActive}
                >
                  {readySpeakers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field-span-2">
                <span>Text to speak</span>
                <textarea
                  id="voice-generate-text"
                  rows={4}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Any line or poem — e.g. 床前明月光，疑是地上霜。举头望明月，低头思故乡。"
                  disabled={jobActive}
                />
              </label>
              <button
                type="button"
                className="btn secondary sm voice-advanced-toggle"
                onClick={() => setShowAdvanced((v) => !v)}
              >
                {showAdvanced ? "Hide options" : "Options"}
              </button>
              {showAdvanced ? (
                <div className="voice-advanced">
                  <div className="field voice-speed-field">
                    <span>Speed</span>
                    <div className="voice-speed-control">
                      <button
                        type="button"
                        className="btn secondary sm"
                        aria-label="Decrease speed"
                        disabled={jobActive || speed <= 0.5 + 1e-6}
                        onClick={() =>
                          setSpeed((s) => Math.max(0.5, Math.round((s - 0.1) * 10) / 10))
                        }
                      >
                        −
                      </button>
                      <span className="voice-speed-value">{speed.toFixed(1)}×</span>
                      <button
                        type="button"
                        className="btn secondary sm"
                        aria-label="Increase speed"
                        disabled={jobActive || speed >= 2.0 - 1e-6}
                        onClick={() =>
                          setSpeed((s) => Math.min(2.0, Math.round((s + 0.1) * 10) / 10))
                        }
                      >
                        +
                      </button>
                      {Math.abs(speed - 1.0) > 1e-6 ? (
                        <button
                          type="button"
                          className="btn link sm"
                          onClick={() => setSpeed(1.0)}
                        >
                          reset
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <label className="field">
                    <span>Lead silence (s, H3 mouth-sync)</span>
                    <input
                      type="number"
                      min="0"
                      max="10"
                      step="0.1"
                      value={leadSilence}
                      onChange={(e) => setLeadSilence(e.target.value)}
                      disabled={jobActive}
                    />
                  </label>
                  <label className="field">
                    <span>Tail silence (s)</span>
                    <input
                      type="number"
                      min="0"
                      max="10"
                      step="0.1"
                      value={tailSilence}
                      onChange={(e) => setTailSilence(e.target.value)}
                      disabled={jobActive}
                    />
                  </label>
                  <label className="field">
                    <span>Seed (blank = random)</span>
                    <input
                      value={seed}
                      onChange={(e) => setSeed(e.target.value)}
                      placeholder="random"
                      disabled={jobActive}
                    />
                  </label>
                </div>
              ) : null}
              <div className="voice-generate-actions">
                <button
                  type="button"
                  className="btn primary"
                  disabled={!speakerId || !text.trim() || busy || jobActive}
                  onClick={() => void onGenerate()}
                >
                  {jobActive ? "Generating…" : "Generate"}
                </button>
                {jobActive ? (
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={() => void onCancel()}
                  >
                    Cancel
                  </button>
                ) : null}
              </div>
            </div>

            {job && !jobDone ? (
              <div className="banner">
                Job {job.id} · {job.status}
                {job.error ? ` · ${job.error}` : ""}
              </div>
            ) : null}

            {jobDone && resultUrl ? (
              <div className="voice-result-card">
                <audio controls src={resultUrl} />
                <div className="voice-result-actions">
                  {saved ? (
                    <>
                      <span className="voice-ready">Saved · {saved.id}</span>
                      {savedH3Ready ? (
                        <span className="voice-ready">H3 Ready</span>
                      ) : (
                        <span
                          className="voice-status"
                          title="Outside the 2–15s H3 voice-reference window"
                        >
                          Not H3-ready
                        </span>
                      )}
                      {savedH3Ready ? (
                        <span className="voice-assign">
                          <select
                            value={assignShot}
                            onChange={(e) => setAssignShot(e.target.value)}
                            disabled={busy}
                          >
                            <option value="">Assign to shot…</option>
                            {shots.map((shot, i) => (
                              <option key={shot.id} value={shot.id}>
                                #{i + 1} {shot.title || shot.id}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="btn secondary sm"
                            disabled={!assignShot || busy}
                            onClick={() => void onAssign()}
                          >
                            Attach
                          </button>
                        </span>
                      ) : (
                        <span className="field-hint">
                          Too long for an H3 voice reference (2–15s). Use it as
                          a production track or trim a shorter phrase.
                        </span>
                      )}
                    </>
                  ) : (
                    <button
                      type="button"
                      className="btn primary sm"
                      disabled={busy}
                      onClick={() => void onSave()}
                    >
                      Save to Voice Library
                    </button>
                  )}
                </div>
              </div>
            ) : null}
          </>
        )}
      </section>

      {showRegister && projectId ? (
        <SpeakerRegisterDialog
          projectId={projectId}
          onClose={() => setShowRegister(false)}
          onRegistered={() => {
            refreshSpeakers();
            setShowRegister(false);
          }}
        />
      ) : null}
    </div>
  );
}
