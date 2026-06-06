"use client";

import { OctagonAlert, RotateCcw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}

/** One error surface everywhere: problem-detail aware, always retryable. */
export const ErrorState = ({ error, onRetry, title = "Something went wrong" }: ErrorStateProps) => {
  const detail =
    error instanceof ApiError
      ? (error.problem.detail ?? error.problem.title)
      : "An unexpected error occurred while talking to the API.";
  const requestId = error instanceof ApiError ? error.problem.request_id : null;

  return (
    <Alert variant="destructive" className="bg-peach-900/60">
      <OctagonAlert className="h-4 w-4" aria-hidden />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="space-y-3">
        <p>{detail}</p>
        {requestId && requestId !== "-" ? (
          <p className="text-xs opacity-70">Request ID: {requestId}</p>
        ) : null}
        {onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry} className="gap-1.5">
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            Try again
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
};
