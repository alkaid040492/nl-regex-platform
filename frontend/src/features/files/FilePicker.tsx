import { useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconAlertCircle, IconFileSpreadsheet, IconFileTypeCsv, IconRefresh, IconSearch } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { fileSchema, listFiles } from "../../api/endpoints";
import { errorMessage, formatBytes } from "../../api/client";
import type { Connection, S3File, SchemaPreview } from "../../api/types";

interface Props {
  connection: Connection;
  onSelected: (file: S3File, schema: SchemaPreview) => void;
  onDisconnect: () => void;
}

export function FilePicker({ connection, onSelected, onDisconnect }: Props) {
  const [filter, setFilter] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const filesQuery = useQuery({
    queryKey: ["files", connection.connection_id],
    queryFn: () => listFiles(connection.connection_id),
  });

  const schemaQuery = useQuery({
    queryKey: ["schema", connection.connection_id, selectedKey],
    queryFn: () => fileSchema(connection.connection_id, selectedKey!),
    enabled: !!selectedKey,
  });

  const files = useMemo(() => {
    const all = filesQuery.data?.files ?? [];
    const f = filter.trim().toLowerCase();
    return f ? all.filter((x) => x.key.toLowerCase().includes(f)) : all;
  }, [filesQuery.data, filter]);

  const selectedFile = files.find((f) => f.key === selectedKey) ?? filesQuery.data?.files.find((f) => f.key === selectedKey);

  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="md">
        <Group justify="space-between">
          <Group gap="xs">
            <Title order={3}>Choose a file</Title>
            <Badge variant="light">{connection.bucket}</Badge>
            <Badge variant="outline" color="gray">
              key {connection.access_key_hint}
            </Badge>
          </Group>
          <Group gap="xs">
            <Button variant="subtle" size="xs" leftSection={<IconRefresh size={14} />} onClick={() => filesQuery.refetch()}>
              Refresh
            </Button>
            <Button variant="subtle" size="xs" color="gray" onClick={onDisconnect}>
              Disconnect
            </Button>
          </Group>
        </Group>

        <TextInput
          placeholder="Filter by name…"
          leftSection={<IconSearch size={16} />}
          value={filter}
          onChange={(e) => setFilter(e.currentTarget.value)}
        />

        {filesQuery.isLoading && (
          <Group gap="xs">
            <Loader size="sm" /> <Text size="sm">Listing bucket…</Text>
          </Group>
        )}
        {filesQuery.error && (
          <Alert color="red" icon={<IconAlertCircle size={18} />} title="Could not list files">
            {errorMessage(filesQuery.error)}
          </Alert>
        )}
        {filesQuery.data && files.length === 0 && (
          <Alert color="yellow" variant="light">
            No CSV or Excel files found in this bucket{filter ? " matching your filter" : ""}.
          </Alert>
        )}

        {files.length > 0 && (
          <ScrollArea.Autosize mah={280}>
            <Table highlightOnHover verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>File</Table.Th>
                  <Table.Th>Size</Table.Th>
                  <Table.Th>Modified</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {files.map((f) => (
                  <Table.Tr
                    key={f.key}
                    style={{ cursor: "pointer" }}
                    bg={f.key === selectedKey ? "var(--mantine-color-indigo-light)" : undefined}
                    onClick={() => setSelectedKey(f.key)}
                  >
                    <Table.Td>
                      <UnstyledButton>
                        <Group gap={6}>
                          {f.kind === "csv" ? <IconFileTypeCsv size={16} /> : <IconFileSpreadsheet size={16} />}
                          <Text size="sm">{f.key}</Text>
                        </Group>
                      </UnstyledButton>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{formatBytes(f.size)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" c="dimmed">
                        {new Date(f.last_modified).toLocaleString()}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>
        )}

        {selectedKey && (
          <Paper withBorder p="sm" radius="sm" bg="var(--mantine-color-gray-0)">
            {schemaQuery.isLoading && (
              <Group gap="xs">
                <Loader size="xs" /> <Text size="sm">Reading columns…</Text>
              </Group>
            )}
            {schemaQuery.error && (
              <Alert color="red" variant="light" title="Could not read file">
                {errorMessage(schemaQuery.error)}
              </Alert>
            )}
            {schemaQuery.data && (
              <Stack gap="xs">
                <Text size="sm" fw={500}>
                  {schemaQuery.data.columns.length} columns detected
                </Text>
                <Group gap={6}>
                  {schemaQuery.data.columns.map((c) => (
                    <Badge key={c.name} variant="light" color={c.dtype === "number" ? "teal" : "indigo"}>
                      {c.name}
                    </Badge>
                  ))}
                </Group>
                {schemaQuery.data.sample_rows.length > 0 && (
                  <ScrollArea type="auto">
                    <Table fz="xs" withTableBorder withColumnBorders>
                      <Table.Thead>
                        <Table.Tr>
                          {schemaQuery.data.columns.map((c) => (
                            <Table.Th key={c.name}>{c.name}</Table.Th>
                          ))}
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {schemaQuery.data.sample_rows.map((row, i) => (
                          <Table.Tr key={i}>
                            {schemaQuery.data!.columns.map((c) => (
                              <Table.Td key={c.name} style={{ whiteSpace: "nowrap", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis" }}>
                                {row[c.name]}
                              </Table.Td>
                            ))}
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </ScrollArea>
                )}
                <Group justify="flex-end">
                  <Button onClick={() => selectedFile && onSelected(selectedFile, schemaQuery.data!)} disabled={schemaQuery.data.columns.length === 0}>
                    Use this file
                  </Button>
                </Group>
              </Stack>
            )}
          </Paper>
        )}
      </Stack>
    </Paper>
  );
}
