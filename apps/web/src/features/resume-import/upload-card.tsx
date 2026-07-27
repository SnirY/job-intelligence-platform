"use client";

import { FileUp, Loader2 } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldHint } from "@/components/ui/label";
import { useUploadResume } from "@/features/resume-import/api";
import { ApiError } from "@/lib/api";

/**
 * Formats that work end to end.
 *
 * Upload validation, text extraction, and the parser all handle both. Listing
 * a third here would promise something the pipeline cannot deliver, and the
 * user would only find out after waiting for a job that was always going to
 * fail.
 */
const ACCEPTED = ".pdf,.docx";
const MAX_BYTES = 10 * 1024 * 1024;

interface UploadCardProps {
  onUploaded: (documentId: string) => void;
}

export function UploadCard({ onUploaded }: UploadCardProps) {
  const upload = useUploadResume();
  const inputRef = useRef<HTMLInputElement>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  function handleFile(file: File | undefined) {
    setLocalError(null);
    if (!file) return;

    // Checked here as well as on the server so a 10 MB file is not sent across
    // the network to be refused. The server check is the one that counts.
    if (file.size > MAX_BYTES) {
      setLocalError("That file is larger than the 10 MB limit.");
      return;
    }

    upload.mutate(file, {
      onSuccess: (accepted) => {
        setLocalError(null);
        onUploaded(accepted.source_document_id);
      },
    });
  }

  const message = localError ?? uploadErrorMessage(upload.error);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Import a resume</CardTitle>
        <CardDescription>
          Upload a PDF or Word document. We read it, propose what we found, and change nothing on
          your profile until you say so.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          className="sr-only"
          aria-label="Resume file"
          onChange={(event) => handleFile(event.target.files?.[0])}
        />

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            disabled={upload.isPending}
            onClick={() => inputRef.current?.click()}
          >
            {upload.isPending ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : (
              <FileUp aria-hidden className="size-4" />
            )}
            {upload.isPending ? "Uploading…" : "Choose a file"}
          </Button>
          <FieldHint>PDF or DOCX, up to 10 MB.</FieldHint>
        </div>

        <p aria-live="polite" className="text-sm text-destructive">
          {message}
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * The message to show for a failed upload.
 *
 * A rejected file gets the API's own explanation — it names the actual problem
 * ("the file contents do not match a PDF") in a way a generic message cannot.
 */
function uploadErrorMessage(error: Error | null): string {
  if (!error) return "";
  if (error instanceof ApiError) {
    if (error.status === 422) return error.message;
    if (error.isUnauthenticated) return "Your session was not accepted. Sign out and back in.";
    if (error.status === 503) return "File storage is unavailable right now. Try again shortly.";
  }
  return "Could not upload that file. Check your connection and try again.";
}
