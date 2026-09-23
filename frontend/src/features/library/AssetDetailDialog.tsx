import { useEffect, useMemo, useState } from "react";
import type { OutputSlot, Shot } from "../../shared/api/types";
import { Lightbox } from "../../shared/components/Lightbox";
import {
  attachVoiceToShot,
  detachVoiceFromShot,
  getProjectShots,
  type LibraryAsset,
} from "./api";

const PREVIEW_KEYS = [
  "layout",
  "fullbody_threeview",
  "master",
  "asset_sheet",
  "bust_threeview",
  "wardrobe_ref",
  "image",
  "plate",
  "video",
] as const;

const KEY_LABELS: Record<string, string> = {
  master: "Master",
  fullbody_threeview: "Full-body three-view",
  bust_threeview: "Bust three-view",
  asset_sheet: "Asset sheet",
  wardrobe_ref: "Wardrobe ref",
  layout: "Layout",
  image: "Image",
  plate: "Plate",
  video: "Video",
  input_actor: "Input · actor",
  input_wardrobe: "Input · wardrobe",
  input_scene: "Input · scene",
};

function labelForKey(key: string): string {
  if (KEY_LABELS[key]) return KEY_LABELS[key];
  if (key.startsWith("input_")) return `Input · ${key.slice(6)}`;
  return key.replace(/_/g, " ");
}

export function assetPreviewUrl(asset: LibraryAsset): string | null {
  if (asset.kind === "voices") return null;
  const urls = asset.urls || {};
  for (const key of PREVIEW_KEYS) {
    if (urls[key]) return urls[key];
  }
  return Object.values(urls).find(Boolean) || null;
}

export function assetSlots(asset: LibraryAsset): OutputSlot[] {
  const urls = asset.urls || {};
  const files = asset.files || {};
  const keys = new Set([...Object.keys(urls), ...Object.keys(files)]);
  const ordered = [
    ...PREVIEW_KEYS.filter((key) => keys.has(key)),
    ...[...keys]
      .filter((key) => !(PREVIEW_KEYS as readonly string[]).includes(key))
      .sort(),
  ];
  return ordered
    .filter((key) => urls[key])
    .map((key) => ({
      key,
      label: labelForKey(key),
      filename: files[key] || null,
      url: urls[key],
    }));
}

function voiceAttachFileKey(asset: LibraryAsset): string {
  const metaKey = String(asset.meta?.h3_file_key || "");
  if (metaKey && asset.files?.[metaKey]) return metaKey;
  if (asset.files?.audio) return "audio";
  return "reference";
}

