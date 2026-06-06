"use client";

import { KeyRound, Loader2 } from "lucide-react";
import { useActionState } from "react";

import { connectAction, type ConnectState } from "@/app/connect/actions";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const INITIAL_STATE: ConnectState = { error: null };

export const ConnectForm = () => {
  const [state, formAction, isPending] = useActionState(connectAction, INITIAL_STATE);

  return (
    <form action={formAction} className="space-y-4" noValidate>
      <div className="space-y-2">
        <Label htmlFor="apiKey">Organization API key</Label>
        <Input
          id="apiKey"
          name="apiKey"
          type="password"
          required
          autoComplete="off"
          spellCheck={false}
          placeholder="cgk_local_xxxxxxxx.…"
          aria-invalid={Boolean(state.error)}
          aria-describedby={state.error ? "connect-error" : undefined}
          className="h-11 bg-card"
        />
      </div>

      {state.error ? (
        <Alert variant="destructive" id="connect-error" className="bg-peach-900/60">
          <AlertDescription>{state.error}</AlertDescription>
        </Alert>
      ) : null}

      <Button type="submit" disabled={isPending} className="h-11 w-full gap-2">
        {isPending ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Verifying key…
          </>
        ) : (
          <>
            <KeyRound className="h-4 w-4" aria-hidden />
            Connect
          </>
        )}
      </Button>
    </form>
  );
};
