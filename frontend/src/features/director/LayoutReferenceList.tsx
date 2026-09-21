import { useState } from "react";
import {
  layoutPreviewUrl,
  type LayoutReference,
  type LayoutReviewStatus,
  type Shot,
} from "../../shared/api/types";
import { isDisplayableLayout, isRetiredLayout } from "../../shared/layoutReferenceStatus";
import { removeLayoutReference, useLayout } from "./api";

interface LayoutReferenceListProps {
  shot: Shot;
  busy: boolean;
  onDiscussAddReference: (description: string) => void;
  onOpenImage: (assetId: string) => void;
  onShotUpdated?: (shot: Shot) => void;
}

function isTerminalJobFailure(layout: LayoutReference): boolean {
  return layout.job_status === "failed" || layout.job_status === "cancelled";
}

function isActiveJob(layout: LayoutReference): boolean {
  return (
    layout.job_status === "queued"
    || layout.job_status === "uploading"
    || layout.job_status === "running"
  );
}

function reviewLabel(status: LayoutReviewStatus | null, layout: LayoutReference): string {
  if (layout.job_status === "failed") return "generation failed";
  if (layout.job_status === "cancelled") return "generation cancelled";
  if (layout.superseded_by) return "previous";
  if (status === "reject") return "rejected";
  if (layout.asset_id) return layout.selected_for_h3 ? "in use" : "not used";
  if (!status) return "awaiting generation";
  return status.replace(/_/g, " ");
}

function shouldDefaultExpand(layout: LayoutReference): boolean {
  if (isTerminalJobFailure(layout)) return true;
  if (layout.job_status === "queued" || layout.job_status === "running") return true;
  return !layout.review_status
    || layout.review_status === "pending_review"
    || layout.review_status === "usable_with_repair";
}

function LayoutReferenceCard({
  shot,
  layout,
  onOpenImage,
  onRemove,
  removing = false,
  removeDisabled = false,
  onUse,
  using = false,
  useDisabled = false,
}: {
  shot: Shot;
  layout: LayoutReference;
  onOpenImage: (assetId: string) => void;
  onRemove?: (layout: LayoutReference) => void;
  removing?: boolean;
  removeDisabled?: boolean;
  onUse?: (layout: LayoutReference) => void;
  using?: boolean;
  useDisabled?: boolean;
}) {
  const picture = layout.asset_id
    ? shot.refs.find(
        (ref) => ref.role === "layout_ref_frame" && ref.asset_id === layout.asset_id,
      )
    : undefined;
  const status = layout.review_status;
  const terminalJobFailure = isTerminalJobFailure(layout);
  const imageUrl = layoutPreviewUrl(layout.asset_id);

  return (
    <article
      className={`layout-reference-card${layout.selected_for_h3 ? " is-current" : ""}`}
      aria-labelledby={`layout-${layout.id}-title`}
    >
      <details className="layout-reference-details" open={shouldDefaultExpand(layout)}>
        <summary className="layout-reference-summary">
          <span className="layout-reference-kicker">Layout</span>
          <h3 id={`layout-${layout.id}-title`} className="layout-reference-title">
            {layout.purpose || layout.id}
          </h3>
          <span className={`gate-badge layout-review-${status || "queued"}`}>
            {reviewLabel(status, layout)}
          </span>
          {layout.selected_for_h3 ? (
            <span className="layout-current-badge">Current</span>
          ) : null}
          {picture ? <span className="layout-picture-badge">Picture {picture.picture_index}</span> : null}
          {onUse
          && layout.asset_id
          && !layout.selected_for_h3
          && layout.review_status !== "reject" ? (
            <button
              type="button"
              className="layout-use-button"
              aria-label={`Use ${layout.purpose || "layout"} for H3`}
              title={
                isActiveJob(layout)
                  ? "Wait for the running job to finish"
                  : "Use this Layout for the prompt and H3 run"
              }
              disabled={useDisabled || using || isActiveJob(layout)}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onUse(layout);
              }}
            >
              {using ? "Using…" : "Use this Layout"}
            </button>
          ) : null}
          {onRemove ? (
            <button
              type="button"
              className="layout-remove-button"
              aria-label={`Remove ${layout.purpose || "layout reference"}`}
              title={isActiveJob(layout)
                ? "Cannot remove a reference frame while its job is running"
                : "Remove this reference frame"}
              disabled={removeDisabled || removing || isActiveJob(layout)}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onRemove(layout);
              }}
            >
              {removing ? "Removing…" : "Remove"}
            </button>
          ) : null}
        </summary>
        <div className="layout-reference-body">
          <div className="layout-reference-rail">
            <span>{layout.time_hint || "time not specified"}</span>
            <span>{layout.source_refs.length} source{layout.source_refs.length === 1 ? "" : "s"}</span>
            {layout.origin?.kind === "clip_tail_frame" ? (
              <span className="layout-origin-label">
                {`Tail frame · ${layout.origin.source_shot_id} · v${layout.origin.source_generation} · ${layout.origin.output_kind}`}
              </span>
            ) : null}
          </div>
          <div className="layout-reference-evidence">
            {imageUrl ? (
              <button
                type="button"
                className="layout-reference-image"
                onClick={() => layout.asset_id && onOpenImage(layout.asset_id)}
                aria-label={`Open ${layout.purpose || "layout reference"}`}
              >
                <img src={imageUrl} alt={layout.purpose || "layout reference"} />
              </button>
            ) : (
              <div className="layout-reference-empty">
                {terminalJobFailure
                  ? layout.job_status === "cancelled"
                    ? "Reference generation cancelled"
                    : "Reference generation failed"
                  : layout.job_id ? "Generating reference frame" : "No reference frame yet"}
              </div>
            )}
            <p className="layout-reference-state">{layout.state_description || "No state description provided."}</p>
          </div>
          <div className="layout-reference-controls">
            <span className={`gate-badge layout-review-${status || "queued"}`}>
              {reviewLabel(status, layout)}
            </span>
            <span className="layout-job">{layout.job_id ? `Job ${layout.job_id}` : "No generation job"}</span>
            {terminalJobFailure ? (
              <p className="layout-action-error" role="alert">
                {layout.job_error || (layout.job_status === "cancelled"
                  ? "Layout generation was cancelled. Add a new reference frame to try again."
                  : "Layout generation failed. Add a new reference frame to try again.")}
              </p>
            ) : null}
            {layout.review_feedback ? <p className="layout-feedback">{layout.review_feedback}</p> : null}
            {layout.feedback_source === "director_chat" ? (
              <span className="layout-feedback-source" title={layout.feedback_quote || undefined}>
                From Director chat
              </span>
            ) : null}
            {status === "reject" ? (
              <span className="layout-selection-hint">This Layout is not used.</span>
            ) : picture ? (
              <span className="layout-selection-hint">Used automatically in prompt and H3</span>
            ) : layout.asset_id ? (
              <span className="layout-selection-hint">Previous Layout — not submitted</span>
            ) : null}
          </div>
        </div>
      </details>
    </article>
  );
}

