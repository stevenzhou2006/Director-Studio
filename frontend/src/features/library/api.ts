import { parseError } from "../../shared/api/client";
import type { Shot } from "../../shared/api/types";

export type LibraryKind =
  | "actors"
  | "costumes"
  | "scenes"
  | "props"
  | "layouts"
  | "voices";

export interface LibraryAsset {
  id: string;
  kind: string;
  name: string;
  notes: string;
  pipeline_id: string;
  job_id: string;
  seed: number | null;
  created_at: string;
  files: Record<string, string | null>;
  meta: Record<string, unknown>;
  urls: Record<string, string>;
  project_id: string | null;
}

export async function listLibraryAssets(
  kind: LibraryKind,
  projectId: string | null,
  includeUnassigned = false,
): Promise<LibraryAsset[]> {
  if (!projectId) return [];
  const qs = new URLSearchParams({
    kind,
    project_id: projectId,
    include_unassigned: includeUnassigned ? "true" : "false",
  });
  const res = await fetch(`/api/library?${qs}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function importExternalAsset(opts: {
  file: File;
  kind: LibraryKind;
  name?: string;
  notes?: string;
  projectId: string;
}): Promise<LibraryAsset> {
  const fd = new FormData();
  fd.append("file", opts.file);
  fd.append("kind", opts.kind);
  fd.append("name", opts.name || opts.file.name.replace(/\.[^.]+$/, ""));
  fd.append("notes", opts.notes || "");
  fd.append("project_id", opts.projectId);
  const res = await fetch("/api/library/import", { method: "POST", body: fd });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function deleteLibraryAsset(
  kind: string,
  assetId: string,
): Promise<void> {
  const res = await fetch(
    `/api/library/${encodeURIComponent(kind)}/${encodeURIComponent(assetId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function updateLibraryAsset(
  kind: string,
  assetId: string,
  metadata: { name: string; notes: string },
): Promise<LibraryAsset> {
  const res = await fetch(
    `/api/library/${encodeURIComponent(kind)}/${encodeURIComponent(assetId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(metadata),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getProjectShots(projectId: string): Promise<Shot[]> {
  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
  if (!res.ok) throw new Error(await parseError(res));
  const detail = (await res.json()) as { shots?: Shot[] };
  return detail.shots ?? [];
}

export async function attachVoiceToShot(
  shotId: string,
  body: { asset_id: string; file_key?: string; speaker?: string },
): Promise<Shot> {
  const res = await fetch(`/api/shots/${encodeURIComponent(shotId)}/voice-refs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_key: "audio", speaker: "", ...body }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function detachVoiceFromShot(
  shotId: string,
  assetId: string,
): Promise<Shot> {
  const res = await fetch(
    `/api/shots/${encodeURIComponent(shotId)}/voice-refs/${encodeURIComponent(assetId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}
