import { useEffect, useState } from "react";
import {
  expandGlobalPrompt,
  getGlobalDirection,
  saveGlobalDirection,
} from "../../features/director/api";

/**
 * App-wide global direction. Write a rough note, ask the Director LLM to expand it
 * into detailed, checkable rules, then save. The backend appends the saved text to
 * every shot's H3 prompt, every Layout/reference-frame prompt, and every asset
 * pipeline across all projects. The negative list is applied to image pipelines
 * that support a negative prompt.
 */
export function GlobalPromptPanel() {
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
    let cancelled = false;
    setLoading(true);
    getGlobalDirection()
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
  }, []);

  const dirty =
    detail.trim() !== stored.detail.trim() ||
    negative.trim() !== stored.negative.trim();

  const generate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const expanded = await expandGlobalPrompt(brief, detail);
      setDetail(expanded);
      setSaved(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const value = await saveGlobalDirection(detail, negative);
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
    <section className="section-card compact-card" aria-label="Global direction">
      <p className="field-hint">
        通用功能：应用于所有项目、每个镜头的视频提示词和参考图提示词。输入简单描述，生成细节，满意后保存。
      </p>
      {error ? <div className="banner error">{error}</div> : null}

      <label className="field">
        <span>简单描述</span>
        <textarea
          rows={2}
          value={brief}
          placeholder="用一句话描述你想要的整体画面、角色或场景。"
          onChange={(e) => setBrief(e.target.value)}
        />
      </label>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <button
          type="button"
          className="btn secondary sm"
          disabled={generating || !brief.trim()}
          onClick={() => void generate()}
        >
          {generating ? "生成中…" : "生成细节"}
        </button>
        <span className="muted tiny">
          生成会调用 Director LLM，把笼统描述补成可执行的细节（结构、材质、颜色、环境、光线、禁止项）。
        </span>
      </div>

      <label className="field">
        <span>全局细节</span>
        <textarea
          rows={6}
          value={detail}
          disabled={loading}
          placeholder="生成后的细节会出现在这里，可以继续手动修改。"
          onChange={(e) => {
            setDetail(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <label className="field">
        <span>全局禁止项（negative，参考图/图片生成用）</span>
        <textarea
          rows={2}
          value={negative}
          disabled={loading}
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
          disabled={saving || loading || !dirty || !detail.trim()}
          onClick={() => void save()}
        >
          {saving ? "保存中…" : "保存全局细节"}
        </button>
        {saved && !dirty ? <span className="muted tiny">已保存</span> : null}
      </div>
    </section>
  );
}
