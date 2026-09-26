import { useEffect, useRef } from "react";
import { Alert, Badge, Button, Code, Group, Paper, Progress, Stack, Text, Timeline, Title, Tooltip } from "@mantine/core";
import { IconAlertCircle, IconCheck, IconPlayerStop, IconRefresh, IconRotate, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cancelJob, getJob } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import type { Job, JobStage, JobStatus } from "../../api/types";

interface Props {
  jobId: string;
  onFinished: (ok: boolean) => void;
  onNewJob: () => void;
  onStartOver: () => void;
}

const STAGES: { key: JobStage; label: string; hint: string }[] = [
  { key: "LOAD", label: "Load from S3", hint: "Spark reads the file straight from your bucket" },
  { key: "LLM", label: "Generate regex", hint: "Natural language → pattern (cached in Redis)" },
  { key: "VALIDATE", label: "Validate", hint: "Syntax, ReDoS and JVM compile checks" },
  { key: "TRANSFORM", label: "Transform", hint: "Distributed regexp_replace across partitions" },
  { key: "WRITE", label: "Write result", hint: "Parquet on the results volume" },
];

const STATUS_COLOR: Record<JobStatus, string> = {
  QUEUED: "gray",
  RUNNING: "indigo",
  SUCCESS: "green",
  FAILED: "red",
  CANCELLED: "yellow",
};

const TERMINAL: JobStatus[] = ["SUCCESS", "FAILED", "CANCELLED"];

export function JobProgress({ jobId, onFinished, onNewJob, onStartOver }: Props) {
  const qc = useQueryClient();
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.status) ? false : 1500),
  });

  const cancel = useMutation({
    mutationFn: () => cancelJob(jobId),
    onSuccess: (j) => qc.setQueryData(["job", jobId], j),
  });

  const notified = useRef<string | null>(null);
  useEffect(() => {
    const status = job.data?.status;
    if (status && TERMINAL.includes(status) && notified.current !== jobId + status) {
      notified.current = jobId + status;
      onFinished(status === "SUCCESS");
    }
  }, [job.data?.status, jobId, onFinished]);

  if (job.isLoading) {
    return (
      <Paper withBorder p="lg">
        <Text>Loading job…</Text>
      </Paper>
    );
  }
  if (job.error || !job.data) {
    return (
      <Alert color="red" icon={<IconAlertCircle size={18} />} title="Could not load job">
        {errorMessage(job.error)}
        <Button mt="sm" size="xs" variant="light" leftSection={<IconRefresh size={14} />} onClick={() => job.refetch()}>
          Retry
        </Button>
      </Alert>
    );
  }

  const j: Job = job.data;
  const terminal = TERMINAL.includes(j.status);
  const activeIdx = STAGES.findIndex((s) => s.key === j.stage);
  const timelineActive = j.status === "SUCCESS" ? STAGES.length : activeIdx;

  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="md">
        <Group justify="space-between">
          <Group gap="xs">
            <Title order={3}>Job</Title>
            <Badge color={STATUS_COLOR[j.status]} variant="filled">
              {j.status}
            </Badge>
            <Badge variant="outline" color="gray">
              {j.transform_type}
            </Badge>
            {j.llm_cache_hit && (
              <Tooltip label="An identical prompt was served from the Redis cache; the LLM was not called.">
                <Badge variant="light" color="teal">
                  LLM cache hit
                </Badge>
              </Tooltip>
            )}
          </Group>
          <Text size="xs" c="dimmed" ff="monospace">
            {j.id}
          </Text>
        </Group>

        <Progress value={j.progress} size="lg" radius="xl" animated={!terminal} color={STATUS_COLOR[j.status]} />
        <Group justify="space-between">
          <Text size="sm">
            {j.progress}% · {j.file_key} · columns {j.columns.join(", ")}
          </Text>
          {j.duration_seconds != null && <Text size="sm" c="dimmed">{j.duration_seconds.toFixed(1)}s</Text>}
        </Group>

        <Timeline active={timelineActive} bulletSize={22} lineWidth={2} color={STATUS_COLOR[j.status]}>
          {STAGES.map((s, i) => {
            const failedHere = j.status === "FAILED" && i === activeIdx;
            const done = j.status === "SUCCESS" || i < activeIdx;
            return (
              <Timeline.Item
                key={s.key}
                title={s.label}
                bullet={failedHere ? <IconX size={14} /> : done ? <IconCheck size={14} /> : undefined}
              >
                <Text size="xs" c="dimmed">
                  {s.hint}
                </Text>
              </Timeline.Item>
            );
          })}
        </Timeline>

        {j.regex_pattern && (
          <Paper withBorder p="sm" radius="sm" bg="var(--mantine-color-gray-0)">
            <Stack gap={4}>
              <Text size="xs" fw={600} c="dimmed">
                GENERATED PATTERN
              </Text>
              <Code block>{j.regex_pattern}</Code>
              {j.replacement_template && (
                <Text size="xs">
                  Template: <Code>{j.replacement_template}</Code>
                </Text>
              )}
              {j.llm_explanation && (
                <Text size="xs" c="dimmed">
                  {j.llm_explanation}
                </Text>
              )}
            </Stack>
          </Paper>
        )}

        {j.status === "SUCCESS" && (
          <Alert color="green" variant="light" icon={<IconCheck size={18} />}>
            Processed <b>{j.row_count?.toLocaleString()}</b> rows; <b>{j.matched_rows?.toLocaleString()}</b> contained a match
            {j.matched_rows === 0 && " — the data was left unchanged"}.
          </Alert>
        )}
        {j.status === "FAILED" && (
          <Alert color="red" variant="light" icon={<IconAlertCircle size={18} />} title={j.error_code || "Failed"}>
            {j.error_message}
          </Alert>
        )}
        {j.status === "CANCELLED" && (
          <Alert color="yellow" variant="light" icon={<IconPlayerStop size={18} />}>
            The job was cancelled. Partial results were discarded.
          </Alert>
        )}
        {j.status === "QUEUED" && j.error_message && (
          <Alert color="yellow" variant="light">
            {j.error_message}
          </Alert>
        )}

        <Group justify="space-between">
          <Group>
            {!terminal && (
              <Button
                color="red"
                variant="light"
                leftSection={<IconPlayerStop size={16} />}
                loading={cancel.isPending}
                onClick={() => cancel.mutate()}
              >
                Cancel
              </Button>
            )}
          </Group>
          <Group>
            <Button variant="default" leftSection={<IconRotate size={16} />} onClick={onNewJob}>
              New transformation on this file
            </Button>
            <Button variant="subtle" color="gray" onClick={onStartOver}>
              Start over
            </Button>
          </Group>
        </Group>
      </Stack>
    </Paper>
  );
}
