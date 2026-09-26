import { useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Chip,
  Group,
  MultiSelect,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconArrowLeft, IconWand } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { createJob } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import type { Connection, S3File, SchemaPreview, TransformType } from "../../api/types";

interface Props {
  connection: Connection;
  file: S3File;
  schema: SchemaPreview;
  onSubmitted: (jobId: string) => void;
  onBack: () => void;
}

const TYPE_INFO: Record<TransformType, { label: string; description: string; examples: string[] }> = {
  REPLACE: {
    label: "Replace",
    description: "Find every match of the pattern and replace it with a fixed value.",
    examples: [
      "Find email addresses and replace them with REDACTED",
      "Mask US phone numbers",
      "Remove all URLs",
      "Replace credit card numbers",
    ],
  },
  EXTRACT: {
    label: "Extract",
    description: "Copy the matched text (or a capture group) into a new column.",
    examples: ["Extract the domain of the email address", "Pull out the 4-digit year", "Extract the order id like ORD-12345"],
  },
  NORMALIZE: {
    label: "Normalize",
    description: "Rewrite matches into one consistent format using capture groups (e.g. reorder a date).",
    examples: [
      "Convert dates from yyyy/mm/dd to dd-mm-yyyy",
      "Format US phone numbers as (XXX) XXX-XXXX",
      "Mask emails but keep the domain",
    ],
  },
};

export function JobForm({ connection, file, schema, onSubmitted, onBack }: Props) {
  const [type, setType] = useState<TransformType>("REPLACE");
  const [columns, setColumns] = useState<string[]>(() => guessColumns(schema));
  const [prompt, setPrompt] = useState("");
  const [replacement, setReplacement] = useState("REDACTED");
  const [newColumn, setNewColumn] = useState("extracted");

  const columnOptions = useMemo(() => schema.columns.map((c) => ({ value: c.name, label: c.name })), [schema]);

  const mutation = useMutation({
    mutationFn: createJob,
    onSuccess: (res) => onSubmitted(res.job_id),
  });

  const canSubmit =
    columns.length > 0 && prompt.trim().length >= 3 && (type !== "EXTRACT" || /^[A-Za-z_][A-Za-z0-9_]*$/.test(newColumn));

  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="md">
        <Group justify="space-between">
          <Group gap="xs">
            <IconWand size={22} />
            <Title order={3}>Describe the transformation</Title>
          </Group>
          <Badge variant="light">{file.key}</Badge>
        </Group>

        <SegmentedControl
          fullWidth
          value={type}
          onChange={(v) => {
            setType(v as TransformType);
            setPrompt("");
          }}
          data={(Object.keys(TYPE_INFO) as TransformType[]).map((t) => ({ value: t, label: TYPE_INFO[t].label }))}
        />
        <Text size="sm" c="dimmed">
          {TYPE_INFO[type].description}
        </Text>

        <MultiSelect
          label="Target column(s)"
          description="The pattern is applied to these columns only."
          data={columnOptions}
          value={columns}
          onChange={setColumns}
          searchable
          clearable
          required
        />

        <Textarea
          label="What should the pattern match?"
          description="Plain English. A language model turns this into a regular expression, which is validated before it runs."
          placeholder={TYPE_INFO[type].examples[0]}
          minRows={2}
          autosize
          required
          value={prompt}
          onChange={(e) => setPrompt(e.currentTarget.value)}
        />
        <Group gap={6}>
          <Text size="xs" c="dimmed">
            Try:
          </Text>
          {TYPE_INFO[type].examples.map((ex) => (
            <Chip key={ex} size="xs" checked={prompt === ex} onChange={() => setPrompt(ex)} variant="outline">
              {ex}
            </Chip>
          ))}
        </Group>

        {type === "REPLACE" && (
          <TextInput
            label="Replacement value"
            description="Inserted literally in place of every match. Leave empty to delete matches."
            value={replacement}
            onChange={(e) => setReplacement(e.currentTarget.value)}
          />
        )}
        {type === "EXTRACT" && (
          <TextInput
            label="New column name"
            description="Letters, digits and underscores. With several source columns the name is suffixed per column."
            value={newColumn}
            onChange={(e) => setNewColumn(e.currentTarget.value)}
            required
            error={newColumn && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(newColumn) ? "Invalid column name" : undefined}
          />
        )}

        {mutation.error && (
          <Alert icon={<IconAlertCircle size={18} />} color="red" variant="light" title="Could not submit job">
            {errorMessage(mutation.error)}
          </Alert>
        )}

        <Group justify="space-between">
          <Button variant="default" leftSection={<IconArrowLeft size={16} />} onClick={onBack}>
            Back
          </Button>
          <Button
            loading={mutation.isPending}
            disabled={!canSubmit}
            onClick={() =>
              mutation.mutate({
                connection_id: connection.connection_id,
                file_key: file.key,
                transform_type: type,
                prompt: prompt.trim(),
                replacement: type === "REPLACE" ? replacement : undefined,
                columns,
                new_column_name: type === "EXTRACT" ? newColumn : undefined,
              })
            }
          >
            Run asynchronously
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function guessColumns(schema: SchemaPreview): string[] {
  const preferred = schema.columns.find((c) => /email|mail/i.test(c.name)) ?? schema.columns.find((c) => c.dtype === "string");
  return preferred ? [preferred.name] : [];
}
