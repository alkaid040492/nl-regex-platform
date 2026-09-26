import { apiFetch } from "./client";
import type { Connection, CreateJobRequest, Job, JobResultPage, S3File, SchemaPreview } from "./types";

// ---- connections -----------------------------------------------------------
export interface ConnectRequest {
  access_key: string;
  secret_key: string;
  bucket: string;
  region?: string;
}

export const createConnection = (body: ConnectRequest) =>
  apiFetch<Connection>("/connections/", { method: "POST", body: JSON.stringify(body) });

export const deleteConnection = (id: string) => apiFetch<void>(`/connections/${id}/`, { method: "DELETE" });

export const listFiles = (id: string, prefix = "") =>
  apiFetch<{ bucket: string; files: S3File[] }>(`/connections/${id}/files/?prefix=${encodeURIComponent(prefix)}`);

export const fileSchema = (id: string, key: string) =>
  apiFetch<SchemaPreview>(`/connections/${id}/files/schema/?key=${encodeURIComponent(key)}`);

// ---- jobs ------------------------------------------------------------------
export const createJob = (body: CreateJobRequest) =>
  apiFetch<{ job_id: string }>("/jobs/", { method: "POST", body: JSON.stringify(body) });

export const getJob = (id: string) => apiFetch<Job>(`/jobs/${id}/`);

export const listJobs = () => apiFetch<Job[]>("/jobs/");

export const cancelJob = (id: string) => apiFetch<Job>(`/jobs/${id}/cancel/`, { method: "POST" });

export const getJobResult = (id: string, page: number, pageSize: number, onlyMatched = false) =>
  apiFetch<JobResultPage>(`/jobs/${id}/result/?page=${page}&page_size=${pageSize}&only_matched=${onlyMatched}`);

// ---- misc ------------------------------------------------------------------
export const getHealth = () => apiFetch<{ status: string; db: string; redis: string; worker: string }>("/health/");
