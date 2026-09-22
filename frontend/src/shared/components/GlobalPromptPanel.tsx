import { useEffect, useState } from "react";
import {
  expandProjectDirection,
  getProjectDirection,
  saveProjectDirection,
} from "../../features/director/api";

/**
 * Project direction. Write a rough note, ask the Director LLM to expand it into
 * detailed, checkable rules, then save. The backend appends the saved text to every
 * shot's H3 prompt and every reference-image prompt of the current project. The
 * negative list is applied to image pipelines that support a negative prompt.
 */
export function GlobalPromptPanel({ projectId }: { projectId?: string }) {
  const [brief, setBrief] = useState("");
  const [detail, setDetail] = useState("");
  const [negative, setNegative] = useState("");
  const [stored, setStored] = useState({ detail: "", negative: "" });
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) {
      setDetail("");
      setNegative("");
      setStored({ detail: "", negative: "" });
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    getProjectDirection(projectId)
      .then((value) => {
        if (cancelled) return;
        setDetail(value.detail);
        setNegative(value.negative);
        setStored(value);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const dirty =
    detail.trim() !== stored.detail.trim() ||
    negative.trim() !== stored.negative.trim();

  const generate = async () => {
    if (!projectId) return;
    setGenerating(true);
    setError(null);
    try {
      const expanded = await expandProjectDirection(projectId, brief, detail);
      setDetail(expanded);
      setSaved(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const save = async () => {
    if (!projectId) return;
    setSaving(true);
    setError(null);
    try {
      const value = await saveProjectDirection(projectId, detail, negative);
      setDetail(value.detail);
      setNegative(value.negative);
      setStored(value);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="section-card compact-card" aria-label="Project direction">
      <p className="field-hint">
        项目功能：应用于当前项目的每个镜头的视频提示词和参考图提示词。输入简单描述，生成细节，满意后保存。
      </p>
      {error ? <div className="banner error">{error}</div> : null}
      {!projectId ? (
        <p className="muted tiny">请先选择一个项目。</p>
      ) : null}

      <label className="field">
        <span>简单描述</span>
        <textarea
          rows={2}
          value={brief}
          disabled={!projectId}
          placeholder="用一句话描述你想要的整体画面、角色或场景。"
          onChange={(e) => setBrief(e.target.value)}
        />
      </label>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <button
          type="button"
          className="btn secondary sm"
          disabled={generating || !projectId || !brief.trim()}
          onClick={() => void generate()}
        >
          {generating ? "生成中…" : "生成细节"}
        </button>
        <span className="muted tiny">
          生成会调用 Director LLM，把笼统描述补成可执行的细节（结构、材质、颜色、环境、光线、禁止项）。
        </span>
      </div>

      <label className="field">
        <span>项目细节</span>
        <textarea
          rows={6}
          value={detail}
          disabled={loading || !projectId}
          placeholder="生成后的细节会出现在这里，可以继续手动修改。"
          onChange={(e) => {
            setDetail(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <label className="field">
        <span>项目禁止项（negative，参考图/图片生成用）</span>
        <textarea
          rows={2}
          value={negative}
          disabled={loading || !projectId}
          placeholder="例如：glass windshield, glass side window, enclosed cabin, steering wheel"
          onChange={(e) => {
            setNegative(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <button
          type="button"
          className="btn primary sm"
          disabled={saving || loading || !dirty || !detail.trim() || !projectId}
          onClick={() => void save()}
        >
          {saving ? "保存中…" : "保存项目细节"}
        </button>
        {saved && !dirty ? <span className="muted tiny">已保存</span> : null}
      </div>
    </section>
  );
}