export function LayoutReferenceList({ shot, busy, onDiscussAddReference, onOpenImage, onShotUpdated }: LayoutReferenceListProps) {
  const layouts = shot.layout_refs;
  const byNewestFirst = (a: LayoutReference, b: LayoutReference) =>
    (b.created_at || "").localeCompare(a.created_at || "") || b.id.localeCompare(a.id);
  const displayableLayouts = [...layouts].filter(isDisplayableLayout);
  const currentLayouts = displayableLayouts
    .filter((layout) => !isRetiredLayout(layout))
    .sort(byNewestFirst);
  const retiredLayouts = displayableLayouts
    .filter(isRetiredLayout)
    .sort(byNewestFirst);
  const [adding, setAdding] = useState(false);
  const [description, setDescription] = useState("");
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [usingId, setUsingId] = useState<string | null>(null);
  const [useError, setUseError] = useState<string | null>(null);

  const discuss = () => {
    const trimmed = description.trim();
    if (!trimmed) return;
    onDiscussAddReference(trimmed);
    setDescription("");
    setAdding(false);
  };

  const removeReference = async (layout: LayoutReference) => {
    setRemovingId(layout.id);
    setRemoveError(null);
    try {
      const updated = await removeLayoutReference(shot.id, layout.id);
      onShotUpdated?.(updated);
    } catch (cause) {
      setRemoveError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setRemovingId(null);
    }
  };

  const useReference = async (layout: LayoutReference) => {
    setUsingId(layout.id);
    setUseError(null);
    try {
      const updated = await useLayout(shot.id, layout.id);
      onShotUpdated?.(updated);
    } catch (cause) {
      setUseError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setUsingId(null);
    }
  };

  const cardProps = (layout: LayoutReference) => ({
    onRemove: removeReference,
    removing: removingId === layout.id,
    removeDisabled: busy,
    onUse: useReference,
    using: usingId === layout.id,
    useDisabled: busy,
  });

  return (
    <section className="layout-reference-list" aria-label="Layout references">
      {removeError ? (
        <div className="banner error" role="alert">
          Could not remove reference frame: {removeError}
        </div>
      ) : null}
      {useError ? (
        <div className="banner error" role="alert">
          Could not use this Layout: {useError}
        </div>
      ) : null}
      {currentLayouts.map((layout) => (
        <LayoutReferenceCard
          key={layout.id}
          shot={shot}
          layout={layout}
          onOpenImage={onOpenImage}
          {...cardProps(layout)}
        />
      ))}
      {retiredLayouts.length ? (
        <details className="layout-history">
          <summary>Previous layouts ({retiredLayouts.length})</summary>
          <div className="layout-history-list">
            {retiredLayouts.map((layout) => (
              <LayoutReferenceCard
                key={layout.id}
                shot={shot}
                layout={layout}
                onOpenImage={onOpenImage}
                {...cardProps(layout)}
              />
            ))}
          </div>
        </details>
      ) : null}
      {layouts.length > 0 ? (
        <div className="layout-add-reference">
          <button
            type="button"
            className="mode-chip"
            disabled={busy}
            aria-expanded={adding}
            onClick={() => setAdding((open) => !open)}
          >
            Add reference frame
          </button>
          {adding ? (
            <div className="layout-brief-form">
              <label>
                Description
                <textarea
                  rows={3}
                  value={description}
                  disabled={busy}
                  placeholder="What should an additional reference frame help establish?"
                  onChange={(event) => setDescription(event.target.value)}
                />
              </label>
              <button type="button" className="btn primary" disabled={busy || !description.trim()} onClick={discuss}>
                Discuss with Director
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
