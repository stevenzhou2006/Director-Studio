import { parseError } from "../../shared/api/client";
import type { JobStatus, OutputSlot } from "../../shared/api/types";

export type { JobStatus, OutputSlot };

export interface SpeakerRecord {
  id: string;
  project_id: string;
  name: string;
  slug: string;
  ref_text: string;
  source: string;
  source_asset_id: string | null;
  duration_s: number | null;
  status: "registering" | "ready" | "failed";
  register_job_id: string | null;
  created_at: string;
  engine_ready: boolean;
  engine_files: Record<string, boolean>;
  preview_url: string | null;
}

export interface TtsJobRecord {
  id: string;
  status: JobStatus;
  name: string;
  notes: string;
  seed: number | null;
  fixed_seed: boolean;
  error: string | null;
  comfy_prompt_id: string | null;
  created_at: string;
  updated_at: string;
  outputs: Record<string, OutputSlot>;
  output_order: string[];
  input_previews: Record<string, string>;
  pipeline_id: string;
  style: string | null;
  speaker_id: string | null;
}

export interface SavedVoiceRecord {
  id: string;
  name: string;
  notes: string;
  seed: number | null;
  job_id: string;
  created_at: string;
  files: Record<string, string | null>;
  urls: Record<string, string>;
  meta: Record<string, unknown>;
  project_id: string | null;
}

export async function listSpeakers(projectId: string): Promise<SpeakerRecord[]> {
  const res = await fetch(
    `/api/tts/speakers?project_id=${encodeURIComponent(projectId)}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  const data = (await res.json()) as { items: SpeakerRecord[] };
  return data.items ?? [];
}

export async function registerSpeaker(form: FormData): Promise<{
  speaker: SpeakerRecord;
  job: TtsJobRecord;
}> {
  const res = await fetch("/api/tts/speakers", { method: "POST", body: form });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function deleteSpeaker(
  projectId: string,
  speakerId: string,
): Promise<void> {
  const res = await fetch(
    `/api/tts/speakers/${encodeURIComponent(speakerId)}?project_id=${encodeURIComponent(projectId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function generateSpeech(form: FormData): Promise<TtsJobRecord> {
  const res = await fetch("/api/tts/generate", { method: "POST", body: form });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getTtsJob(jobId: string): Promise<TtsJobRecord> {
  const res = await fetch(`/api/tts/jobs/${encodeURIComponent(jobId)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function cancelTtsJob(jobId: string): Promise<TtsJobRecord> {
  const res = await fetch(
    `/api/tts/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function saveTtsJob(
  jobId: string,
  body?: { name?: string; notes?: string; project_id?: string | null },
): Promise<SavedVoiceRecord> {
  const res = await fetch(
    `/api/tts/jobs/${encodeURIComponent(jobId)}/save`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export const TTS_ACTIVE_STATUSES: JobStatus[] = [
  "queued",
  "uploading",
  "running",
];
