"use client";
import { useState, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import { useUser } from "@/lib/user-context";
import * as diff from "diff";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

function pathLookup(obj: unknown, path: string): unknown {
  const parts = path
    .replace(/\[(\d+)\]/g, ".$1")
    .split(".")
    .filter(Boolean);
  let cur = obj;
  for (const p of parts) {
    if (cur == null || typeof cur !== "object") throw new Error(`Cannot read "${p}" — parent is not an object.`);
    cur = (cur as Record<string, unknown>)[p];
  }
  return cur;
}

export default function ProfilePage() {
  const { activeUser } = useUser();
  const uid = activeUser?.id ?? "";

  const [editorText, setEditorText] = useState("{}");
  const [savedText, setSavedText] = useState("{}");
  const [msg, setMsg] = useState<{ type: "ok" | "err" | "info"; text: string } | null>(null);
  const [confirmSave, setConfirmSave] = useState(false);
  const [pathQuery, setPathQuery] = useState("");
  const [pathResult, setPathResult] = useState<string | null>(null);
  const [pathError, setPathError] = useState("");
  const [showDiff, setShowDiff] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadProfile = async () => {
    if (!uid) return;
    try {
      const { truth_json } = await api.getProfile(uid);
      const text = JSON.stringify(truth_json, null, 2);
      setEditorText(text);
      setSavedText(text);
      setMsg(null);
    } catch (e: unknown) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : String(e) });
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadProfile(); }, [uid]);

  let parsed: unknown = null;
  let parseError = "";
  try { parsed = JSON.parse(editorText); } catch (e: unknown) { parseError = e instanceof Error ? e.message : String(e); }
  const isDict = typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
  const isDirty = editorText !== savedText;

  const format = () => {
    try { setEditorText(JSON.stringify(JSON.parse(editorText), null, 2)); } catch {}
  };
  const minify = () => {
    try { setEditorText(JSON.stringify(JSON.parse(editorText))); } catch {}
  };

  const loadSample = async () => {
    const { truth_json } = await api.getSampleProfile();
    setEditorText(JSON.stringify(truth_json, null, 2));
  };

  const validate = async () => {
    if (!uid) return;
    try {
      const result = await api.validateProfile(uid, parsed as Record<string, unknown>);
      if (!result.syntax_ok || !result.is_dict) {
        setMsg({ type: "err", text: result.error ?? "Invalid JSON object." });
      } else if (result.warnings.length) {
        setMsg({ type: "info", text: `Warnings:\n${result.warnings.join("\n")}` });
      } else {
        setMsg({ type: "ok", text: "Validation passed ✓" });
      }
    } catch (e: unknown) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : String(e) });
    }
  };

  const saveProfile = async () => {
    if (!uid || !isDict) return;
    setSaving(true);
    try {
      await api.saveProfile(uid, parsed as Record<string, unknown>);
      setSavedText(editorText);
      setConfirmSave(false);
      setMsg({ type: "ok", text: "Profile saved." });
    } catch (e: unknown) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  };

  const inspectPath = () => {
    setPathError(""); setPathResult(null);
    if (!isDict || !pathQuery.trim()) return;
    try {
      const result = pathLookup(parsed, pathQuery.trim());
      setPathResult(JSON.stringify(result, null, 2));
    } catch (e: unknown) {
      setPathError(e instanceof Error ? e.message : String(e));
    }
  };

  // Stats
  const topKeys = isDict ? Object.keys(parsed as object).length : 0;
  const projectsCount = isDict && Array.isArray((parsed as Record<string, unknown>).projects)
    ? ((parsed as Record<string, unknown>).projects as unknown[]).length : 0;
  const expCount = isDict && Array.isArray((parsed as Record<string, unknown>).experience)
    ? ((parsed as Record<string, unknown>).experience as unknown[]).length : 0;

  // Diff
  const diffLines = isDirty ? diff.createPatch("truth.json", savedText, editorText, "saved", "editor").split("\n") : [];

  const msgClass = msg?.type === "ok" ? "text-green-400" : msg?.type === "err" ? "text-red-400" : "text-yellow-400";

  if (!uid) return <p className="text-neutral-500 text-sm">Select a profile first.</p>;

  return (
    <div className="grid grid-cols-[1fr_240px] gap-3 h-full">
      {/* ── Editor ── */}
      <div className="flex flex-col gap-2 min-h-0">
        {/* Toolbar */}
        <div className="flex gap-1.5 flex-wrap">
          {([
            ["Reload from DB", loadProfile],
            ["Load Sample", loadSample],
            ["Format", format],
            ["Minify", minify],
            ["Validate", validate],
          ] as [string, () => void][]).map(([label, fn]) => (
            <button key={label} onClick={fn}
              className="text-xs px-2 py-1 bg-neutral-800 border border-neutral-700 rounded text-neutral-300 hover:bg-neutral-700">
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1 min-h-0 border border-neutral-800 rounded overflow-hidden">
          <MonacoEditor
            height="100%"
            defaultLanguage="json"
            theme="vs-dark"
            value={editorText}
            onChange={(v) => { setEditorText(v ?? ""); setConfirmSave(false); }}
            options={{ fontSize: 13, minimap: { enabled: false }, tabSize: 2, wordWrap: "on" }}
          />
        </div>

        {/* Diff */}
        <div>
          <button
            className="text-xs text-neutral-500 hover:text-neutral-300 mb-1"
            onClick={() => setShowDiff((s) => !s)}
          >
            {showDiff ? "Hide" : "Show"} diff ({isDirty ? `${diffLines.length} lines changed` : "no changes"})
          </button>
          {showDiff && isDirty && (
            <pre className="text-xs bg-neutral-950 border border-neutral-800 rounded p-2 max-h-40 overflow-auto whitespace-pre-wrap">
              {diffLines.map((line, i) => (
                <span key={i} className={line.startsWith("+") ? "text-green-400" : line.startsWith("-") ? "text-red-400" : "text-neutral-600"}>
                  {line}{"\n"}
                </span>
              ))}
            </pre>
          )}
        </div>
      </div>

      {/* ── Side panel ── */}
      <div className="flex flex-col gap-3 min-h-0 overflow-auto">
        {/* Quick status */}
        <section className="border border-neutral-800 rounded p-2">
          <p className="text-xs font-semibold text-neutral-400 mb-1">Status</p>
          <div className="grid grid-cols-2 gap-1 text-xs">
            <div className="bg-neutral-900 rounded px-2 py-1">
              <p className="text-neutral-600">Syntax</p>
              <p className={parseError ? "text-red-400" : "text-green-400"}>{parseError ? "Error" : "OK"}</p>
            </div>
            <div className="bg-neutral-900 rounded px-2 py-1">
              <p className="text-neutral-600">Dirty</p>
              <p className={isDirty ? "text-yellow-400" : "text-neutral-400"}>{isDirty ? "Yes" : "No"}</p>
            </div>
            <div className="bg-neutral-900 rounded px-2 py-1">
              <p className="text-neutral-600">Keys</p>
              <p className="text-neutral-200">{topKeys}</p>
            </div>
            <div className="bg-neutral-900 rounded px-2 py-1">
              <p className="text-neutral-600">Projects</p>
              <p className="text-neutral-200">{projectsCount}</p>
            </div>
            <div className="bg-neutral-900 rounded px-2 py-1 col-span-2">
              <p className="text-neutral-600">Experience entries</p>
              <p className="text-neutral-200">{expCount}</p>
            </div>
          </div>
          {parseError && <p className="text-xs text-red-400 mt-1 break-all">{parseError}</p>}
        </section>

        {/* Path inspector */}
        <section className="border border-neutral-800 rounded p-2">
          <p className="text-xs font-semibold text-neutral-400 mb-1">Path Inspector</p>
          <input
            className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-xs text-neutral-100 mb-1"
            placeholder="e.g. personal_information.email"
            value={pathQuery}
            onChange={(e) => setPathQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && inspectPath()}
          />
          <button
            className="text-xs px-2 py-1 bg-neutral-800 border border-neutral-700 rounded text-neutral-300 hover:bg-neutral-700 w-full"
            onClick={inspectPath}
          >
            Inspect
          </button>
          {pathError && <p className="text-xs text-red-400 mt-1">{pathError}</p>}
          {pathResult != null && (
            <pre className="text-xs bg-neutral-950 rounded p-1 mt-1 max-h-32 overflow-auto text-neutral-300 whitespace-pre-wrap">{pathResult}</pre>
          )}
        </section>

        {/* Save */}
        <section className="border border-neutral-800 rounded p-2 space-y-1.5">
          <p className="text-xs font-semibold text-neutral-400">Save</p>
          {msg && <p className={`text-xs whitespace-pre-wrap ${msgClass}`}>{msg.text}</p>}
          {isDirty && (
            <label className="flex items-center gap-1.5 text-xs text-neutral-500 cursor-pointer">
              <input type="checkbox" checked={confirmSave} onChange={(e) => setConfirmSave(e.target.checked)} />
              I reviewed the changes
            </label>
          )}
          <button
            className="w-full text-xs px-2 py-1.5 bg-blue-800 text-white rounded hover:bg-blue-700 disabled:opacity-40"
            onClick={saveProfile}
            disabled={!!parseError || !isDict || (isDirty && !confirmSave) || saving}
          >
            {saving ? "Saving…" : "Save Profile"}
          </button>
        </section>
      </div>
    </div>
  );
}
