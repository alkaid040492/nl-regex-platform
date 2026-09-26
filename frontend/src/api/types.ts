export type TransformType = "REPLACE" | "EXTRACT" | "NORMALIZE";
export type JobStatus = "QUEUED" | "RUNNING" | "SUCCESS" | "FAILED" | "CANCELLED";
export type JobStage = "PENDING" | "LOAD" | "LLM" | "VALIDATE" | "TRANSFORM" | "WRITE" | "DONE";

export interface Connection {
  connection_id: string;
  bucket: string;
  region: string;
  access_key_hint: string;
  expires_at: string;
}

export interface S3File {
  key: string;
  size: number;
  last_modified: string;
  kind: "csv" | "excel";
}

export interface ColumnInfo {
  name: string;
  dtype: "string" | "number";
}

export interface SchemaPreview {
  key: string;
  columns: ColumnInfo[];
  sample_rows: Record<string, string>[];
  sampled_rows: number;
}

export interface CreateJobRequest {
  connection_id: string;
  file_key: string;
  transform_type: TransformType;
  prompt: string;
  replacement?: string;
  columns: string[];
  new_column_name?: string;
}

export interface Job {
  id: string;
  status: JobStatus;
  stage: JobStage;
  progress: number;
  transform_type: TransformType;
  prompt: string;
  replacement: string;
  columns: string[];
  new_column_name: string;
  file_key: string;
  bucket: string;
  regex_pattern: string;
  replacement_template: string;
  llm_explanation: string;
  llm_cache_hit: boolean;
  row_count: number | null;
  matched_rows: number | null;
  result_columns: string[];
  error_code: string;
  error_message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
}

export interface JobResultPage {
  columns: string[];
  rows: Record<string, string | number | boolean | null>[];
  page: number;
  page_size: number;
  total_rows: number;
  total_pages: number;
}
