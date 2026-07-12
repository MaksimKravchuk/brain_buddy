import { useState } from "react";
import { Mic, Send, ListChecks } from "lucide-react";
import { Link } from "react-router-dom";

import { useCreateCaptureSession, useListCaptures } from "../api/vnext-hooks";
import { Button } from "../components/ui/Button";
import { useUiStore } from "../stores/uiStore";
import { getErrorMessage } from "../utils/error";

export default function CapturePage(): JSX.Element {
  const [text, setText] = useState("");
  const pushToast = useUiStore((state) => state.pushToast);

  const createSession = useCreateCaptureSession();
  const { data: captures, isLoading } = useListCaptures();

  const handleSubmit = () => {
    if (!text.trim()) return;
    createSession.mutate(
      { text },
      {
        onSuccess: (data) => {
          pushToast({
            title: "Captured",
            description: `${data.captures.length} item(s) created`,
            variant: "success",
            duration: 4000
          });
          setText("");
        },
        onError: (error) => {
          pushToast({
            title: "Capture failed",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

  return (
    <div className="min-h-screen bg-surface-base text-slate-900">
      <header className="border-b border-slate-200 bg-surface-raised px-6 py-4">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Brain Dump</h1>
            <p className="mt-1 text-sm text-slate-500">
              Capture your thoughts. Review them later.
            </p>
          </div>
          <Link to="/review">
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<ListChecks className="h-4 w-4" />}
            >
              Weekly Review
            </Button>
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-6">
        <div className="mb-6 rounded-xl border border-slate-200 bg-surface-raised p-4 shadow-soft">
          <textarea
            className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
            placeholder="Dump your thoughts here... one per line"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={5}
          />
          <div className="mt-3 flex justify-end">
            <Button
              variant="primary"
              size="md"
              leftIcon={<Send className="h-4 w-4" />}
              onClick={handleSubmit}
              isLoading={createSession.isPending}
              disabled={!text.trim()}
            >
              Capture
            </Button>
          </div>
        </div>

        <div>
          <h2 className="mb-3 text-sm font-medium text-slate-700">
            Recent Captures
          </h2>
          {isLoading ? (
            <p className="text-sm text-slate-400">Loading...</p>
          ) : captures && captures.length > 0 ? (
            <div className="space-y-2">
              {captures.slice(0, 20).map((capture) => (
                <div
                  key={capture.id}
                  className="flex items-center gap-3 rounded-lg border border-slate-200 bg-surface-raised px-4 py-2 text-sm"
                >
                  <span className="flex h-6 w-6 items-center justify-center rounded text-xs text-slate-400">
                    <Mic className="h-3 w-3" />
                  </span>
                  <span className="flex-1 truncate text-slate-700">
                    {capture.current_text}
                  </span>
                  <span className="text-xs text-slate-400">
                    {capture.review_state}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-400">
              No captures yet. Start by dumping your thoughts above.
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