function VoiceShotAttachPanel({ asset }: { asset: LibraryAsset }) {
  const projectId = asset.project_id;
  const [shots, setShots] = useState<Shot[] | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const ready = Boolean(asset.meta?.h3_ready);
  const fileKey = voiceAttachFileKey(asset);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    getProjectShots(projectId)
      .then((result) => {
        if (active) setShots(result);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      active = false;
    };
  }, [projectId, asset.id]);

  const apply = (updated: Shot) => {
    setShots((current) =>
      current ? current.map((shot) => (shot.id === updated.id ? updated : shot)) : current,
    );
  };

  const attach = async (shotId: string) => {
    setBusyId(shotId);
    setError("");
    try {
      apply(await attachVoiceToShot(shotId, { asset_id: asset.id, file_key: fileKey }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusyId(null);
    }
  };

  const detach = async (shotId: string) => {
    setBusyId(shotId);
    setError("");
    try {
      apply(await detachVoiceFromShot(shotId, asset.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="voice-shot-attach">
      <div className="voice-shot-attach-head">
        <h3>Attach to Shots</h3>
        {ready ? (
          <small className="voice-shot-ready">H3-ready · attaches as a mouth-sync reference</small>
        ) : (
          <small className="voice-shot-warn">
            Not H3-ready (outside the 2–15s window) — cannot attach
          </small>
        )}
      </div>
      {error ? <div className="banner error">{error}</div> : null}
      {!projectId ? <p className="empty-copy">This voice is not owned by a project.</p> : null}
      {projectId && shots == null ? <p className="empty-copy">Loading shots…</p> : null}
      {projectId && shots != null && shots.length === 0 ? (
        <p className="empty-copy">No shots in this project yet.</p>
      ) : null}
      {shots && shots.length > 0 ? (
        <ul className="voice-shot-list">
          {shots.map((shot, index) => {
            const attached = shot.voice_refs.some((ref) => ref.asset_id === asset.id);
            const full = shot.voice_refs.length >= 3;
            const disabled = busyId === shot.id || (!attached && (!ready || full));
            const reason = !ready
              ? "Not H3-ready"
              : full
                ? "Shot already has 3 voices"
                : "";
            return (
              <li className="voice-shot-row" key={shot.id}>
                <span className="voice-shot-name">
                  <strong>Shot {String(index + 1).padStart(2, "0")}</strong>
                  <small>{shot.title}</small>
                </span>
                {attached ? (
                  <button
                    type="button"
                    className="btn secondary sm"
                    disabled={disabled}
                    onClick={() => void detach(shot.id)}
                  >
                    {busyId === shot.id ? "…" : "Detach"}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn primary sm"
                    disabled={disabled}
                    title={reason}
                    onClick={() => void attach(shot.id)}
                  >
                    {busyId === shot.id ? "…" : "Attach"}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

export function AssetDetailDialog({
  asset,
  busy = false,
  onClose,
  onDelete,
  onEdit,
}: {
  asset: LibraryAsset;
  busy?: boolean;
  onClose: () => void;
  onDelete?: () => void;
  onEdit?: () => void;
}) {
  const slots = useMemo(() => assetSlots(asset), [asset]);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  return (
    <>
      <div
        className="folder-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${asset.name} assets`}
        onClick={onClose}
      >
        <div className="folder-modal-panel" onClick={(event) => event.stopPropagation()}>
          <div className="folder-modal-head">
            <div>
              <h2 className="folder-modal-title">{asset.name}</h2>
              <p className="muted tiny">
                {asset.kind} · {asset.pipeline_id || "asset"}
                {asset.job_id ? ` · ${asset.job_id}` : ""}
                {asset.seed != null ? ` · seed ${asset.seed}` : ""}
              </p>
              {asset.notes ? <p className="folder-modal-notes">{asset.notes}</p> : null}
            </div>
            <div className="folder-modal-actions">
              {onEdit ? (
                <button type="button" className="btn secondary sm" disabled={busy} onClick={onEdit}>
                  Edit
                </button>
              ) : null}
              {onDelete ? (
                <button type="button" className="btn danger sm" disabled={busy} onClick={onDelete}>
                  Delete
                </button>
              ) : null}
              <button type="button" className="btn secondary sm" onClick={onClose}>
                Close
              </button>
            </div>
          </div>

          {slots.length === 0 ? (
            <p className="empty-copy">No files in this asset.</p>
          ) : (
            <div className="folder-file-grid">
              {slots.map((slot, index) =>
                asset.kind === "voices" ? (
                  <div key={slot.key} className="folder-file-card voice-file-card">
                    <div className="folder-file-label">{slot.label}</div>
                    <audio controls preload="metadata" src={slot.url || undefined} />
                    {slot.filename ? <div className="muted tiny ellipsis">{slot.filename}</div> : null}
                  </div>
                ) : (
                  <button
                    key={slot.key}
                    type="button"
                    className="folder-file-card"
                    onClick={() => setLightboxIndex(index)}
                  >
                    <div className="folder-file-thumb">
                      {slot.url ? <img src={slot.url} alt={slot.label} /> : <div className="output-empty">—</div>}
                    </div>
                    <div className="folder-file-label">{slot.label}</div>
                    {slot.filename ? <div className="muted tiny ellipsis">{slot.filename}</div> : null}
                  </button>
                ),
              )}
            </div>
          )}

          {asset.kind === "voices" ? <VoiceShotAttachPanel asset={asset} /> : null}
        </div>
      </div>

      {lightboxIndex != null ? (
        <Lightbox
          slots={slots}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onIndex={setLightboxIndex}
        />
      ) : null}
    </>
  );
}
