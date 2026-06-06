"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiFetch, pageQuery } from "@/lib/api/client";
import type {
  AuditCreate,
  AuditRunOut,
  ChunkOut,
  DocumentDetail,
  DocumentSummary,
  FindingOut,
  OrgOut,
  Page,
  PolicyOut,
  PolicySummary,
  PolicyVersionOut,
  RegulatorySearchRequest,
  RegulatorySearchResponse,
} from "@/lib/api/types";
import { AUDIT_POLL_INTERVAL_MS, DEFAULT_PAGE_SIZE, RUN_STATUS_META } from "@/lib/constants";

export const queryKeys = {
  me: ["me"] as const,
  audits: (offset: number) => ["audits", offset] as const,
  audit: (id: number) => ["audit", id] as const,
  findings: (runId: number, offset: number) => ["findings", runId, offset] as const,
  policies: (offset: number) => ["policies", offset] as const,
  policy: (id: number) => ["policy", id] as const,
  policyVersions: (id: number) => ["policy-versions", id] as const,
  documents: (offset: number, filters: string) => ["documents", offset, filters] as const,
  document: (id: number) => ["document", id] as const,
  chunks: (documentId: number) => ["chunks", documentId] as const,
};

export const useMe = (): UseQueryResult<OrgOut> =>
  useQuery({ queryKey: queryKeys.me, queryFn: () => apiFetch<OrgOut>("me") });

export const useAudits = (offset = 0): UseQueryResult<Page<AuditRunOut>> =>
  useQuery({
    queryKey: queryKeys.audits(offset),
    queryFn: () =>
      apiFetch<Page<AuditRunOut>>(`audits${pageQuery(DEFAULT_PAGE_SIZE, offset)}`),
  });

/** Polls while the run is queued/running — the 202 + poll contract. */
export const useAudit = (id: number): UseQueryResult<AuditRunOut> =>
  useQuery({
    queryKey: queryKeys.audit(id),
    queryFn: () => apiFetch<AuditRunOut>(`audits/${id}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || RUN_STATUS_META[status].terminal) return false;
      return AUDIT_POLL_INTERVAL_MS;
    },
  });

export const useFindings = (
  runId: number,
  enabled: boolean,
  offset = 0,
): UseQueryResult<Page<FindingOut>> =>
  useQuery({
    queryKey: queryKeys.findings(runId, offset),
    queryFn: () =>
      apiFetch<Page<FindingOut>>(
        `audits/${runId}/findings${pageQuery(100, offset)}`,
      ),
    enabled,
  });

export const useCreateAudit = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AuditCreate) =>
      apiFetch<AuditRunOut>("audits", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["audits"] }),
  });
};

export const usePolicies = (offset = 0): UseQueryResult<Page<PolicySummary>> =>
  useQuery({
    queryKey: queryKeys.policies(offset),
    queryFn: () =>
      apiFetch<Page<PolicySummary>>(`policies${pageQuery(DEFAULT_PAGE_SIZE, offset)}`),
  });

export const usePolicy = (id: number): UseQueryResult<PolicyOut> =>
  useQuery({
    queryKey: queryKeys.policy(id),
    queryFn: () => apiFetch<PolicyOut>(`policies/${id}`),
  });

export const usePolicyVersions = (id: number): UseQueryResult<Page<PolicyVersionOut>> =>
  useQuery({
    queryKey: queryKeys.policyVersions(id),
    queryFn: () => apiFetch<Page<PolicyVersionOut>>(`policies/${id}/versions?limit=50`),
  });

export const useCreatePolicy = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; body: string }) =>
      apiFetch<PolicyOut>("policies", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policies"] }),
  });
};

export const useUpdatePolicy = (id: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { title?: string; body?: string }) =>
      apiFetch<PolicyOut>(`policies/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.policy(id) });
      queryClient.invalidateQueries({ queryKey: ["policies"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.policyVersions(id) });
    },
  });
};

export const useDeletePolicy = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`policies/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policies"] }),
  });
};

export interface DocumentFilters {
  jurisdiction?: string;
  issuing_body?: string;
  document_type?: string;
}

export const useDocuments = (
  offset = 0,
  filters: DocumentFilters = {},
): UseQueryResult<Page<DocumentSummary>> => {
  const params = new URLSearchParams({
    limit: String(DEFAULT_PAGE_SIZE),
    offset: String(offset),
  });
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  return useQuery({
    queryKey: queryKeys.documents(offset, params.toString()),
    queryFn: () =>
      apiFetch<Page<DocumentSummary>>(`regulatory/documents?${params.toString()}`),
  });
};

export const useDocument = (id: number): UseQueryResult<DocumentDetail> =>
  useQuery({
    queryKey: queryKeys.document(id),
    queryFn: () => apiFetch<DocumentDetail>(`regulatory/documents/${id}`),
  });

export const useChunks = (documentId: number): UseQueryResult<Page<ChunkOut>> =>
  useQuery({
    queryKey: queryKeys.chunks(documentId),
    queryFn: () =>
      apiFetch<Page<ChunkOut>>(`regulatory/documents/${documentId}/chunks?limit=100`),
  });

export const useRegulatorySearch = () =>
  useMutation({
    mutationFn: (body: RegulatorySearchRequest) =>
      apiFetch<RegulatorySearchResponse>("regulatory/search", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  });
