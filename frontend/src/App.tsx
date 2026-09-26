import { useState } from "react";
import { Anchor, AppShell, Badge, Container, Group, Stepper, Text, Title } from "@mantine/core";
import { IconBolt } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { ConnectForm } from "./features/connect/ConnectForm";
import { FilePicker } from "./features/files/FilePicker";
import { JobForm } from "./features/job/JobForm";
import { JobProgress } from "./features/job/JobProgress";
import { ResultTable } from "./features/results/ResultTable";
import { deleteConnection, getHealth } from "./api/endpoints";
import type { Connection, S3File, SchemaPreview } from "./api/types";

type Step = 0 | 1 | 2 | 3;

export default function App() {
  const [step, setStep] = useState<Step>(0);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [file, setFile] = useState<S3File | null>(null);
  const [schema, setSchema] = useState<SchemaPreview | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobDone, setJobDone] = useState(false);

  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 30_000, retry: false });

  const reset = () => {
    setStep(0);
    setConnection(null);
    setFile(null);
    setSchema(null);
    setJobId(null);
    setJobDone(false);
  };

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Container size="lg" h="100%">
          <Group h="100%" justify="space-between">
            <Group gap="xs">
              <IconBolt size={22} />
              <Title order={4}>NL Regex Platform</Title>
              <Text size="xs" c="dimmed" visibleFrom="sm">
                S3 → natural language → PySpark
              </Text>
            </Group>
            <Group gap="xs">
              <Badge
                variant="dot"
                color={health.data?.status === "ok" ? (health.data.worker === "ok" ? "green" : "yellow") : "red"}
              >
                {health.isLoading ? "checking" : health.data?.status === "ok" ? (health.data.worker === "ok" ? "all systems up" : "worker offline") : "backend down"}
              </Badge>
              <Anchor href="/flower/" target="_blank" size="xs">
                Flower
              </Anchor>
            </Group>
          </Group>
        </Container>
      </AppShell.Header>

      <AppShell.Main>
        <Container size="lg">
          <Stepper active={step} onStepClick={(i) => i < step && setStep(i as Step)} mb="lg" allowNextStepsSelect={false}>
            <Stepper.Step label="Connect" description="AWS credentials" />
            <Stepper.Step label="Pick file" description="CSV or Excel" />
            <Stepper.Step label="Describe" description="Natural language" />
            <Stepper.Step label="Results" description="Async job" />
          </Stepper>

          {step === 0 && (
            <ConnectForm
              onConnected={(c) => {
                setConnection(c);
                setStep(1);
              }}
            />
          )}

          {step === 1 && connection && (
            <FilePicker
              connection={connection}
              onSelected={(f, s) => {
                setFile(f);
                setSchema(s);
                setStep(2);
              }}
              onDisconnect={() => {
                deleteConnection(connection.connection_id).catch(() => undefined);
                reset();
              }}
            />
          )}

          {step === 2 && connection && file && schema && (
            <JobForm
              connection={connection}
              file={file}
              schema={schema}
              onSubmitted={(id) => {
                setJobId(id);
                setJobDone(false);
                setStep(3);
              }}
              onBack={() => setStep(1)}
            />
          )}

          {step === 3 && jobId && (
            <>
              <JobProgress jobId={jobId} onFinished={(ok) => setJobDone(ok)} onNewJob={() => setStep(2)} onStartOver={reset} />
              {jobDone && <ResultTable jobId={jobId} />}
            </>
          )}
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
