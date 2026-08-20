"use client";

import { useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL;
// Configurable, but this stays simple polling on purpose — no WebSockets.
// At this app's scale, polling is sufficient; the interval is just how
// responsive the UI feels while a job is in flight, not a scalability knob.
const POLL_INTERVAL_MS = Number(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS) || 2000;

type Position = {
  title: string;
  company: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
};

type Education = {
  degree: string;
  institution: string;
  graduation_date: string;
};

type ParsedResume = {
  name: string;
  email: string;
  phone: string;
  location: string;
  positions: Position[];
  education: Education[];
  skills: string[];
};

type ResumeStatus = {
  id: number;
  status: "pending" | "processing" | "done" | "failed";
  parsed_result: ParsedResume | null;
  error: string | null;
};

export default function Home() {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [resume, setResume] = useState<ResumeStatus | null>(null);
  const [pollNotice, setPollNotice] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!resume || resume.status === "done" || resume.status === "failed") {
      return;
    }
    const timer = setInterval(async () => {
      let response: Response;
      try {
        response = await fetch(`${API_URL}/resumes/${resume.id}`);
      } catch {
        // Network error (offline, connection refused, etc.) — transient by
        // nature, so just try again next tick rather than tearing down the
        // poll or showing a broken state.
        setPollNotice("Connection lost, retrying...");
        return;
      }

      if (response.status === 404) {
        // The resume genuinely doesn't exist — not transient, retrying
        // forever won't fix it, so stop polling and say so plainly instead
        // of silently rendering nothing.
        setPollNotice(null);
        setResume((r) => (r ? { ...r, status: "failed", error: "Resume not found" } : r));
        return;
      }

      if (!response.ok) {
        // 5xx or anything else unexpected. Could well be transient, so keep
        // polling — but don't treat the (possibly not ResumeStatus-shaped)
        // body as a valid parsed result just because a response arrived.
        setPollNotice(`Server error (${response.status}), retrying...`);
        return;
      }

      let data: ResumeStatus;
      try {
        data = await response.json();
      } catch {
        setPollNotice("Received an invalid response, retrying...");
        return;
      }
      setPollNotice(null);
      setResume(data);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [resume]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) return;

    setUploading(true);
    setUploadError(null);
    setResume(null);
    setPollNotice(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const response = await fetch(`${API_URL}/resumes`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail ?? "upload failed");
      }
      const data: { id: number; status: ResumeStatus["status"] } = await response.json();
      setResume({ id: data.id, status: data.status, parsed_result: null, error: null });
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col items-center bg-zinc-50 px-6 py-16 dark:bg-black">
      <main className="flex w-full max-w-2xl flex-col gap-8">
        <div>
          <h1 className="text-2xl font-semibold text-black dark:text-zinc-50">Resume Parser</h1>
          <p className="mt-2 text-zinc-600 dark:text-zinc-400">
            Upload your resume to see exactly how our parser reads it.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex items-center gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx"
            className="sr-only"
            onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="rounded-full border border-zinc-300 px-4 py-2 text-sm text-zinc-700 dark:border-zinc-700 dark:text-zinc-300"
          >
            Choose file
          </button>
          <span className="flex-1 text-sm text-zinc-600 dark:text-zinc-400">
            {selectedFile ? selectedFile.name : "No file chosen"}
          </span>
          <button
            type="submit"
            disabled={uploading}
            className="rounded-full bg-black px-5 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-black"
          >
            {uploading ? "Uploading..." : "Upload"}
          </button>
        </form>

        {uploadError && <p className="text-sm text-red-600">{uploadError}</p>}

        {resume && <ResumeStatusView resume={resume} pollNotice={pollNotice} />}
      </main>
    </div>
  );
}

function ResumeStatusView({
  resume,
  pollNotice,
}: {
  resume: ResumeStatus;
  pollNotice: string | null;
}) {
  if (resume.status === "pending" || resume.status === "processing") {
    return (
      <div className="flex flex-col gap-1">
        <p className="text-sm text-zinc-600 dark:text-zinc-400">Parsing your resume...</p>
        {pollNotice && <p className="text-xs text-amber-600">{pollNotice}</p>}
      </div>
    );
  }

  if (resume.status === "failed") {
    return <p className="text-sm text-red-600">Parsing failed: {resume.error}</p>;
  }

  const parsed = resume.parsed_result;
  if (!parsed) return null;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-zinc-200 p-6 dark:border-zinc-800">
      <div>
        <p className="text-lg font-medium text-black dark:text-zinc-50">{parsed.name}</p>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {[parsed.email, parsed.phone, parsed.location].filter(Boolean).join(" · ")}
        </p>
      </div>

      {parsed.skills.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {parsed.skills.map((skill) => (
            <span
              key={skill}
              className="rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
            >
              {skill}
            </span>
          ))}
        </div>
      )}

      {parsed.positions.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-black dark:text-zinc-50">Experience</h2>
          <ul className="mt-2 flex flex-col gap-2">
            {parsed.positions.map((position, i) => (
              <li key={i} className="text-sm text-zinc-700 dark:text-zinc-300">
                <span className="font-medium">{position.title}</span> at {position.company}{" "}
                <span className="text-zinc-500">
                  ({position.start_date} –{" "}
                  {position.is_current ? "present" : position.end_date})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {parsed.education.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-black dark:text-zinc-50">Education</h2>
          <ul className="mt-2 flex flex-col gap-2">
            {parsed.education.map((edu, i) => (
              <li key={i} className="text-sm text-zinc-700 dark:text-zinc-300">
                <span className="font-medium">{edu.degree}</span>, {edu.institution}{" "}
                <span className="text-zinc-500">({edu.graduation_date})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
