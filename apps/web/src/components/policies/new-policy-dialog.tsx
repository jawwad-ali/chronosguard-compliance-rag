"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { FilePlus2, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { useCreatePolicy } from "@/lib/api/queries";
import { MAX_POLICY_BODY_CHARS } from "@/lib/constants";

const formSchema = z.object({
  title: z.string().min(1, "Give the policy a title.").max(300),
  body: z.string().min(1, "Policy text is required.").max(MAX_POLICY_BODY_CHARS),
});

type FormValues = z.infer<typeof formSchema>;

export const NewPolicyDialog = () => {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const createPolicy = useCreatePolicy();

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { title: "", body: "" },
  });

  const onSubmit = (values: FormValues): void => {
    createPolicy.mutate(values, {
      onSuccess: (policy) => {
        toast.success("Policy stored", { description: `${policy.title} · v1` });
        setOpen(false);
        form.reset();
        router.push(`/policies/${policy.id}`);
      },
      onError: (error) =>
        toast.error("Could not store the policy", {
          description: error instanceof ApiError ? error.message : "Unexpected error.",
        }),
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="gap-2">
          <FilePlus2 className="h-4 w-4" aria-hidden />
          New policy
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Store a policy</DialogTitle>
          <DialogDescription>
            Version 1 is created immediately; later edits append immutable versions.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="title"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Title</FormLabel>
                  <FormControl>
                    <Input {...field} placeholder="Funds Settlement Policy" />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="body"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Policy text</FormLabel>
                  <FormControl>
                    <Textarea {...field} rows={8} className="resize-y bg-card text-sm" />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <Button type="submit" disabled={createPolicy.isPending} className="h-11 w-full gap-2">
              {createPolicy.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Storing…
                </>
              ) : (
                <>
                  <FilePlus2 className="h-4 w-4" aria-hidden /> Store policy
                </>
              )}
            </Button>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
};
