"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { format } from "date-fns";
import { CalendarDays, Loader2, Stamp } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
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
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { useCreateAudit, useMe, usePolicies } from "@/lib/api/queries";
import { MAX_POLICY_BODY_CHARS } from "@/lib/constants";
import { cn } from "@/lib/utils";

const formSchema = z
  .object({
    source: z.enum(["stored", "pasted"]),
    policyId: z.string().optional(),
    policyText: z.string().max(MAX_POLICY_BODY_CHARS).optional(),
    jurisdiction: z
      .string()
      .min(2, "Jurisdiction code required")
      .max(16)
      .transform((value) => value.toUpperCase()),
    asOfDate: z.date(),
  })
  .superRefine((value, ctx) => {
    if (value.source === "stored" && !value.policyId) {
      ctx.addIssue({
        code: "custom",
        path: ["policyId"],
        message: "Pick a stored policy.",
      });
    }
    if (value.source === "pasted" && !value.policyText?.trim()) {
      ctx.addIssue({
        code: "custom",
        path: ["policyText"],
        message: "Paste the policy text to audit.",
      });
    }
  });

type FormValues = z.infer<typeof formSchema>;

export const NewAuditDialog = () => {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const me = useMe();
  const policies = usePolicies(0);
  const createAudit = useCreateAudit();

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      source: "stored",
      jurisdiction: me.data?.home_jurisdiction ?? "PK",
      asOfDate: new Date(),
    },
  });

  const source = useWatch({ control: form.control, name: "source" });

  const onSubmit = (values: FormValues): void => {
    createAudit.mutate(
      {
        jurisdiction: values.jurisdiction,
        as_of_date: format(values.asOfDate, "yyyy-MM-dd"),
        ...(values.source === "stored"
          ? { policy_id: Number(values.policyId) }
          : { policy_text: values.policyText }),
      },
      {
        onSuccess: (run) => {
          toast.success(`Audit №${run.id} queued`, {
            description: `Anchored as of ${format(values.asOfDate, "d MMM yyyy")}.`,
          });
          setOpen(false);
          form.reset();
          router.push(`/audits/${run.id}`);
        },
        onError: (error) => {
          toast.error("Could not start the audit", {
            description:
              error instanceof ApiError ? error.message : "Unexpected error.",
          });
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="gap-2">
          <Stamp className="h-4 w-4" aria-hidden />
          New audit
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Open a new audit</DialogTitle>
          <DialogDescription>
            The verdict is anchored to the as-of date — the law in force on that
            day, not today.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-5">
            <FormField
              control={form.control}
              name="source"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Policy source</FormLabel>
                  <FormControl>
                    <Tabs value={field.value} onValueChange={field.onChange}>
                      <TabsList className="grid w-full grid-cols-2">
                        <TabsTrigger value="stored">Stored policy</TabsTrigger>
                        <TabsTrigger value="pasted">Paste text</TabsTrigger>
                      </TabsList>
                    </Tabs>
                  </FormControl>
                </FormItem>
              )}
            />

            {source === "stored" ? (
              <FormField
                control={form.control}
                name="policyId"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Policy</FormLabel>
                    <Select value={field.value ?? ""} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue
                            placeholder={
                              policies.isPending
                                ? "Loading policies…"
                                : policies.data?.items.length
                                  ? "Choose a policy"
                                  : "No stored policies yet"
                            }
                          />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {policies.data?.items.map((policy) => (
                          <SelectItem key={policy.id} value={String(policy.id)}>
                            {policy.title} · v{policy.current_version_no}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      The current version is snapshotted into the run.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              <FormField
                control={form.control}
                name="policyText"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Policy text</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        value={field.value ?? ""}
                        rows={7}
                        placeholder={
                          "PocketPay will hold user funds for up to 7 business days before clearing.\n\nCustomer KYC records are retained for 5 years after account closure."
                        }
                        className="resize-y bg-card font-sans text-sm"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="jurisdiction"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Jurisdiction</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder="PK" className="uppercase" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="asOfDate"
                render={({ field }) => (
                  <FormItem className="flex flex-col">
                    <FormLabel>As-of date</FormLabel>
                    <Popover>
                      <PopoverTrigger asChild>
                        <FormControl>
                          <Button
                            variant="outline"
                            className={cn(
                              "justify-start gap-2 text-left font-normal",
                              !field.value && "text-muted-foreground",
                            )}
                          >
                            <CalendarDays className="h-4 w-4" aria-hidden />
                            {field.value ? format(field.value, "d MMM yyyy") : "Pick a date"}
                          </Button>
                        </FormControl>
                      </PopoverTrigger>
                      <PopoverContent className="w-auto p-0" align="start">
                        <Calendar
                          mode="single"
                          selected={field.value}
                          onSelect={(date) => date && field.onChange(date)}
                          autoFocus
                        />
                      </PopoverContent>
                    </Popover>
                    <FormDescription>Point-in-time audits welcome.</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <Button
              type="submit"
              disabled={createAudit.isPending}
              className="h-11 w-full gap-2"
            >
              {createAudit.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  Queueing audit…
                </>
              ) : (
                <>
                  <Stamp className="h-4 w-4" aria-hidden />
                  Run audit
                </>
              )}
            </Button>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
};
