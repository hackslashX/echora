"use client";

import { LoaderCircle, Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import AudioVisualizer from "./AudioVisualizer";
import styles from "./HumSearchButton.module.css";

type Track = { id: string; title: string; artist?: string; album?: string; duration_seconds: number; source_id?: string; cover_art?: string; similarity?: number; matched_at_seconds?: number };
type IndexStatus = { status: "missing" | "building" | "complete" | "failed"; indexed_tracks: number; error?: string };

export default function HumSearchButton({ onResults, onError }: { onResults: (tracks: Track[]) => void; onError: (message: string) => void }) {
  const [index, setIndex] = useState<IndexStatus>({ status: "missing", indexed_tracks: 0 });
  const [state, setState] = useState<"idle" | "recording" | "searching" | "building">("idle");
  const [activeStream, setActiveStream] = useState<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);

  async function refreshIndex() {
    const response = await fetch("/analysis/library/hum/index");
    if (response.ok) {
      const next: IndexStatus = await response.json();
      setIndex(next);
      if (next.status === "complete") setState(current => current === "building" ? "idle" : current);
    }
  }

  useEffect(() => {
    fetch("/analysis/library/hum/index").then(response => response.ok ? response.json() : null)
      .then(value => { if (value) setIndex(value); }).catch(() => {});
  }, []);
  useEffect(() => {
    if (state !== "building") return;
    const timer = window.setInterval(() => refreshIndex().catch(() => {}), 2500);
    return () => window.clearInterval(timer);
  }, [state]);
  useEffect(() => () => stream.current?.getTracks().forEach(track => track.stop()), []);

  async function build() {
    setState("building"); onError("");
    const response = await fetch("/analysis/library/hum/index?track_limit=50", { method: "POST" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setState("idle"); onError(body.detail || "Could not build the hum index");
    } else setIndex(current => ({ ...current, status: "building" }));
  }

  async function start() {
    if (index.status !== "complete") { await build(); return; }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      setActiveStream(stream.current);
      chunks.current = [];
      const active = new MediaRecorder(stream.current);
      recorder.current = active;
      active.ondataavailable = event => { if (event.data.size) chunks.current.push(event.data); };
      active.onstop = async () => {
        stream.current?.getTracks().forEach(track => track.stop());
        stream.current = null;
        setActiveStream(null);
        setState("searching");
        try {
          const recording = new Blob(chunks.current, { type: active.mimeType });
          const response = await fetch("/analysis/library/hum/search?limit=10", { method: "POST", headers: { "content-type": active.mimeType || "application/octet-stream" }, body: recording });
          const contentType = response.headers.get("content-type") || "";
          const body = contentType.includes("application/json") ? await response.json() : null;
          if (!response.ok) throw new Error(body?.detail || `Hum search failed (${response.status})`);
          onResults(body?.tracks || []);
        } catch (error) { onError(error instanceof Error ? error.message : "Hum search failed"); }
        finally { setState("idle"); }
      };
      active.start(); setState("recording"); onError("");
    } catch {
      stream.current?.getTracks().forEach(track => track.stop());
      stream.current = null;
      setActiveStream(null);
      onError("Microphone access is required for hum search");
    }
  }

  function stop() { recorder.current?.stop(); recorder.current = null; }

  const building = state === "building" || index.status === "building";
  const label = state === "recording" ? "Stop humming" : state === "searching" ? "Matching" : building ? `Indexing ${index.indexed_tracks || 0}/50` : index.status === "complete" ? "Hum to search" : "Build hum index";
  return <button type="button" className={`${styles.button} ${state === "recording" ? styles.recording : ""}`} onClick={state === "recording" ? stop : start} disabled={state === "searching" || building} title={label}>
    {state === "recording" && activeStream ? <AudioVisualizer stream={activeStream} /> : null}
    {state === "recording" ? <Square /> : state === "searching" || building ? <LoaderCircle className={styles.spin} /> : <Mic />}
    <span>{label}</span>
  </button>;
}
